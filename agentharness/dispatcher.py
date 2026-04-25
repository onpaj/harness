"""State transition logic, fan-out/fan-in, and next-queue dispatch."""

from __future__ import annotations

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
from agentharness.storage import (
    PipelineQueue,
    impl_artifact_path,
    phase_artifact_path,
    task_review_artifact_path,
)

log = logging.getLogger(__name__)

# Maps feature status → (next_status, next_queue_key)
_LINEAR_TRANSITIONS: dict[str, tuple[str, str]] = {
    "analyzing": ("architecting", "architect-queue"),
    "architecting": ("designing", "designer-queue"),
    "designing": ("planning", "planner-queue"),
}


async def dispatch_after_completion(
    state: FeatureState,
    completed_task: TaskMessage,
    agent_output: str,
    config: Config,
    queues: dict[str, PipelineQueue],
) -> FeatureState | None:
    """Determine and execute the next pipeline step.

    Returns the updated FeatureState, or None if no further action (fan-in wait).
    """
    status = state.status

    if status in (FeatureStatus.analyzing, FeatureStatus.architecting, FeatureStatus.designing):
        return await _dispatch_linear(state, status, config, queues)

    if status == FeatureStatus.planning:
        return await _dispatch_fan_out(state, agent_output, config, queues)

    if status in (FeatureStatus.developing, FeatureStatus.dev_revision):
        return await _dispatch_serial_next(state, completed_task, agent_output, config, queues)

    if status == FeatureStatus.reviewing:
        return await _dispatch_review_result(state, completed_task, agent_output, config, queues)

    log.warning("No dispatch logic for status %r", status)
    return None


async def _dispatch_linear(
    state: FeatureState,
    current_status: str,
    config: Config,
    queues: dict[str, PipelineQueue],
) -> FeatureState:
    next_status, queue_key = _LINEAR_TRANSITIONS[current_status]
    next_queue = queues.get(queue_key)
    if not next_queue:
        raise RuntimeError(f"Queue {queue_key!r} not found")

    agent_path = config.agent_path_for_queue(queue_key)
    feature_id = state.feature_id
    revision = 1

    input_artifacts = _artifacts_for_phase(feature_id, next_status)
    output_artifact = phase_artifact_path(feature_id, _output_name(next_status), revision)

    task = TaskMessage(
        feature_id=feature_id,
        task_id=f"{feature_id}-{next_status}-1",
        input_artifacts=input_artifacts,
        output_artifact=output_artifact,
        agent_role=agent_path.stem,
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
    design_output: str,
    config: Config,
    queues: dict[str, PipelineQueue],
) -> FeatureState:
    dev_queue = queues.get("developer-queue")
    if not dev_queue:
        raise RuntimeError("developer-queue not found")

    tasks = _parse_task_list(design_output, state.feature_id)
    if not tasks:
        log.warning("Designer produced no tasks for %s — creating fallback task", state.feature_id)
        tasks = [_fallback_developer_task(state.feature_id)]

    task_entries: list[TaskEntry] = [
        TaskEntry(
            task_id=task_msg.task_id,
            phase="developing",
            status=TaskStatus.pending,
            output_artifact=task_msg.output_artifact,
            queued_message=task_msg.model_dump(),
        )
        for task_msg in tasks
    ]

    first_task = tasks[0]
    await dev_queue.send_task(first_task)
    task_entries[0] = task_entries[0].model_copy(update={"status": TaskStatus.queued})
    log.info("Enqueued first developer task %s (%d pending)", first_task.task_id, len(tasks) - 1)

    return (
        state
        .with_status(FeatureStatus.developing)
        .with_tasks_added(task_entries)
        .with_event("serial_dispatch", phase="developing", details=f"{len(tasks)} tasks, 1 enqueued")
    )


async def _dispatch_serial_next(
    state: FeatureState,
    completed_task: TaskMessage,
    agent_output: str,
    config: Config,
    queues: dict[str, PipelineQueue],
) -> FeatureState:
    dev_status = _parse_developer_status(agent_output)
    if dev_status in ("BLOCKED", "NEEDS_CONTEXT"):
        log.warning(
            "Dev task %s reported %s — skipping review, marking feature failed",
            completed_task.task_id,
            dev_status,
        )
        return state.with_status(FeatureStatus.failed).with_event(
            "feature_failed", details=f"Task {completed_task.task_id} reported {dev_status}"
        )
    log.info("Dev task %s complete (%s), enqueuing per-task review", completed_task.task_id, dev_status)
    return await _enqueue_per_task_review(state, completed_task, queues)


async def _enqueue_per_task_review(
    state: FeatureState,
    dev_task: TaskMessage,
    queues: dict[str, PipelineQueue],
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
            phase_artifact_path(feature_id, "spec", 1),
            phase_artifact_path(feature_id, "arch-review", 1),
            dev_task.output_artifact,
        ],
        output_artifact=task_review_artifact_path(feature_id, task_name, revision),
        agent_role="reviewer",
        context=task_name,
        revision=revision,
        work_dir=dev_task.work_dir,
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
    queues: dict[str, PipelineQueue],
) -> FeatureState:
    task_name = completed_task.context or _task_name_from_id(completed_task.task_id, state.feature_id)
    failed_tasks = _parse_review_result(review_output)

    if task_name not in failed_tasks:
        next_task_entry = state.next_pending_task("developing")
        if next_task_entry is None:
            log.info("All tasks reviewed and passed for %s — done", state.feature_id)
            return state.with_status(FeatureStatus.done).with_event("feature_completed")

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

    task_msg = TaskMessage(
        feature_id=feature_id,
        task_id=task_id,
        input_artifacts=[
            phase_artifact_path(feature_id, "spec", 1),
            phase_artifact_path(feature_id, "arch-review", 1),
            phase_artifact_path(feature_id, "design", 1),
        ],
        output_artifact=output_artifact,
        agent_role="developer",
        context=f"Revise task: {task_name}",
        revision=new_revision,
        review_feedback=feedback,
        work_dir=_impl_work_dir(feature_id),
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


def _task_name_from_id(task_id: str, feature_id: str) -> str:
    """Extract task name from IDs like '{feature_id}-dev-{task_name}[-r{N}]'."""
    prefix = f"{feature_id}-dev-"
    suffix = task_id[len(prefix):]
    return re.sub(r"-r\d+$", "", suffix)


# ── Output parsers ──────────────────────────────────────────────────────────

_TASK_HEADER_RE = re.compile(r"^###\s+task:\s*(.+)$", re.MULTILINE | re.IGNORECASE)


def _parse_task_list(design_output: str, feature_id: str) -> list[TaskMessage]:
    """Extract developer tasks from designer output.

    Expected format in design.md:
        ### task: auth-module
        Implement JWT authentication middleware...

        ### task: user-api
        Create REST endpoints...
    """
    matches = list(_TASK_HEADER_RE.finditer(design_output))
    if not matches:
        return []

    tasks: list[TaskMessage] = []
    for i, match in enumerate(matches):
        task_name = match.group(1).strip().lower().replace(" ", "-")
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(design_output)
        context = design_output[start:end].strip()

        task = TaskMessage(
            feature_id=feature_id,
            task_id=f"{feature_id}-dev-{task_name}",
            input_artifacts=[
                phase_artifact_path(feature_id, "spec", 1),
                phase_artifact_path(feature_id, "arch-review", 1),
                phase_artifact_path(feature_id, "design", 1),
                phase_artifact_path(feature_id, "task-plan", 1),
            ],
            output_artifact=impl_artifact_path(feature_id, task_name, 1),
            agent_role="developer",
            context=f"Task: {task_name}\n\n{context}",
            work_dir=_impl_work_dir(feature_id),
        )
        tasks.append(task)

    return tasks


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


def _fallback_developer_task(feature_id: str) -> TaskMessage:
    return TaskMessage(
        feature_id=feature_id,
        task_id=f"{feature_id}-dev-main",
        input_artifacts=[
            phase_artifact_path(feature_id, "spec", 1),
            phase_artifact_path(feature_id, "arch-review", 1),
            phase_artifact_path(feature_id, "design", 1),
        ],
        output_artifact=impl_artifact_path(feature_id, "main", 1),
        agent_role="developer",
        context="Implement the feature as described in the spec and design documents.",
        work_dir=_impl_work_dir(feature_id),
    )


def _impl_work_dir(feature_id: str) -> str:
    return f"implementations/{feature_id}"


def _artifacts_for_phase(feature_id: str, phase: str) -> list[str]:
    """Return input artifact paths for a given pipeline phase."""
    mapping: dict[str, list[str]] = {
        "analyzing": [f"artifacts/{feature_id}/brief.md"],
        "architecting": [
            phase_artifact_path(feature_id, "spec", 1),
            f"artifacts/{feature_id}/brief.md",
        ],
        "designing": [
            phase_artifact_path(feature_id, "spec", 1),
            phase_artifact_path(feature_id, "arch-review", 1),
        ],
        "planning": [
            phase_artifact_path(feature_id, "spec", 1),
            phase_artifact_path(feature_id, "arch-review", 1),
            phase_artifact_path(feature_id, "design", 1),
        ],
    }
    return mapping.get(phase, [])


def _output_name(phase: str) -> str:
    return {
        "analyzing": "spec",
        "architecting": "arch-review",
        "designing": "design",
        "planning": "task-plan",
    }.get(phase, phase)
