"""Unit tests for state_change.apply_state_change."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from agentharness.models import (
    FeatureState,
    FeatureStatus,
    TaskEntry,
    TaskMessage,
    TaskStatus,
)
from agentharness.state_change import (
    CLEAR_TASKS_STATES,
    StateChangeError,
    StateChangeMode,
    StateChangeResult,
    apply_state_change,
)


class TestConstants:
    def test_clear_tasks_states_covers_brainstorming_through_planning(self):
        assert CLEAR_TASKS_STATES == frozenset({
            FeatureStatus.brainstorming,
            FeatureStatus.brainstormed,
            FeatureStatus.analyzing,
            FeatureStatus.architecting,
            FeatureStatus.designing,
            FeatureStatus.planning,
        })

    def test_clear_tasks_states_excludes_developing_and_later(self):
        for s in (FeatureStatus.developing, FeatureStatus.dev_revision,
                  FeatureStatus.reviewing, FeatureStatus.done, FeatureStatus.failed):
            assert s not in CLEAR_TASKS_STATES


def _make_state_mgr(initial: FeatureState):
    """Return an AsyncMock that simulates StateBackend.update via a mutator closure."""
    state = {"value": initial}

    async def fake_update(feature_id, mutator):
        state["value"] = mutator(state["value"])
        return state["value"]

    async def fake_get(feature_id):
        return state["value"]

    mgr = AsyncMock()
    mgr.update.side_effect = fake_update
    mgr.get.side_effect = fake_get
    mgr._state_ref = state  # for tests to inspect
    return mgr


def _make_queue_factory():
    queues: dict[str, AsyncMock] = {}

    def factory(name: str):
        if name not in queues:
            q = AsyncMock()
            q.send_task = AsyncMock()
            q.close = AsyncMock()
            queues[name] = q
        return queues[name]

    factory.queues = queues  # type: ignore[attr-defined]
    return factory


def _config():
    cfg = MagicMock()
    from pathlib import Path
    agent_paths = {
        "analyst-queue":   Path(".agents/analyst.md"),
        "architect-queue": Path(".agents/architect.md"),
        "designer-queue":  Path(".agents/designer.md"),
        "planner-queue":   Path(".agents/planner.md"),
        "developer-queue": Path(".agents/developer.md"),
        "review-queue":    Path(".agents/reviewer.md"),
    }
    cfg.agent_path_for_queue.side_effect = lambda q: agent_paths[q]
    return cfg


@pytest.mark.asyncio
class TestApplyStateChangeFail:
    async def test_sets_status_to_failed_and_does_not_enqueue(self):
        initial = FeatureState(feature_id="feat-x", status=FeatureStatus.developing)
        mgr = _make_state_mgr(initial)
        factory = _make_queue_factory()

        await apply_state_change(
            "feat-x",
            StateChangeResult(target_status=FeatureStatus.failed, mode="fail"),
            state_mgr=mgr, queue_factory=factory, config=_config(),
        )

        persisted = mgr._state_ref["value"]
        assert persisted.status == FeatureStatus.failed
        assert factory.queues == {}  # no enqueue at all

    async def test_appends_history_event_with_metadata(self):
        initial = FeatureState(feature_id="feat-x", status=FeatureStatus.developing)
        mgr = _make_state_mgr(initial)

        await apply_state_change(
            "feat-x",
            StateChangeResult(target_status=FeatureStatus.failed, mode="fail"),
            state_mgr=mgr, queue_factory=_make_queue_factory(), config=_config(),
        )

        persisted = mgr._state_ref["value"]
        assert len(persisted.history) == 1
        evt = persisted.history[0]
        assert evt.event == "manual_state_change"
        details = json.loads(evt.details)
        assert details["from"] == "developing"
        assert details["to"] == "failed"
        assert details["mode"] == "fail"
        assert details["actor"] == "tui"


@pytest.mark.asyncio
class TestApplyStateChangeRestart:
    async def test_keeps_status_unchanged_and_enqueues(self):
        existing = TaskMessage(
            feature_id="feat-x",
            task_id="feat-x-dev-auth-r1",
            input_artifacts=[],
            output_artifact="artifacts/feat-x/impl/auth.r1.md",
            agent_role="developer",
            context="auth",
        )
        entry = TaskEntry(
            task_id=existing.task_id,
            phase="developing",
            status=TaskStatus.in_progress,
            queued_message=existing.model_dump(),
        )
        initial = FeatureState(
            feature_id="feat-x", status=FeatureStatus.developing
        ).with_tasks_added([entry])
        mgr = _make_state_mgr(initial)
        factory = _make_queue_factory()

        await apply_state_change(
            "feat-x",
            StateChangeResult(target_status=FeatureStatus.developing, mode="restart"),
            state_mgr=mgr, queue_factory=factory, config=_config(),
        )

        persisted = mgr._state_ref["value"]
        assert persisted.status == FeatureStatus.developing
        assert "developer-queue" in factory.queues
        factory.queues["developer-queue"].send_task.assert_awaited_once()


@pytest.mark.asyncio
class TestApplyStateChangeRollback:
    async def test_rollback_to_planning_clears_tasks(self):
        entry = TaskEntry(task_id="feat-x-dev-a", phase="developing", status=TaskStatus.in_progress)
        initial = FeatureState(
            feature_id="feat-x", status=FeatureStatus.developing
        ).with_tasks_added([entry])
        mgr = _make_state_mgr(initial)
        factory = _make_queue_factory()

        await apply_state_change(
            "feat-x",
            StateChangeResult(target_status=FeatureStatus.planning, mode="rollback"),
            state_mgr=mgr, queue_factory=factory, config=_config(),
        )

        persisted = mgr._state_ref["value"]
        assert persisted.status == FeatureStatus.planning
        assert persisted.tasks == []
        assert "planner-queue" in factory.queues

    async def test_rollback_to_reviewing_does_not_clear_tasks(self):
        existing = TaskMessage(
            feature_id="feat-x",
            task_id="feat-x-dev-auth-r1",
            input_artifacts=[],
            output_artifact="artifacts/feat-x/impl/auth.r1.md",
            agent_role="developer",
            context="auth",
        )
        entry = TaskEntry(
            task_id=existing.task_id,
            phase="developing",
            status=TaskStatus.in_progress,
            queued_message=existing.model_dump(),
        )
        initial = FeatureState(
            feature_id="feat-x", status=FeatureStatus.dev_revision
        ).with_tasks_added([entry])
        mgr = _make_state_mgr(initial)
        factory = _make_queue_factory()

        await apply_state_change(
            "feat-x",
            StateChangeResult(target_status=FeatureStatus.reviewing, mode="rollback"),
            state_mgr=mgr, queue_factory=factory, config=_config(),
        )

        persisted = mgr._state_ref["value"]
        assert persisted.status == FeatureStatus.reviewing
        assert len(persisted.tasks) == 1
        assert "review-queue" in factory.queues

    async def test_rollback_to_brainstorming_does_not_enqueue(self):
        initial = FeatureState(feature_id="feat-x", status=FeatureStatus.analyzing)
        mgr = _make_state_mgr(initial)
        factory = _make_queue_factory()

        await apply_state_change(
            "feat-x",
            StateChangeResult(target_status=FeatureStatus.brainstorming, mode="rollback"),
            state_mgr=mgr, queue_factory=factory, config=_config(),
        )

        persisted = mgr._state_ref["value"]
        assert persisted.status == FeatureStatus.brainstorming
        assert factory.queues == {}

    async def test_rollback_records_tasks_cleared_in_event_details(self):
        entry = TaskEntry(task_id="feat-x-dev-a", phase="developing")
        initial = FeatureState(
            feature_id="feat-x", status=FeatureStatus.developing
        ).with_tasks_added([entry])
        mgr = _make_state_mgr(initial)

        await apply_state_change(
            "feat-x",
            StateChangeResult(target_status=FeatureStatus.planning, mode="rollback"),
            state_mgr=mgr, queue_factory=_make_queue_factory(), config=_config(),
        )

        persisted = mgr._state_ref["value"]
        evt = persisted.history[-1]
        details = json.loads(evt.details)
        assert details["tasks_cleared"] is True
        assert details["mode"] == "rollback"


@pytest.mark.asyncio
class TestApplyStateChangeIdempotencyUnderRetry:
    async def test_closure_appends_only_one_event_when_invoked_twice(self):
        """Simulate lease contention: state_mgr.update calls the mutator twice."""
        initial = FeatureState(feature_id="feat-x", status=FeatureStatus.developing)
        state_holder = {"value": initial}

        async def retry_update(feature_id, mutator):
            # First attempt: discard result (simulate lease lost)
            mutator(state_holder["value"])
            # Second attempt: keep result
            state_holder["value"] = mutator(state_holder["value"])
            return state_holder["value"]

        mgr = AsyncMock()
        mgr.update.side_effect = retry_update

        await apply_state_change(
            "feat-x",
            StateChangeResult(target_status=FeatureStatus.failed, mode="fail"),
            state_mgr=mgr, queue_factory=_make_queue_factory(), config=_config(),
        )

        # One event in the persisted state — the closure rebuilt from snapshot each time
        events = [e for e in state_holder["value"].history if e.event == "manual_state_change"]
        assert len(events) == 1


@pytest.mark.asyncio
class TestApplyStateChangeEnqueueRetry:
    async def test_retries_once_then_raises_state_change_error(self, monkeypatch):
        existing = TaskMessage(
            feature_id="feat-x",
            task_id="feat-x-dev-a-r1",
            input_artifacts=[],
            output_artifact="artifacts/feat-x/impl/a.r1.md",
            agent_role="developer",
            context="a",
        )
        entry = TaskEntry(
            task_id=existing.task_id, phase="developing",
            status=TaskStatus.in_progress, queued_message=existing.model_dump(),
        )
        initial = FeatureState(
            feature_id="feat-x", status=FeatureStatus.developing
        ).with_tasks_added([entry])
        mgr = _make_state_mgr(initial)

        bad_queue = AsyncMock()
        bad_queue.send_task = AsyncMock(side_effect=RuntimeError("queue down"))
        bad_queue.close = AsyncMock()

        def factory(name):
            return bad_queue

        # Patch asyncio.sleep so the test runs fast
        import agentharness.state_change as sc
        monkeypatch.setattr(sc.asyncio, "sleep", AsyncMock())

        with pytest.raises(StateChangeError) as exc_info:
            await apply_state_change(
                "feat-x",
                StateChangeResult(target_status=FeatureStatus.developing, mode="restart"),
                state_mgr=mgr, queue_factory=factory, config=_config(),
            )

        assert exc_info.value.persisted_status == FeatureStatus.developing
        # Two attempts (one initial + one retry)
        assert bad_queue.send_task.await_count == 2


@pytest.mark.asyncio
class TestApplyStateChangeRollbackFromFailed:
    async def test_rollback_from_failed_adds_phase_resumed_event(self):
        initial = FeatureState(feature_id="feat-x", status=FeatureStatus.failed)
        mgr = _make_state_mgr(initial)

        await apply_state_change(
            "feat-x",
            StateChangeResult(target_status=FeatureStatus.analyzing, mode="rollback"),
            state_mgr=mgr, queue_factory=_make_queue_factory(), config=_config(),
        )

        persisted = mgr._state_ref["value"]
        events = [e.event for e in persisted.history]
        assert "phase_resumed" in events

    async def test_rollback_from_non_failed_does_not_add_phase_resumed(self):
        initial = FeatureState(feature_id="feat-x", status=FeatureStatus.architecting)
        mgr = _make_state_mgr(initial)

        await apply_state_change(
            "feat-x",
            StateChangeResult(target_status=FeatureStatus.analyzing, mode="rollback"),
            state_mgr=mgr, queue_factory=_make_queue_factory(), config=_config(),
        )

        persisted = mgr._state_ref["value"]
        events = [e.event for e in persisted.history]
        assert "phase_resumed" not in events


@pytest.mark.asyncio
class TestApplyStateChangeRestartCancelStale:
    """On restart, apply_state_change cancels stale queued tasks if the queue supports it."""

    def _analyzing_state(self):
        return FeatureState(feature_id="feat-x", status=FeatureStatus.analyzing)

    def _make_queue_factory_with_cancel(self, cancel_return: int = 1):
        queues: dict = {}

        def factory(name: str):
            if name not in queues:
                q = AsyncMock()
                q.send_task = AsyncMock()
                q.close = AsyncMock()
                q.cancel_queued_for_feature = AsyncMock(return_value=cancel_return)
                queues[name] = q
            return queues[name]

        factory.queues = queues  # type: ignore[attr-defined]
        return factory

    def _make_queue_factory_without_cancel(self):
        queues: dict = {}

        def factory(name: str):
            if name not in queues:
                q = AsyncMock()
                q.send_task = AsyncMock()
                q.close = AsyncMock()
                # Intentionally no cancel_queued_for_feature attribute
                if hasattr(q, "cancel_queued_for_feature"):
                    del q.cancel_queued_for_feature
                queues[name] = q
            return queues[name]

        factory.queues = queues  # type: ignore[attr-defined]
        return factory

    async def test_restart_calls_cancel_queued_for_feature_before_enqueue(self):
        initial = self._analyzing_state()
        mgr = _make_state_mgr(initial)
        factory = self._make_queue_factory_with_cancel(cancel_return=1)

        await apply_state_change(
            "feat-x",
            StateChangeResult(target_status=FeatureStatus.analyzing, mode="restart"),
            state_mgr=mgr, queue_factory=factory, config=_config(),
        )

        queue = factory.queues["analyst-queue"]
        queue.cancel_queued_for_feature.assert_awaited_once_with("feat-x")
        queue.send_task.assert_awaited_once()

    async def test_cancel_is_called_before_send(self):
        initial = self._analyzing_state()
        mgr = _make_state_mgr(initial)

        call_order: list[str] = []

        def factory(name: str):
            q = AsyncMock()

            async def cancel(fid):
                call_order.append("cancel")
                return 1

            async def send(task, **kwargs):
                call_order.append("send")

            q.cancel_queued_for_feature = cancel
            q.send_task = send
            q.close = AsyncMock()
            return q

        await apply_state_change(
            "feat-x",
            StateChangeResult(target_status=FeatureStatus.analyzing, mode="restart"),
            state_mgr=mgr, queue_factory=factory, config=_config(),
        )

        assert call_order == ["cancel", "send"]

    async def test_restart_proceeds_normally_when_queue_lacks_cancel_method(self):
        initial = self._analyzing_state()
        mgr = _make_state_mgr(initial)
        factory = self._make_queue_factory_without_cancel()

        # Should not raise even when cancel_queued_for_feature is absent
        await apply_state_change(
            "feat-x",
            StateChangeResult(target_status=FeatureStatus.analyzing, mode="restart"),
            state_mgr=mgr, queue_factory=factory, config=_config(),
        )

        queue = factory.queues["analyst-queue"]
        queue.send_task.assert_awaited_once()

    async def test_rollback_does_not_call_cancel(self):
        """cancel_queued_for_feature is only called on restart, not rollback."""
        initial = FeatureState(feature_id="feat-x", status=FeatureStatus.architecting)
        mgr = _make_state_mgr(initial)
        factory = self._make_queue_factory_with_cancel()

        await apply_state_change(
            "feat-x",
            StateChangeResult(target_status=FeatureStatus.analyzing, mode="rollback"),
            state_mgr=mgr, queue_factory=factory, config=_config(),
        )

        queue = factory.queues["analyst-queue"]
        queue.cancel_queued_for_feature.assert_not_awaited()
