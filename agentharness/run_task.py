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
from datetime import UTC, datetime
from pathlib import Path

from agentharness.agent_runner import run_agent
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

    store = create_artifact_store(config, feature_id=task.feature_id)
    state_mgr = create_state_manager(config)

    all_queues: dict[str, TaskQueue] = {
        q_name: create_task_queue(config, q_name)
        for q_name in config.queue_names()
    }

    try:
        agent_path = config.agent_path_for_queue(queue_name)
        agent_def = load_agent_definition(agent_path)

        log.info("[%s] Starting task %s", WORKER_ID, task.task_id)

        started_state = await state_mgr.update(task.feature_id, lambda s: _mark_started(s, task))

        work_dir = None
        if config.storage_backend == "github" and hasattr(store, "get_work_dir"):
            work_dir = store.get_work_dir()
            work_dir.mkdir(parents=True, exist_ok=True)
        elif task.work_dir:
            work_dir = Path(task.work_dir)
            work_dir.mkdir(parents=True, exist_ok=True)

        artifact_contents: dict[str, str] = {}
        for blob_path in task.input_artifacts:
            content = await _download_with_retry(store, blob_path)
            if content is None:
                log.warning("Skipping missing artifact %s", blob_path)
                continue
            label = artifact_label(blob_path)
            artifact_contents[label] = content
            if work_dir:
                (work_dir / label).write_text(content)

        prompt = build_prompt(agent_def, task, artifact_contents)
        result = await run_agent(agent_def, prompt, work_dir=work_dir, worktree_path=started_state.worktree_path)

        await store.upload(task.output_artifact, result.output)
        log.info("[%s] Task %s complete → %s", WORKER_ID, task.task_id, task.output_artifact)

        updated_state = await state_mgr.update(task.feature_id, lambda s: _mark_completed(s, task, result.tokens))

        next_state = await dispatch_after_completion(updated_state, task, result.output, config, all_queues)
        if next_state is not None:
            persisted = await state_mgr.update(task.feature_id, lambda _: next_state)
            await run_terminal_cleanup(persisted, state_mgr)

    finally:
        for q in all_queues.values():
            await q.close()
        await store.close()


def _mark_started(state, task: TaskMessage):
    phase = state.status.value
    return (
        state
        .with_task_update(task.task_id, status=TaskStatus.in_progress, worker_id=WORKER_ID, started_at=datetime.now(UTC), pid=os.getpid())
        .with_phase(phase, PhaseInfo(status=PhaseStatus.in_progress))
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
