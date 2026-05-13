"""State transition logic, fan-out/fan-in, and next-queue dispatch."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime

from agentharness.config import Config
from agentharness.models import (
    FeatureState,
    FeatureStatus,
    PhaseInfo,
    PhaseStatus,
    TaskEntry,
    TaskMessage,
    TaskStatus,
)
from agentharness.worktree_manager import WorktreeRemovalError, remove_worktree
from agentharness.storage import (
    impl_artifact_path,
    phase_artifact_path,
    task_context_artifact_path,
    task_review_artifact_path,
)
from agentharness.storage_protocol import ArtifactStorage, StateBackend, TaskQueue

log = logging.getLogger(__name__)


async def run_terminal_cleanup(state: FeatureState, state_manager) -> None:
    """Best-effort worktree cleanup after a terminal state transition.

    - done:   remove the worktree; on failure log ERROR + persist cleanup_warning.
    - failed: log INFO preserving the worktree for operator inspection; no removal.
    - other:  no-op.
    """
    if state.worktree_path is None:
        return

    if state.status == FeatureStatus.done:
        log.info(
            "Worktree removal started for %s at %s",
            state.feature_id, state.worktree_path,
        )
        try:
            await asyncio.to_thread(remove_worktree, state.worktree_path)
            log.info(
                "Worktree removal succeeded for %s at %s",
                state.feature_id, state.worktree_path,
            )
        except WorktreeRemovalError as exc:
            log.error(
                "Worktree removal failed for %s at %s: %s",
                state.feature_id, state.worktree_path, exc,
            )
            try:
                await state_manager.set_cleanup_warning(state.feature_id, str(exc))
            except Exception as warn_exc:
                log.error(
                    "Failed to persist cleanup_warning for %s: %s",
                    state.feature_id, warn_exc,
                )

    elif state.status == FeatureStatus.failed:
        log.info(
            "Preserving worktree at %s for inspection (feature %s failed)",
            state.worktree_path, state.feature_id,
        )
        # Epic child failure: apply pause label + post comment
        if state.epic_parent is not None:
            from agentharness.github_state import GitHubStateManager
            if isinstance(state_manager, GitHubStateManager):
                await state_manager.handle_epic_child_failed(
                    state,
                    reason=f"Feature {state.feature_id} reached failed status",
                )
            else:
                log.warning(
                    "Epic pause label only supported on GitHub backend; skipping for %s",
                    state.feature_id,
                )


# Maps feature status → (next_status, next_queue_key)
_LINEAR_TRANSITIONS: dict[str, tuple[str, str]] = {
    "architecting": ("designing", "designer-queue"),
    "designing": ("planning", "planner-queue"),
}


# Authoritative state→queue mapping. Used by the dispatcher and by the
# manual state-change service (state_change.apply_state_change).
STATE_TO_QUEUE: dict[FeatureStatus, str | None] = {
    FeatureStatus.brainstorming: None,
    FeatureStatus.brainstormed:  None,
    FeatureStatus.analyzing:     "analyst-queue",
    FeatureStatus.questioning:   "product-queue",
    FeatureStatus.architecting:  "architect-queue",
    FeatureStatus.designing:     "designer-queue",
    FeatureStatus.planning:      "planner-queue",
    FeatureStatus.developing:    "developer-queue",
    FeatureStatus.dev_revision:  "developer-queue",
    FeatureStatus.reviewing:     "review-queue",
    FeatureStatus.done:          None,
    FeatureStatus.failed:        None,
}


def queue_for_state(status: FeatureStatus) -> str | None:
    """Return the queue name to enqueue a task on for a given feature status, or None
    when the status is terminal or pre-pipeline (brainstorming/brainstormed/done/failed)."""
    return STATE_TO_QUEUE.get(status)


async def dispatch_after_completion(
    state: FeatureState,
    completed_task: TaskMessage,
    agent_output: str,
    config: Config,
    queues: dict[str, TaskQueue],
    state_mgr: StateBackend | None = None,
    *,
    store: ArtifactStorage | None = None,
) -> FeatureState | None:
    """Determine and execute the next pipeline step.

    Returns the updated FeatureState, or None if no further action (fan-in wait).
    """
    status = state.status

    if status == FeatureStatus.analyzing:
        analyst_status = _parse_analyst_status(agent_output)
        cfg = state.config
        cap_reached = cfg.current_analyst_iteration >= cfg.max_analyst_iterations
        if analyst_status == "COMPLETE" or cap_reached:
            if analyst_status == "HAS_QUESTIONS" and cap_reached:
                log.warning(
                    "max_analyst_iterations cap reached — proceeding to architecting "
                    "(feature_id=%s, current=%d, max=%d)",
                    state.feature_id,
                    cfg.current_analyst_iteration,
                    cfg.max_analyst_iterations,
                )
            return await _dispatch_linear_to(state, "architecting", "architect-queue", config, queues)
        return await _dispatch_questioning(state, config, queues)

    if status == FeatureStatus.questioning:
        return await _dispatch_analyst_rerun(state, config, queues)

    if status == FeatureStatus.architecting:
        if _parse_architect_skip_design(agent_output):
            log.info("Architect signalled skip-design — jumping straight to planning for %s", state.feature_id)
            return await _dispatch_linear_to(state, "planning", "planner-queue", config, queues)
        return await _dispatch_linear(state, status, config, queues)

    if status == FeatureStatus.designing:
        return await _dispatch_linear(state, status, config, queues)

    if status == FeatureStatus.planning:
        return await _dispatch_fan_out(state, agent_output, config, queues)

    if status in (FeatureStatus.developing, FeatureStatus.dev_revision):
        return await _dispatch_serial_next(state, completed_task, agent_output, config, queues, state_mgr, store=store)

    if status == FeatureStatus.reviewing:
        return await _dispatch_review_result(state, completed_task, agent_output, config, queues, state_mgr, store=store)

    log.warning("No dispatch logic for status %r", status)
    return None


async def _dispatch_linear(
    state: FeatureState,
    current_status: str,
    config: Config,
    queues: dict[str, TaskQueue],
) -> FeatureState:
    next_status, queue_key = _LINEAR_TRANSITIONS[current_status]
    next_queue = queues.get(queue_key)
    if not next_queue:
        raise RuntimeError(f"Queue {queue_key!r} not found")

    agent_path = config.agent_path_for_queue(queue_key)
    feature_id = state.feature_id
    revision = 1

    input_artifacts = _artifacts_for_phase(state, next_status)
    output_artifact = phase_artifact_path(feature_id, _output_name(next_status), revision)

    task = TaskMessage(
        feature_id=feature_id,
        task_id=f"{feature_id}-{next_status}-1",
        input_artifacts=input_artifacts,
        output_artifact=output_artifact,
        agent_role=agent_path.stem,
        state_issue_number=state.state_issue_number,
    )
    await next_queue.send_task(task)
    log.info("Enqueued %s task for feature %s", next_status, feature_id)

    phase_info = PhaseInfo(status=PhaseStatus.pending)
    return (
        state
        .with_status(FeatureStatus(next_status))
        .with_phase(next_status, phase_info)
        .with_event("phase_enqueued", phase=next_status)
    )


async def _dispatch_linear_to(
    state: FeatureState,
    next_status: str,
    queue_key: str,
    config: Config,
    queues: dict[str, TaskQueue],
) -> FeatureState:
    """Like _dispatch_linear but with explicit destination. Used when the
    transition is not in _LINEAR_TRANSITIONS."""
    next_queue = queues.get(queue_key)
    if not next_queue:
        raise RuntimeError(f"Queue {queue_key!r} not found")

    agent_path = config.agent_path_for_queue(queue_key)
    feature_id = state.feature_id

    input_artifacts = _artifacts_for_phase(state, next_status)
    output_artifact = phase_artifact_path(feature_id, _output_name(next_status), 1)

    task = TaskMessage(
        feature_id=feature_id,
        task_id=f"{feature_id}-{next_status}-1",
        input_artifacts=input_artifacts,
        output_artifact=output_artifact,
        agent_role=agent_path.stem,
        state_issue_number=state.state_issue_number,
    )
    await next_queue.send_task(task)
    log.info("Enqueued %s task for feature %s", next_status, feature_id)

    phase_info = PhaseInfo(status=PhaseStatus.pending)
    return (
        state
        .with_status(FeatureStatus(next_status))
        .with_phase(next_status, phase_info)
        .with_event("phase_enqueued", phase=next_status)
    )


async def _dispatch_fan_out(
    state: FeatureState,
    planner_output: str,
    config: Config,
    queues: dict[str, TaskQueue],
) -> FeatureState:
    dev_queue = queues.get("developer-queue")
    if not dev_queue:
        raise RuntimeError("developer-queue not found")

    feature_id = state.feature_id
    task_msg = TaskMessage(
        feature_id=feature_id,
        task_id=f"{feature_id}-dev-main",
        input_artifacts=[
            phase_artifact_path(feature_id, "spec", _latest_spec_revision(state)),
            phase_artifact_path(feature_id, "arch-review", 1),
            phase_artifact_path(feature_id, "design", 1),
            phase_artifact_path(feature_id, "task-plan", 1),
        ],
        output_artifact=impl_artifact_path(feature_id, "main", 1),
        agent_role="developer",
        work_dir=_impl_work_dir(feature_id),
        state_issue_number=state.state_issue_number,
    )
    task_entry = TaskEntry(
        task_id=task_msg.task_id,
        phase="developing",
        status=TaskStatus.queued,
        output_artifact=task_msg.output_artifact,
        queued_message=task_msg.model_dump(),
    )
    await dev_queue.send_task(task_msg)
    log.info("Enqueued developer orchestrator task for %s", feature_id)

    return (
        state
        .with_status(FeatureStatus.developing)
        .with_tasks_added([task_entry])
        .with_event("developer_dispatched", phase="developing", details="orchestrator task enqueued")
    )


async def _dispatch_questioning(
    state: FeatureState,
    config: Config,
    queues: dict[str, TaskQueue],
) -> FeatureState:
    """Enqueue the product agent to answer open questions in the latest spec."""
    product_queue = queues.get("product-queue")
    if not product_queue:
        raise RuntimeError("product-queue not found")

    feature_id = state.feature_id
    spec_rev = _latest_spec_revision(state)

    task = TaskMessage(
        feature_id=feature_id,
        task_id=f"{feature_id}-questioning-r{spec_rev}",
        input_artifacts=_artifacts_for_phase(state, "questioning"),
        output_artifact=phase_artifact_path(feature_id, "answers", spec_rev),
        agent_role="product",
        state_issue_number=state.state_issue_number,
    )
    await product_queue.send_task(task)
    log.info("Enqueued product task %s for feature %s", task.task_id, feature_id)

    return (
        state
        .with_status(FeatureStatus.questioning)
        .with_phase("questioning", PhaseInfo(status=PhaseStatus.pending))
        .with_event("phase_enqueued", phase="questioning")
    )


async def _dispatch_analyst_rerun(
    state: FeatureState,
    config: Config,
    queues: dict[str, TaskQueue],
) -> FeatureState:
    """Increment analyst iteration counter and re-enqueue the analyst task."""
    analyst_queue = queues.get("analyst-queue")
    if not analyst_queue:
        raise RuntimeError("analyst-queue not found")

    incremented = state.with_analyst_iteration_incremented()
    feature_id = incremented.feature_id
    spec_rev = _latest_spec_revision(incremented)  # iter+1 after increment

    task = TaskMessage(
        feature_id=feature_id,
        task_id=f"{feature_id}-analyzing-r{spec_rev}",
        input_artifacts=_artifacts_for_phase(incremented, "analyzing"),
        output_artifact=phase_artifact_path(feature_id, "spec", spec_rev),
        agent_role="analyst",
        state_issue_number=incremented.state_issue_number,
    )
    await analyst_queue.send_task(task)
    log.info(
        "Re-enqueued analyst task %s for feature %s (iter=%d)",
        task.task_id, feature_id, incremented.config.current_analyst_iteration,
    )

    return (
        incremented
        .with_status(FeatureStatus.analyzing)
        .with_phase("analyzing", PhaseInfo(status=PhaseStatus.pending))
        .with_event(
            "phase_enqueued",
            phase="analyzing",
            details=f"analyst iteration {incremented.config.current_analyst_iteration}",
        )
    )


async def _dispatch_serial_next(
    state: FeatureState,
    completed_task: TaskMessage,
    agent_output: str,
    config: Config,
    queues: dict[str, TaskQueue],
    state_mgr: StateBackend | None = None,
    *,
    store: ArtifactStorage | None = None,
) -> FeatureState:
    dev_status = _parse_developer_status(agent_output)
    if dev_status in ("BLOCKED", "NEEDS_CONTEXT"):
        log.warning(
            "Dev task %s reported %s — marking feature failed",
            completed_task.task_id,
            dev_status,
        )
        return state.with_status(FeatureStatus.failed).with_event(
            "feature_failed", details=f"Task {completed_task.task_id} reported {dev_status}"
        )
    log.info(
        "Dev task %s complete (%s) — in-developer review already done, marking feature done",
        completed_task.task_id,
        dev_status,
    )
    done_state = state.with_status(FeatureStatus.done).with_event("feature_completed")
    await _open_feature_pr(done_state, state_mgr, store)
    return done_state


async def _enqueue_per_task_review(
    state: FeatureState,
    dev_task: TaskMessage,
    queues: dict[str, TaskQueue],
) -> FeatureState:
    review_queue = queues.get("review-queue")
    if not review_queue:
        raise RuntimeError("review-queue not found")

    feature_id = state.feature_id
    task_name = _task_name_from_id(dev_task.task_id, feature_id)
    revision = dev_task.revision

    task = TaskMessage(
        feature_id=feature_id,
        task_id=f"{feature_id}-review-{task_name}-r{revision}",
        input_artifacts=[
            phase_artifact_path(feature_id, "spec", _latest_spec_revision(state)),
            phase_artifact_path(feature_id, "arch-review", 1),
            dev_task.output_artifact,
        ],
        output_artifact=task_review_artifact_path(feature_id, task_name, revision),
        agent_role="reviewer",
        context=task_name,
        revision=revision,
        work_dir=dev_task.work_dir,
        state_issue_number=state.state_issue_number,
    )
    await review_queue.send_task(task)
    log.info("Enqueued per-task review for %s r%d", task_name, revision)

    return (
        state
        .with_status(FeatureStatus.reviewing)
        .with_phase("reviewing", PhaseInfo(status=PhaseStatus.pending))
        .with_event("phase_enqueued", phase="reviewing", details=f"Per-task review for {task_name} r{revision}")
    )


async def _dispatch_review_result(
    state: FeatureState,
    completed_task: TaskMessage,
    review_output: str,
    config: Config,
    queues: dict[str, TaskQueue],
    state_mgr: StateBackend | None = None,
    *,
    store: ArtifactStorage | None = None,
) -> FeatureState:
    task_name = completed_task.context or _task_name_from_id(completed_task.task_id, state.feature_id)
    failed_tasks = _parse_review_result(review_output)

    if task_name not in failed_tasks:
        next_task_entry = state.next_pending_task("developing")
        if next_task_entry is None:
            log.info("All tasks reviewed and passed for %s — done", state.feature_id)
            done_state = state.with_status(FeatureStatus.done).with_event("feature_completed")
            await _open_feature_pr(done_state, state_mgr, store)
            return done_state

        dev_queue = queues.get("developer-queue")
        if not dev_queue:
            raise RuntimeError("developer-queue not found")
        next_task_msg = TaskMessage.model_validate(next_task_entry.queued_message)
        await dev_queue.send_task(next_task_msg)
        log.info("Review passed for %s, enqueuing next task %s", task_name, next_task_msg.task_id)
        return (
            state
            .with_task_update(next_task_entry.task_id, status=TaskStatus.queued)
            .with_status(FeatureStatus.developing)
            .with_event("review_passed", details=f"Task {task_name} approved, next: {next_task_msg.task_id}")
        )

    feedback = failed_tasks[task_name]
    new_revision = completed_task.revision + 1

    if new_revision > state.config.max_revisions:
        log.warning("Task %s exceeded max revisions, marking feature failed", task_name)
        return state.with_status(FeatureStatus.failed).with_event(
            "feature_failed", details=f"Max revisions exceeded for task {task_name}"
        )

    dev_queue = queues.get("developer-queue")
    if not dev_queue:
        raise RuntimeError("developer-queue not found")

    feature_id = state.feature_id
    output_artifact = impl_artifact_path(feature_id, task_name, new_revision)
    task_id = f"{feature_id}-dev-{task_name}-r{new_revision}"

    prev_revision = completed_task.revision
    task_msg = TaskMessage(
        feature_id=feature_id,
        task_id=task_id,
        input_artifacts=[
            task_context_artifact_path(feature_id, task_name),
            impl_artifact_path(feature_id, task_name, prev_revision),
            task_review_artifact_path(feature_id, task_name, prev_revision),
        ],
        output_artifact=output_artifact,
        agent_role="developer",
        context=task_name,
        revision=new_revision,
        review_feedback=feedback,
        work_dir=_impl_work_dir(feature_id),
        state_issue_number=state.state_issue_number,
    )
    task_entry = TaskEntry(
        task_id=task_id,
        phase="developing",
        status=TaskStatus.queued,
        revision=new_revision,
        output_artifact=output_artifact,
        queued_message=task_msg.model_dump(),
    )
    await dev_queue.send_task(task_msg)
    log.info("Review failed for %s, enqueuing revision r%d", task_name, new_revision)

    updated_config = state.config.model_copy(
        update={"current_revision_round": state.config.current_revision_round + 1}
    )
    return (
        state
        .with_tasks_added([task_entry])
        .model_copy(update={"config": updated_config})
        .with_status(FeatureStatus.dev_revision)
        .with_event("revision_requested", details=f"Task {task_name} r{new_revision}")
    )


# ── Helpers ─────────────────────────────────────────────────────────────────

_DEV_STATUS_RE = re.compile(
    r"^##\s+Status\s*\n(DONE|DONE_WITH_CONCERNS|BLOCKED|NEEDS_CONTEXT)", re.MULTILINE
)


def _parse_developer_status(output: str) -> str:
    """Return the developer's reported status, defaulting to DONE if absent."""
    match = _DEV_STATUS_RE.search(output)
    return match.group(1) if match else "DONE"


_ANALYST_STATUS_RE = re.compile(
    r"^##\s+Status:\s*(\S+)\s*$", re.MULTILINE
)


def _parse_analyst_status(output: str) -> str:
    """Parse analyst's '## Status:' line. Safe default: COMPLETE."""
    match = _ANALYST_STATUS_RE.search(output)
    if match and match.group(1) == "HAS_QUESTIONS":
        return "HAS_QUESTIONS"
    return "COMPLETE"


_SKIP_DESIGN_RE = re.compile(r"^##\s+Skip Design:\s*true\s*$", re.MULTILINE | re.IGNORECASE)


def _parse_architect_skip_design(output: str) -> bool:
    """Return True when the architect signals that the design phase should be skipped."""
    return bool(_SKIP_DESIGN_RE.search(output))


def _latest_spec_revision(state: FeatureState) -> int:
    """Return the revision number of the most recent spec.

    Invariant: analyst run N produces spec.r{N+1}.md where N = current_analyst_iteration.
    """
    return state.config.current_analyst_iteration + 1


def _task_name_from_id(task_id: str, feature_id: str) -> str:
    """Extract task name from IDs like '{feature_id}-dev-{task_name}[-r{N}]'."""
    prefix = f"{feature_id}-dev-"
    suffix = task_id[len(prefix):]
    return re.sub(r"-r\d+$", "", suffix)


_REVIEW_TASK_RE = re.compile(
    r"^###\s+task:\s*(.+?)\n.*?\*\*Status:\*\*\s*(PASS|REVISION_NEEDED)(.*?)(?=^###|\Z)",
    re.MULTILINE | re.DOTALL | re.IGNORECASE,
)
_ISSUES_RE = re.compile(r"\*\*Issues:\*\*(.*?)(?=\n###|\Z)", re.DOTALL)


def _parse_review_result(review_output: str) -> dict[str, str]:
    """Return mapping of task_name → feedback for tasks that need revision."""
    failed: dict[str, str] = {}
    for match in _REVIEW_TASK_RE.finditer(review_output):
        task_name = match.group(1).strip().lower().replace(" ", "-")
        status = match.group(2).upper()
        if status == "REVISION_NEEDED":
            issues_match = _ISSUES_RE.search(match.group(3))
            feedback = issues_match.group(1).strip() if issues_match else "See review output."
            failed[task_name] = feedback
    return failed


def _impl_work_dir(feature_id: str) -> str:
    return f"implementations/{feature_id}"


def _artifacts_for_phase(state: FeatureState, phase: str) -> list[str]:
    """Return input artifact paths for a given pipeline phase."""
    feature_id = state.feature_id
    iter_n = state.config.current_analyst_iteration
    spec_rev = _latest_spec_revision(state)  # = iter_n + 1

    if phase == "analyzing":
        artifacts = [f"artifacts/{feature_id}/brief.md"]
        artifacts += [phase_artifact_path(feature_id, "spec", i) for i in range(1, spec_rev)]
        artifacts += [phase_artifact_path(feature_id, "answers", i) for i in range(1, iter_n + 1)]
        return artifacts

    if phase == "questioning":
        result = [
            f"artifacts/{feature_id}/brief.md",
            phase_artifact_path(feature_id, "spec", spec_rev),
        ]
        result += [phase_artifact_path(feature_id, "answers", i) for i in range(1, iter_n + 1)]
        return result

    latest_spec = phase_artifact_path(feature_id, "spec", spec_rev)
    if phase == "architecting":
        return [latest_spec, f"artifacts/{feature_id}/brief.md"]
    if phase == "designing":
        return [latest_spec, phase_artifact_path(feature_id, "arch-review", 1)]
    if phase == "planning":
        return [
            latest_spec,
            phase_artifact_path(feature_id, "arch-review", 1),
            phase_artifact_path(feature_id, "design", 1),
        ]
    return []


def _output_name(phase: str) -> str:
    return {
        "analyzing": "spec",
        "architecting": "arch-review",
        "designing": "design",
        "planning": "task-plan",
    }.get(phase, phase)



def build_phase_task(
    state: FeatureState,
    target_status: FeatureStatus,
    config: Config,
) -> TaskMessage:
    """Construct a TaskMessage for any pipeline phase.

    For phase agents (analyzing/architecting/designing/planning), build the
    TaskMessage from scratch using artifact path helpers.

    For developer/dev_revision phases, return the TaskMessage from the
    in-progress developer task's queued_message, falling back to the next
    pending task's queued_message.

    For the reviewing phase, return the review TaskMessage derived from the
    in-progress developer task.

    Raises ValueError for terminal or pre-pipeline statuses that have no queue.
    """
    queue_name = STATE_TO_QUEUE.get(target_status)
    if queue_name is None:
        raise ValueError(
            f"build_phase_task: no enqueueable task for terminal/pre-pipeline status {target_status!r}"
        )

    feature_id = state.feature_id

    if target_status in (FeatureStatus.developing, FeatureStatus.dev_revision):
        candidate = next(
            (t for t in state.tasks if t.phase == "developing" and t.status == TaskStatus.in_progress),
            None,
        )
        if candidate is None:
            candidate = state.next_pending_task("developing")

        if candidate is None or not candidate.queued_message:
            raise ValueError(
                f"No developer task available to enqueue for feature {feature_id!r}"
            )
        return TaskMessage.model_validate(candidate.queued_message)

    if target_status == FeatureStatus.reviewing:
        in_progress = next(
            (t for t in state.tasks if t.phase == "developing" and t.status == TaskStatus.in_progress),
            None,
        )
        if in_progress is None or not in_progress.queued_message:
            raise ValueError(
                f"No in-progress developer task found for review in feature {feature_id!r}"
            )
        dev_task = TaskMessage.model_validate(in_progress.queued_message)
        task_name = _task_name_from_id(dev_task.task_id, feature_id)
        revision = dev_task.revision
        return TaskMessage(
            feature_id=feature_id,
            task_id=f"{feature_id}-review-{task_name}-r{revision}",
            input_artifacts=[
                phase_artifact_path(feature_id, "spec", _latest_spec_revision(state)),
                phase_artifact_path(feature_id, "arch-review", 1),
                dev_task.output_artifact,
            ],
            output_artifact=task_review_artifact_path(feature_id, task_name, revision),
            agent_role="reviewer",
            context=task_name,
            revision=revision,
            work_dir=dev_task.work_dir,
            state_issue_number=state.state_issue_number,
        )

    # Phase agents: analyzing, questioning, architecting, designing, planning
    phase = target_status.value
    input_artifacts = _artifacts_for_phase(state, phase)

    if phase == "analyzing":
        spec_rev = _latest_spec_revision(state)
        output_artifact = phase_artifact_path(feature_id, "spec", spec_rev)
        task_id = f"{feature_id}-analyzing-r{spec_rev}"
    elif phase == "questioning":
        spec_rev = _latest_spec_revision(state)
        output_artifact = phase_artifact_path(feature_id, "answers", spec_rev)
        task_id = f"{feature_id}-questioning-r{spec_rev}"
    else:
        output_artifact = phase_artifact_path(feature_id, _output_name(phase), 1)
        task_id = f"{feature_id}-{phase}-1"

    agent_role = config.agent_path_for_queue(queue_name).stem
    return TaskMessage(
        feature_id=feature_id,
        task_id=task_id,
        input_artifacts=input_artifacts,
        output_artifact=output_artifact,
        agent_role=agent_role,
        state_issue_number=state.state_issue_number,
    )


def _extract_brief_title(content: str) -> str:
    """Return a human-readable title from a brief.

    Priority:
      1. First line starting with '#' — return text with leading '#' chars
         and surrounding whitespace stripped.
      2. First non-empty stripped line.
      3. Empty string when input has no usable content.

    Pure: no I/O, O(n) on input length.
    """
    first_non_empty: str | None = None
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            return line.lstrip("#").strip()
        if first_non_empty is None:
            first_non_empty = line
    return first_non_empty or ""


_CONVENTIONAL_COMMIT_RE = re.compile(
    r'^(?:feat|fix|chore|refactor|docs|test|ci|perf|style)(?:\([^)]+\))?!?: .+',
    re.IGNORECASE,
)


def _format_pr_title(raw_title: str) -> str:
    """Wrap *raw_title* in conventional-commit format if it isn't already."""
    if not raw_title or _CONVENTIONAL_COMMIT_RE.match(raw_title):
        return raw_title
    return f"feat: {raw_title}"


def _extract_brief_body(content: str) -> str | None:
    """Return the brief content after the first heading, stripped.

    Used as a fallback PR description when the developer impl has no ## PR Summary.
    Returns None when content is empty or has no body after the title.
    """
    lines = content.splitlines()
    past_title = False
    buffer: list[str] = []
    for line in lines:
        if not past_title:
            if line.strip().startswith("#"):
                past_title = True
            continue
        buffer.append(line)
    body = "\n".join(buffer).strip()
    return body if body else None


_PR_SUMMARY_HEADER = "## PR Summary"


def _extract_pr_summary(impl_content: str) -> str | None:
    """Return the body of the '## PR Summary' section, or None if absent/empty.

    Scanner:
      BEFORE_SECTION → stripped line == _PR_SUMMARY_HEADER → IN_SECTION
      IN_SECTION → line starts with '## ' → DONE (stop collecting)
      IN_SECTION → else → append line to buffer

    Returns None when:
      - Section is absent
      - Body is empty or whitespace-only after rstrip
      - Body contains only an empty '### Changes' heading with no list items
    Subheadings like '### Changes' (3 hashes) are preserved verbatim.
    """
    in_section = False
    buffer: list[str] = []
    for line in impl_content.splitlines():
        stripped = line.strip()
        if not in_section:
            if stripped == _PR_SUMMARY_HEADER:
                in_section = True
            continue
        if line.startswith("## "):
            break
        buffer.append(line)

    body = "\n".join(buffer).rstrip()
    if not body.strip():
        return None

    non_empty_lines = [ln for ln in body.splitlines() if ln.strip()]
    if non_empty_lines == ["### Changes"]:
        return None

    return body


def _last_developer_artifact(state: FeatureState) -> str | None:
    """Return the output_artifact of the last completed developer task.

    Walks state.tasks in insertion order; returns the path of the last entry
    whose phase == 'developing', status == completed, and output_artifact is set.
    Returns None when no such entry exists.
    """
    last: str | None = None
    for entry in state.tasks:
        if (
            entry.phase == "developing"
            and entry.status == TaskStatus.completed
            and entry.output_artifact is not None
        ):
            last = entry.output_artifact
    return last


_BRIEF_PATH_TEMPLATE = "artifacts/{feature_id}/brief.md"
_SPEC_TITLE_PREFIXES = ("Specification: ", "Spec: ", "Feature Specification: ", "Feature Spec: ")


def _extract_spec_title(content: str) -> str:
    """Extract title from a spec artifact, stripping analyst-added prefixes.

    Strips prefixes like "Specification: " that analysts prepend to spec headings,
    leaving only the human-readable description.
    """
    raw = _extract_brief_title(content)
    if not raw:
        return ""
    for prefix in _SPEC_TITLE_PREFIXES:
        if raw.lower().startswith(prefix.lower()):
            return raw[len(prefix):].strip()
    return raw


async def _build_pr_content(
    state: FeatureState,
    store: ArtifactStorage | None,
) -> tuple[str | None, str | None]:
    """Assemble (pr_title, pr_summary) for the GitHub PR; never raises.

    Returns (None, None) when *store* is None — the caller falls back to
    log-style PR content. Otherwise downloads brief.md and the last completed
    developer impl artifact, extracts title + summary, and logs INFO on each
    fallback path. Unexpected exceptions are caught with log.exception.

    Title priority: spec artifact (analyst-generated, descriptive) > brief heading.
    """
    if store is None:
        return None, None

    feature_id = state.feature_id
    pr_title: str | None = None
    pr_summary: str | None = None
    brief_content: str | None = None

    try:
        brief_path = _BRIEF_PATH_TEMPLATE.format(feature_id=feature_id)
        try:
            brief_content = await store.download(brief_path)
        except Exception as exc:
            log.info(
                "[%s] PR title fallback: brief.md not available (%s)",
                feature_id, exc,
            )
        else:
            extracted = _extract_brief_title(brief_content)
            if extracted:
                pr_title = _format_pr_title(extracted)
            else:
                log.info(
                    "[%s] PR title fallback: brief.md has no heading or content",
                    feature_id,
                )

        # Try spec artifact for a more descriptive title (overrides brief heading).
        spec_path = phase_artifact_path(feature_id, "spec", _latest_spec_revision(state))
        try:
            spec_content = await store.download(spec_path)
            spec_title = _extract_spec_title(spec_content)
            if spec_title:
                pr_title = _format_pr_title(spec_title)
        except Exception:
            pass

        impl_path = _last_developer_artifact(state)
        if impl_path is None:
            log.info(
                "[%s] PR summary fallback: no completed developer task in state",
                feature_id,
            )
        else:
            try:
                impl_content = await store.download(impl_path)
            except Exception as exc:
                log.info(
                    "[%s] PR summary fallback: impl artifact not available (%s)",
                    feature_id, exc,
                )
            else:
                pr_summary = _extract_pr_summary(impl_content)
                if pr_summary is None:
                    log.info(
                        "[%s] PR summary fallback: no ## PR Summary section in impl artifact",
                        feature_id,
                    )

        if pr_summary is None and brief_content:
            pr_summary = _extract_brief_body(brief_content)

        return pr_title, pr_summary

    except Exception:
        log.exception(
            "[%s] Unexpected error building PR content; falling back to defaults",
            feature_id,
        )
        return None, None


async def _open_feature_pr(
    state: FeatureState,
    state_mgr: StateBackend | None,
    store: ArtifactStorage | None = None,
) -> None:
    """Open a GitHub PR for the completed feature via the state backend abstraction.

    For epic children: opens a per-child PR targeting the epic branch (via open_review),
    then ticks the umbrella PR checklist (via handle_epic_child_done).
    For non-epic features: opens a regular PR targeting the default branch.
    """
    if state_mgr is None:
        return

    pr_title, pr_summary = await _build_pr_content(state, store)
    try:
        await state_mgr.open_review(
            state.feature_id,
            pr_title=pr_title,
            pr_summary=pr_summary,
        )
    except Exception:
        if state.epic_parent is None:
            raise  # non-epic: propagate as before
        log.exception(
            "[%s] open_review raised unexpectedly; will still attempt epic checklist update",
            state.feature_id,
        )

    if state.epic_parent is not None:
        from agentharness.github_state import GitHubStateManager
        if isinstance(state_mgr, GitHubStateManager):
            await state_mgr.handle_epic_child_done(state)
        else:
            log.warning(
                "Epic PR lifecycle only supported on GitHub backend; skipping for %s",
                state.feature_id,
            )
