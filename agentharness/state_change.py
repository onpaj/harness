"""Headless service for operator-driven feature state changes.

Used by the TUI's `S` shortcut (and by any future CLI/web surface). Owns the
single atomic mutation through `StateBackend.update()` plus the follow-up
queue enqueue. No Textual or UI imports — fully unit-testable.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Callable, Literal

from agentharness.config import Config
from agentharness.dispatcher import build_phase_task, queue_for_state
from agentharness.models import FeatureState, FeatureStatus
from agentharness.storage_protocol import StateBackend, TaskQueue

log = logging.getLogger(__name__)

StateChangeMode = Literal["restart", "rollback", "fail"]

# Rolling back to any of these statuses wipes the developer task list.
# (Anything later than `planning` keeps tasks intact.)
CLEAR_TASKS_STATES: frozenset[FeatureStatus] = frozenset({
    FeatureStatus.brainstorming,
    FeatureStatus.brainstormed,
    FeatureStatus.analyzing,
    FeatureStatus.architecting,
    FeatureStatus.designing,
    FeatureStatus.planning,
})

_ENQUEUE_RETRY_DELAY_SECONDS = 1.0


@dataclass(frozen=True)
class StateChangeResult:
    """User selection from the StateChangeModal."""
    target_status: FeatureStatus
    mode: StateChangeMode


class StateChangeError(Exception):
    """Raised when the state was persisted but the follow-up enqueue failed.

    The operator must retry from the dialog. The persisted status is attached
    so the caller can offer "retry enqueue only" without re-mutating state.
    """

    def __init__(self, message: str, persisted_status: FeatureStatus) -> None:
        super().__init__(message)
        self.persisted_status = persisted_status


QueueFactory = Callable[[str], TaskQueue]


async def apply_state_change(
    feature_id: str,
    result: StateChangeResult,
    *,
    state_mgr: StateBackend,
    queue_factory: QueueFactory,
    config: Config,
) -> None:
    """Atomically transition a feature and enqueue the follow-up phase task.

    Contract:
      - One state_mgr.update() call. The closure may run multiple times under
        lease contention; it always rebuilds the new state from the fresh
        snapshot, so retries do not duplicate the audit event.
      - Skips enqueue when the target maps to None (failed / brainstorming /
        brainstormed / done). Restarting an existing status that maps to a
        queue still enqueues (e.g. restart developing → developer-queue).
      - On enqueue failure: retries once with 1s backoff; if it still fails,
        raises StateChangeError carrying the persisted status.
    """

    def mutator(snapshot: FeatureState) -> FeatureState:
        prev_status = snapshot.status
        will_clear = (
            result.mode == "rollback"
            and result.target_status in CLEAR_TASKS_STATES
        )
        details = json.dumps({
            "from":          prev_status.value,
            "to":            result.target_status.value,
            "mode":          result.mode,
            "tasks_cleared": will_clear,
            "actor":         "tui",
        })

        if result.mode == "fail":
            return snapshot.with_status(FeatureStatus.failed).with_event(
                "manual_state_change", details=details
            )
        if result.mode == "restart":
            return snapshot.with_event("manual_state_change", details=details)
        # rollback
        new_state = snapshot.with_status(result.target_status)
        if will_clear:
            new_state = new_state.with_tasks_cleared()
        return new_state.with_event("manual_state_change", details=details)

    persisted: FeatureState = await state_mgr.update(feature_id, mutator)

    queue_name = queue_for_state(persisted.status)
    if queue_name is None:
        log.info(
            "apply_state_change: status %s has no queue — skipping enqueue",
            persisted.status.value,
        )
        return

    task = build_phase_task(persisted, persisted.status, config)
    queue = queue_factory(queue_name)
    last_exc: Exception | None = None
    try:
        for attempt in range(2):
            if attempt > 0:
                await asyncio.sleep(_ENQUEUE_RETRY_DELAY_SECONDS)
            try:
                await queue.send_task(task)
                log.info(
                    "apply_state_change: enqueued %s on %s",
                    task.task_id, queue_name,
                )
                return
            except Exception as exc:
                last_exc = exc
                log.warning(
                    "apply_state_change: enqueue attempt %d/2 failed: %s",
                    attempt + 1, exc,
                )
        raise StateChangeError(
            f"State persisted but enqueue on {queue_name!r} failed after 2 attempts: {last_exc}",
            persisted_status=persisted.status,
        )
    finally:
        try:
            await queue.close()
        except Exception:
            pass
