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
    review_artifact_path,
)

log = logging.getLogger(__name__)

# Maps feature status → (next_status, next_queue_key)
# None queue_key means fan-in wait (not all tasks done yet)
_LINEAR_TRANSITIONS: dict[str, tuple[str, str]] = {
    "planning": ("architecting", "architect-queue"),
    "architecting": ("designing", "designer-queue"),
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

    if status in (FeatureStatus.planning, FeatureStatus.architecting):
        return await _dispatch_linear(state, status, config, queues)

    if status == FeatureStatus.designing:
        return await _dispatch_fan_out(state, agent_output, config, queues)

    if status in (FeatureStatus.developing, FeatureStatus.dev_revision):
        return await _check_fan_in(state, completed_task, config, queues)

    if status == FeatureStatus.reviewing:
        return await _dispatch_review_result(state, agent_output, config, queues)

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

    agent_path = config.agent_path_for_queue("developer-queue")

    task_entries: list[TaskEntry] = []
    for task_msg in tasks:
        await dev_queue.send_task(task_msg)
        task_entries.append(
            TaskEntry(
                task_id=task_msg.task_id,
                phase="developing",
                status=TaskStatus.queued,
                output_artifact=task_msg.output_artifact,
                queued_message=task_msg.model_dump(),
            )
        )
        log.info("Enqueued developer task %s", task_msg.task_id)

    return (
        state
        .with_status(FeatureStatus.developing)
        .with_tasks_added(task_entries)
        .with_event("fan_out", phase="developing", details=f"{len(tasks)} tasks enqueued")
    )


async def _check_fan_in(
    state: FeatureState,
    completed_task: TaskMessage,
    config: Config,
    queues: dict[str, PipelineQueue],
) -> FeatureState | None:
    if not state.all_tasks_complete("developing"):
        log.info(
            "Fan-in: task %s done, waiting for other developer tasks",
            completed_task.task_id,
        )
        return None

    log.info("Fan-in: all developer tasks complete for %s, triggering review", state.feature_id)
    return await _enqueue_review(state, config, queues)


async def _enqueue_review(
    state: FeatureState,
    config: Config,
    queues: dict[str, PipelineQueue],
) -> FeatureState:
    review_queue = queues.get("review-queue")
    if not review_queue:
        raise RuntimeError("review-queue not found")

    revision = state.config.current_revision_round + 1
    feature_id = state.feature_id

    task = TaskMessage(
        feature_id=feature_id,
        task_id=f"{feature_id}-review-{revision}",
        input_artifacts=[
            phase_artifact_path(feature_id, "spec", 1),
            phase_artifact_path(feature_id, "arch-review", 1),
        ],
        output_artifact=review_artifact_path(feature_id, revision),
        agent_role="reviewer",
        work_dir=_impl_work_dir(feature_id),
    )
    await review_queue.send_task(task)

    return (
        state
        .with_status(FeatureStatus.reviewing)
        .with_phase("reviewing", PhaseInfo(status=PhaseStatus.pending))
        .with_event("phase_enqueued", phase="reviewing")
    )


async def _dispatch_review_result(
    state: FeatureState,
    review_output: str,
    config: Config,
    queues: dict[str, PipelineQueue],
) -> FeatureState:
    failed_tasks = _parse_review_result(review_output)

    if not failed_tasks:
        log.info("Review passed for feature %s", state.feature_id)
        return state.with_status(FeatureStatus.done).with_event("feature_completed")

    revision_round = state.config.current_revision_round + 1
    if revision_round > state.config.max_revisions:
        log.warning(
            "Feature %s exceeded max revisions (%d), marking failed",
            state.feature_id,
            state.config.max_revisions,
        )
        return state.with_status(FeatureStatus.failed).with_event(
            "feature_failed", details="Max revisions exceeded"
        )

    log.info(
        "Review found %d failing tasks for %s (revision round %d)",
        len(failed_tasks),
        state.feature_id,
        revision_round,
    )
    dev_queue = queues.get("developer-queue")
    if not dev_queue:
        raise RuntimeError("developer-queue not found")

    new_task_entries: list[TaskEntry] = []
    for task_name, feedback in failed_tasks.items():
        new_revision = revision_round + 1
        output_artifact = impl_artifact_path(state.feature_id, task_name, new_revision)
        task_id = f"{state.feature_id}-dev-{task_name}-r{new_revision}"

        task_msg = TaskMessage(
            feature_id=state.feature_id,
            task_id=task_id,
            input_artifacts=[
                phase_artifact_path(state.feature_id, "spec", 1),
                phase_artifact_path(state.feature_id, "arch-review", 1),
                phase_artifact_path(state.feature_id, "design", 1),
            ],
            output_artifact=output_artifact,
            agent_role="developer",
            context=f"Revise task: {task_name}",
            revision=new_revision,
            review_feedback=feedback,
            work_dir=_impl_work_dir(state.feature_id),
        )
        await dev_queue.send_task(task_msg)

        new_task_entries.append(
            TaskEntry(
                task_id=task_id,
                phase="developing",
                status=TaskStatus.queued,
                revision=new_revision,
                output_artifact=output_artifact,
                queued_message=task_msg.model_dump(),
            )
        )

    updated_config = state.config.model_copy(
        update={"current_revision_round": revision_round}
    )
    return (
        state
        .with_status(FeatureStatus.dev_revision)
        .with_tasks_added(new_task_entries)
        .model_copy(update={"config": updated_config})
        .with_event(
            "revision_requested",
            details=f"Round {revision_round}, {len(failed_tasks)} tasks",
        )
    )


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
        "planning": [f"artifacts/{feature_id}/brief.md"],
        "architecting": [
            phase_artifact_path(feature_id, "spec", 1),
            f"artifacts/{feature_id}/brief.md",
        ],
        "designing": [
            phase_artifact_path(feature_id, "spec", 1),
            phase_artifact_path(feature_id, "arch-review", 1),
        ],
    }
    return mapping.get(phase, [])


def _output_name(phase: str) -> str:
    return {
        "planning": "spec",
        "architecting": "arch-review",
        "designing": "design",
    }.get(phase, phase)
