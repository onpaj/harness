"""Single-task runner — reads TaskMessage JSON from stdin, processes it, exits.

Invoked by the observer as a subprocess. Writes all logs to stdout so the
observer can redirect them to a per-task log file.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import socket
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from agentharness.agent_runner import RunResult, run_agent
from agentharness.config import Config
from agentharness.dispatcher import dispatch_after_completion, run_terminal_cleanup
from agentharness.models import (
    FeatureStatus,
    PhaseInfo,
    PhaseStatus,
    TaskMessage,
    TaskStatus,
    TokenUsage,
)
from agentharness.prompt_builder import artifact_label, build_prompt, load_agent_definition
from agentharness.storage import create_artifact_store, create_state_manager, create_task_queue
from agentharness.storage_protocol import ArtifactStorage, TaskQueue

log = logging.getLogger(__name__)

WORKER_ID = f"{socket.gethostname()}-{os.getpid()}"


async def run_task(queue_name: str, task_json: str, config: Config) -> None:
    task = TaskMessage.model_validate_json(task_json)

    state_mgr = create_state_manager(config)
    store: ArtifactStorage | None = None
    all_queues: dict[str, TaskQueue] = {}
    agent_def = None
    try:
        if task.state_issue_number is not None:
            from agentharness.github_state import GitHubStateManager
            if isinstance(state_mgr, GitHubStateManager):
                feature_state = await state_mgr.get(task.feature_id, task.state_issue_number)
            else:
                feature_state = await state_mgr.get(task.feature_id)
        else:
            feature_state = await state_mgr.get(task.feature_id)

        # Defensive guard: if a developer/review task's id was wiped out by a
        # manual rollback, drop the message and emit an audit event rather than
        # crash mid-execution. Phase-level messages do not have TaskEntry rows
        # and must continue to execute (their task_id pattern is feature-{phase}-N).
        if _is_per_task_message(task.task_id, task.feature_id):
            current_ids = {t.task_id for t in feature_state.tasks}
            if task.task_id not in current_ids:
                log.warning(
                    "Dropping orphan task %s — no matching TaskEntry in state",
                    task.task_id,
                )
                await state_mgr.update(
                    task.feature_id,
                    lambda s: s.with_event(
                        "dropped_orphan_task",
                        task_id=task.task_id,
                        details=f'task_id {task.task_id!r} no longer in state.tasks',
                    ),
                )
                return

        branch_name = feature_state.branch_name or task.feature_id
        store = create_artifact_store(config, feature_id=branch_name, base_branch=feature_state.epic_branch)

        all_queues = {
            q_name: create_task_queue(config, q_name)
            for q_name in config.queue_names()
        }

        agent_path = config.agent_path_for_queue(queue_name)
        agent_def = load_agent_definition(agent_path)

        log.info("[%s] Starting task %s", WORKER_ID, task.task_id)

        started_state = await state_mgr.update(task.feature_id, lambda s: _mark_started(s, task, queue_name))

        # Developer agents (allowed_tools set) write code to the feature-branch clone.
        # Output-only agents (output_file_glob, no allowed_tools) just need a scratch
        # directory for their single output file; using the clone root for them pollutes
        # the branch with uncommitted debris and triggers unnecessary git pushes.
        if agent_def.allowed_tools:
            work_dir = store.get_work_dir()
        else:
            work_dir = None
        if work_dir is None and task.work_dir:
            work_dir = Path(task.work_dir)
        if work_dir is None and agent_def.output_file_glob:
            work_dir = Path(tempfile.mkdtemp(prefix=f"agent-{agent_def.id}-"))
        if work_dir is not None:
            work_dir.mkdir(parents=True, exist_ok=True)

        if hasattr(store, "sync_working_branch"):
            log.info("[%s] Syncing working branch for task %s", WORKER_ID, task.task_id)
            await store.sync_working_branch()

        artifact_contents: dict[str, str] = {}
        for blob_path in task.input_artifacts:
            content = await _download_with_retry(store, blob_path)
            if content is None:
                log.warning("Skipping missing artifact %s", blob_path)
                continue
            label = artifact_label(blob_path)
            artifact_contents[label] = content
            if work_dir:
                dest = work_dir / blob_path
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(content)

        prompt = build_prompt(agent_def, task, artifact_contents)
        result = await run_agent(agent_def, prompt, work_dir=work_dir, worktree_path=started_state.worktree_path)

        if agent_def.output_file_glob and work_dir:
            result = _resolve_output_file(result, agent_def.output_file_glob, work_dir)

        if agent_def.allowed_tools:
            committed = await store.commit_workdir_changes(f"agent: {agent_def.id} output {task.task_id}")
            if committed:
                log.info("[%s] Committed workdir changes for task %s", WORKER_ID, task.task_id)
            else:
                log.info("[%s] No workdir changes to commit for task %s", WORKER_ID, task.task_id)

        await store.upload(task.output_artifact, result.output)
        log.info("[%s] Task %s complete → %s", WORKER_ID, task.task_id, task.output_artifact)

        updated_state = await state_mgr.update(task.feature_id, lambda s: _mark_completed(s, task, result.tokens))

        next_state = await dispatch_after_completion(updated_state, task, result.output, config, all_queues, state_mgr, store=store)
        if next_state is not None:
            persisted = await state_mgr.update(task.feature_id, lambda _: next_state)
            await run_terminal_cleanup(persisted, state_mgr)

    except Exception as exc:
        log.error("[%s] Task %s failed: %s", WORKER_ID, task.task_id, exc, exc_info=True)
        retry_limit = agent_def.retry_limit if agent_def else 0
        await _recover_task(state_mgr, task, queue_name, config, all_queues, retry_limit)
        sys.exit(1)

    finally:
        for q in all_queues.values():
            await q.close()
        if store is not None:
            await store.close()


def _count_recent_requeue_attempts(history: list, task_id: str) -> int:
    """Count task_requeued events since the last phase_resumed or pipeline_started.

    Resets the counter on manual resume so users can retry without immediately
    exhausting the retry limit from a previous failed run.

    history is chronological (append-only); we scan from newest to oldest.
    """
    count = 0
    for event in reversed(history):
        if event.event in ("phase_resumed", "pipeline_started"):
            break
        if event.event == "task_requeued" and event.task_id == task_id:
            count += 1
    return count


async def _recover_task(
    state_mgr,
    task: TaskMessage,
    queue_name: str,
    config: Config,
    all_queues: dict[str, TaskQueue],
    retry_limit: int,
) -> None:
    """Mark a failed task for retry or permanent failure and update state."""
    try:
        current = await state_mgr.get(task.feature_id)
        attempts = _count_recent_requeue_attempts(current.history, task.task_id) + 1

        if attempts < retry_limit:
            log.info("[%s] Requeueing task %s (attempt %d/%d)", WORKER_ID, task.task_id, attempts, retry_limit)
            await state_mgr.update(
                task.feature_id,
                lambda s: s.with_task_update(
                    task.task_id,
                    status=TaskStatus.queued,
                    worker_id=None,
                    started_at=None,
                ).with_event("task_requeued", task_id=task.task_id, details=f"attempt {attempts}/{retry_limit}"),
            )
            q = all_queues.get(queue_name)
            if q:
                await q.send_task(task)
        else:
            log.warning("[%s] Task %s exhausted retries — marking failed", WORKER_ID, task.task_id)
            await state_mgr.update(
                task.feature_id,
                lambda s: s.with_task_update(task.task_id, status=TaskStatus.failed)
                .with_status(FeatureStatus.failed)
                .with_event("feature_failed", task_id=task.task_id, details="task exceeded retry limit"),
            )
    except Exception as recovery_exc:
        log.error("[%s] Recovery update failed for %s: %s", WORKER_ID, task.task_id, recovery_exc)


def _mark_started(state, task: TaskMessage, queue_name: str = ""):
    phase = state.status.value
    pid = os.getpid()
    is_phase_level = not _is_per_task_message(task.task_id, task.feature_id)
    log_file = str(Path("logs") / queue_name / f"{task.task_id}.log") if queue_name else None
    return (
        state
        .with_task_update(task.task_id, status=TaskStatus.in_progress, worker_id=WORKER_ID, started_at=datetime.now(UTC), pid=pid, log_file=log_file)
        .with_phase(phase, PhaseInfo(status=PhaseStatus.in_progress, pid=pid if is_phase_level else None))
        .with_event("task_started", phase=phase, task_id=task.task_id, worker_id=WORKER_ID)
    )


def _mark_completed(state, task: TaskMessage, tokens: TokenUsage | None = None):
    phase = state.status.value
    has_task_entry = any(t.task_id == task.task_id for t in state.tasks)
    phase_tokens = None if has_task_entry else tokens
    return (
        state
        .with_task_update(task.task_id, status=TaskStatus.completed, completed_at=datetime.now(UTC), output_artifact=task.output_artifact, tokens_used=tokens)
        .with_phase(phase, PhaseInfo(status=PhaseStatus.completed, tokens_used=phase_tokens))
        .with_event("task_completed", phase=phase, task_id=task.task_id)
    )


def _resolve_output_file(result: RunResult, glob_pattern: str, work_dir: Path) -> RunResult:
    """If the agent wrote a file matching glob_pattern, use that file's content as output."""
    import glob as _glob
    matches = sorted(
        _glob.glob(str(work_dir / glob_pattern)),
        key=lambda p: Path(p).stat().st_mtime,
        reverse=True,
    )
    if not matches:
        log.warning("output_file_glob %r matched no files in %s — using agent text output", glob_pattern, work_dir)
        return result
    plan_path = Path(matches[0])
    try:
        content = plan_path.read_text(encoding="utf-8")
        log.info("Using output file %s (%d chars) as artifact", plan_path, len(content))
        return RunResult(output=content, tokens=result.tokens)
    except OSError as exc:
        log.warning("Could not read output file %s: %s — using agent text output", plan_path, exc)
        return result


_ARTIFACT_RETRY_DELAYS = [2, 5, 10]  # seconds between attempts


async def _download_with_retry(store: ArtifactStorage, blob_path: str) -> str | None:
    for attempt, delay in enumerate([0] + _ARTIFACT_RETRY_DELAYS, start=1):
        if delay:
            await asyncio.sleep(delay)
        try:
            return await store.download(blob_path)
        except Exception as exc:
            if attempt <= len(_ARTIFACT_RETRY_DELAYS):
                log.warning(
                    "Artifact %s not yet available (attempt %d), retrying in %ds: %s",
                    blob_path, attempt, _ARTIFACT_RETRY_DELAYS[attempt - 1], exc,
                )
            else:
                log.warning("Could not download artifact %s after %d attempts: %s", blob_path, attempt, exc)
    return None


_TASK_HEADER_RE = re.compile(r"^### task:\s*(.+)$", re.IGNORECASE | re.MULTILINE)


def _parse_task_sections(output: str) -> dict[str, str]:
    """Parse ### task: name headers from agent output into named sections."""
    matches = list(_TASK_HEADER_RE.finditer(output))
    if not matches:
        return {}
    sections: dict[str, str] = {}
    for i, match in enumerate(matches):
        name = match.group(1).strip().lower().replace(" ", "-")
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(output)
        sections[name] = output[start:end].rstrip()
    return sections


async def _upload_task_contexts(store: ArtifactStorage, feature_id: str, output: str) -> dict[str, str]:
    """Upload per-task context sections to blob storage, return {name: blob_path}."""
    sections = _parse_task_sections(output)
    paths: dict[str, str] = {}
    for name, content in sections.items():
        blob_path = f"artifacts/{feature_id}/task-context/{name}.md"
        await store.upload(blob_path, content)
        paths[name] = blob_path
    return paths


def _is_per_task_message(task_id: str, feature_id: str) -> bool:
    """Return True for developer/review messages keyed to a TaskEntry.

    Phase-agent messages use the pattern '{feature_id}-{phase}-{N}'; per-task
    messages use '{feature_id}-dev-{name}[-r{N}]' or '{feature_id}-review-{name}-r{N}'.
    """
    prefix = f"{feature_id}-"
    if not task_id.startswith(prefix):
        return False
    suffix = task_id[len(prefix):]
    return suffix.startswith("dev-") or suffix.startswith("review-")


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
        force=True,
    )
    logging.getLogger("azure").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
