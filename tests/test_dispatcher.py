"""Unit tests for dispatcher — state transitions, parsing, serial dispatch."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from agentharness.config import Config
from agentharness.dispatcher import (
    _dispatch_review_result,
    _dispatch_serial_next,
    _parse_review_result,
    _task_name_from_id,
)
from agentharness.models import (
    FeatureState,
    FeatureStatus,
    TaskEntry,
    TaskMessage,
    TaskStatus,
)



class TestParseReviewResult:
    def test_all_pass_returns_empty(self):
        review = (
            "## Review Result: PASS\n\n"
            "### task: auth-module\n**Status:** PASS\n\n"
            "### task: user-api\n**Status:** PASS\n"
        )
        failed = _parse_review_result(review)
        assert failed == {}

    def test_identifies_failing_tasks(self):
        review = (
            "## Review Result: REVISION_NEEDED\n\n"
            "### task: auth-module\n"
            "**Status:** REVISION_NEEDED\n"
            "**Issues:**\n- Missing rate limiting\n- No tests\n\n"
            "### task: user-api\n**Status:** PASS\n"
        )
        failed = _parse_review_result(review)
        assert "auth-module" in failed
        assert "user-api" not in failed
        assert "Missing rate limiting" in failed["auth-module"]

    def test_multiple_failing_tasks(self):
        review = (
            "### task: task-one\n**Status:** REVISION_NEEDED\n**Issues:**\n- Issue A\n\n"
            "### task: task-two\n**Status:** REVISION_NEEDED\n**Issues:**\n- Issue B\n"
        )
        failed = _parse_review_result(review)
        assert len(failed) == 2
        assert "task-one" in failed
        assert "task-two" in failed



class TestFeatureStateHelpers:
    def _state_with_tasks(self, statuses: list[str]) -> FeatureState:
        tasks = [
            TaskEntry(
                task_id=f"feat-test-dev-{i}",
                phase="developing",
                status=TaskStatus(s),
            )
            for i, s in enumerate(statuses)
        ]
        state = FeatureState(feature_id="feat-test")
        return state.with_tasks_added(tasks)

    def test_all_tasks_complete_when_all_done(self):
        state = self._state_with_tasks(["completed", "completed"])
        assert state.all_tasks_complete("developing") is True

    def test_not_all_complete_when_one_in_progress(self):
        state = self._state_with_tasks(["completed", "in_progress"])
        assert state.all_tasks_complete("developing") is False

    def test_not_all_complete_when_no_tasks(self):
        state = FeatureState(feature_id="feat-empty")
        assert state.all_tasks_complete("developing") is False

    def test_with_task_update_is_immutable(self):
        state = self._state_with_tasks(["queued"])
        task_id = state.tasks[0].task_id
        updated = state.with_task_update(task_id, status=TaskStatus.completed)
        assert state.tasks[0].status == TaskStatus.queued
        assert updated.tasks[0].status == TaskStatus.completed

    def test_all_tasks_complete_when_one_failed(self):
        state = self._state_with_tasks(["completed", "failed"])
        assert state.all_tasks_complete("developing") is True

    def test_not_all_complete_when_pending_remains(self):
        state = self._state_with_tasks(["completed", "pending"])
        assert state.all_tasks_complete("developing") is False

    def test_next_pending_task_returns_first_pending(self):
        state = self._state_with_tasks(["completed", "pending", "pending"])
        next_task = state.next_pending_task("developing")
        assert next_task is not None
        assert next_task.task_id == "feat-test-dev-1"

    def test_next_pending_task_returns_none_when_none_pending(self):
        state = self._state_with_tasks(["completed", "completed"])
        assert state.next_pending_task("developing") is None

    def test_next_pending_task_ignores_other_phases(self):
        tasks = [
            TaskEntry(task_id="feat-test-review-0", phase="reviewing", status=TaskStatus.pending),
        ]
        state = FeatureState(feature_id="feat-test").with_tasks_added(tasks)
        assert state.next_pending_task("developing") is None


class TestTaskNameFromId:
    def test_simple_task_name(self):
        assert _task_name_from_id("feat-42-dev-auth-module", "feat-42") == "auth-module"

    def test_strips_revision_suffix(self):
        assert _task_name_from_id("feat-42-dev-auth-module-r3", "feat-42") == "auth-module"

    def test_revision_1_stripped(self):
        assert _task_name_from_id("feat-42-dev-foo-r1", "feat-42") == "foo"

    def test_no_revision_suffix(self):
        assert _task_name_from_id("feat-42-dev-user-api", "feat-42") == "user-api"


def _make_dev_task(feature_id: str, task_name: str, revision: int = 1) -> TaskMessage:
    return TaskMessage(
        feature_id=feature_id,
        task_id=f"{feature_id}-dev-{task_name}" + (f"-r{revision}" if revision > 1 else ""),
        input_artifacts=[],
        output_artifact=f"artifacts/{feature_id}/impl/{task_name}.r{revision}.md",
        agent_role="developer",
        context=f"Task: {task_name}",
        revision=revision,
        work_dir=f"implementations/{feature_id}",
    )


def _make_state_with_pending_tasks(feature_id: str, task_names: list[str]) -> FeatureState:
    from agentharness.storage import impl_artifact_path
    entries = [
        TaskEntry(
            task_id=f"{feature_id}-dev-{name}",
            phase="developing",
            status=TaskStatus.pending,
            output_artifact=impl_artifact_path(feature_id, name, 1),
            queued_message=_make_dev_task(feature_id, name).model_dump(),
        )
        for name in task_names
    ]
    return FeatureState(feature_id=feature_id, status=FeatureStatus.developing).with_tasks_added(entries)


def _make_queues() -> dict:
    q = AsyncMock()
    q.send_task = AsyncMock()
    return {"developer-queue": q, "review-queue": q}


def _make_config() -> Config:
    cfg = MagicMock(spec=Config)
    cfg.storage_backend = "azure"
    return cfg


@pytest.mark.asyncio
class TestDispatchSerialNext:
    async def test_enqueues_per_task_review(self):
        state = _make_state_with_pending_tasks("feat-1", ["auth", "api"])
        state = state.with_task_update("feat-1-dev-auth", status=TaskStatus.completed)
        dev_task = _make_dev_task("feat-1", "auth")
        queues = _make_queues()

        result = await _dispatch_serial_next(state, dev_task, "## Status\nDONE\n", _make_config(), queues)

        assert result.status == FeatureStatus.reviewing
        queues["review-queue"].send_task.assert_awaited_once()
        sent = queues["review-queue"].send_task.call_args[0][0]
        assert "review-auth" in sent.task_id
        assert sent.context == "auth"

    async def test_review_task_includes_impl_artifact(self):
        state = _make_state_with_pending_tasks("feat-1", ["foo"])
        dev_task = _make_dev_task("feat-1", "foo")
        queues = _make_queues()

        await _dispatch_serial_next(state, dev_task, "## Status\nDONE\n", _make_config(), queues)

        sent = queues["review-queue"].send_task.call_args[0][0]
        assert dev_task.output_artifact in sent.input_artifacts

    async def test_blocked_status_marks_feature_failed(self):
        state = _make_state_with_pending_tasks("feat-1", ["auth"])
        dev_task = _make_dev_task("feat-1", "auth")
        queues = _make_queues()

        result = await _dispatch_serial_next(
            state, dev_task, "## Status\nBLOCKED\n\nCannot proceed.", _make_config(), queues
        )

        assert result.status == FeatureStatus.failed
        queues["review-queue"].send_task.assert_not_awaited()

    async def test_needs_context_marks_feature_failed(self):
        state = _make_state_with_pending_tasks("feat-1", ["auth"])
        dev_task = _make_dev_task("feat-1", "auth")
        queues = _make_queues()

        result = await _dispatch_serial_next(
            state, dev_task, "## Status\nNEEDS_CONTEXT\n\nMissing info.", _make_config(), queues
        )

        assert result.status == FeatureStatus.failed
        queues["review-queue"].send_task.assert_not_awaited()

    async def test_missing_status_defaults_to_done(self):
        state = _make_state_with_pending_tasks("feat-1", ["foo"])
        dev_task = _make_dev_task("feat-1", "foo")
        queues = _make_queues()

        result = await _dispatch_serial_next(state, dev_task, "No status header here.", _make_config(), queues)

        assert result.status == FeatureStatus.reviewing


@pytest.mark.asyncio
class TestDispatchReviewResult:
    async def test_pass_enqueues_next_pending_task(self):
        state = _make_state_with_pending_tasks("feat-2", ["task-a", "task-b"])
        state = state.with_task_update("feat-2-dev-task-a", status=TaskStatus.completed)
        review_task = TaskMessage(
            feature_id="feat-2",
            task_id="feat-2-review-task-a-r1",
            input_artifacts=[],
            output_artifact="artifacts/feat-2/review/task-a.r1.md",
            agent_role="reviewer",
            context="task-a",
            revision=1,
        )
        review_output = "### task: task-a\n**Status:** PASS\n"
        queues = _make_queues()

        result = await _dispatch_review_result(state, review_task, review_output, _make_config(), queues)

        assert result.status == FeatureStatus.developing
        queues["developer-queue"].send_task.assert_awaited_once()
        sent = queues["developer-queue"].send_task.call_args[0][0]
        assert "task-b" in sent.task_id

    async def test_pass_with_no_more_tasks_marks_done(self):
        state = _make_state_with_pending_tasks("feat-3", ["only-task"])
        state = state.with_task_update("feat-3-dev-only-task", status=TaskStatus.completed)
        review_task = TaskMessage(
            feature_id="feat-3",
            task_id="feat-3-review-only-task-r1",
            input_artifacts=[],
            output_artifact="artifacts/feat-3/review/only-task.r1.md",
            agent_role="reviewer",
            context="only-task",
            revision=1,
        )
        review_output = "### task: only-task\n**Status:** PASS\n"
        queues = _make_queues()

        result = await _dispatch_review_result(state, review_task, review_output, _make_config(), queues)

        assert result.status == FeatureStatus.done
        queues["developer-queue"].send_task.assert_not_awaited()

    async def test_revision_needed_enqueues_revision_task(self):
        state = _make_state_with_pending_tasks("feat-4", ["auth"])
        review_task = TaskMessage(
            feature_id="feat-4",
            task_id="feat-4-review-auth-r1",
            input_artifacts=[],
            output_artifact="artifacts/feat-4/review/auth.r1.md",
            agent_role="reviewer",
            context="auth",
            revision=1,
        )
        review_output = (
            "### task: auth\n**Status:** REVISION_NEEDED\n**Issues:**\n- Missing error handling\n"
        )
        queues = _make_queues()

        result = await _dispatch_review_result(state, review_task, review_output, _make_config(), queues)

        assert result.status == FeatureStatus.dev_revision
        queues["developer-queue"].send_task.assert_awaited_once()
        sent = queues["developer-queue"].send_task.call_args[0][0]
        assert sent.revision == 2
        assert "Missing error handling" in sent.review_feedback

    async def test_revision_exceeding_max_marks_failed(self):
        from agentharness.models import PipelineConfig
        state = _make_state_with_pending_tasks("feat-5", ["auth"])
        state = state.model_copy(update={"config": PipelineConfig(max_revisions=3)})
        review_task = TaskMessage(
            feature_id="feat-5",
            task_id="feat-5-review-auth-r3",
            input_artifacts=[],
            output_artifact="artifacts/feat-5/review/auth.r3.md",
            agent_role="reviewer",
            context="auth",
            revision=3,
        )
        review_output = "### task: auth\n**Status:** REVISION_NEEDED\n**Issues:**\n- Still broken\n"
        queues = _make_queues()

        result = await _dispatch_review_result(state, review_task, review_output, _make_config(), queues)

        assert result.status == FeatureStatus.failed
        queues["developer-queue"].send_task.assert_not_awaited()


class TestStateToQueue:
    def test_mapping_covers_every_feature_status(self):
        from agentharness.dispatcher import STATE_TO_QUEUE
        from agentharness.models import FeatureStatus
        for status in FeatureStatus:
            assert status in STATE_TO_QUEUE, f"Missing mapping for {status}"

    def test_active_phases_have_queues(self):
        from agentharness.dispatcher import STATE_TO_QUEUE
        from agentharness.models import FeatureStatus
        assert STATE_TO_QUEUE[FeatureStatus.analyzing] == "analyst-queue"
        assert STATE_TO_QUEUE[FeatureStatus.architecting] == "architect-queue"
        assert STATE_TO_QUEUE[FeatureStatus.designing] == "designer-queue"
        assert STATE_TO_QUEUE[FeatureStatus.planning] == "planner-queue"
        assert STATE_TO_QUEUE[FeatureStatus.developing] == "developer-queue"
        assert STATE_TO_QUEUE[FeatureStatus.dev_revision] == "developer-queue"
        assert STATE_TO_QUEUE[FeatureStatus.reviewing] == "review-queue"

    def test_terminal_and_brainstorm_states_have_no_queue(self):
        from agentharness.dispatcher import STATE_TO_QUEUE
        from agentharness.models import FeatureStatus
        assert STATE_TO_QUEUE[FeatureStatus.brainstorming] is None
        assert STATE_TO_QUEUE[FeatureStatus.brainstormed] is None
        assert STATE_TO_QUEUE[FeatureStatus.done] is None
        assert STATE_TO_QUEUE[FeatureStatus.failed] is None

    def test_queue_for_state_returns_mapped_queue(self):
        from agentharness.dispatcher import queue_for_state
        from agentharness.models import FeatureStatus
        assert queue_for_state(FeatureStatus.developing) == "developer-queue"

    def test_queue_for_state_returns_none_for_terminal(self):
        from agentharness.dispatcher import queue_for_state
        from agentharness.models import FeatureStatus
        assert queue_for_state(FeatureStatus.failed) is None
        assert queue_for_state(FeatureStatus.done) is None


class TestBuildPhaseTask:
    def _config(self):
        # Mimic the queue→agent path mapping in .pipeline/config.json
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

    def test_phase_agent_task_for_analyzing(self):
        from agentharness.dispatcher import build_phase_task
        state = FeatureState(feature_id="feat-x", status=FeatureStatus.analyzing)
        task = build_phase_task(state, FeatureStatus.analyzing, self._config())
        assert task.feature_id == "feat-x"
        assert task.task_id == "feat-x-analyzing-1"
        assert task.agent_role == "analyst"
        assert task.input_artifacts == ["artifacts/feat-x/brief.md"]
        assert task.output_artifact == "artifacts/feat-x/spec.r1.md"

    def test_phase_agent_task_for_planning(self):
        from agentharness.dispatcher import build_phase_task
        state = FeatureState(feature_id="feat-x", status=FeatureStatus.planning)
        task = build_phase_task(state, FeatureStatus.planning, self._config())
        assert task.agent_role == "planner"
        assert task.task_id == "feat-x-planning-1"
        assert task.output_artifact == "artifacts/feat-x/task-plan.r1.md"

    def test_developer_target_uses_in_progress_queued_message(self):
        from agentharness.dispatcher import build_phase_task
        existing = TaskMessage(
            feature_id="feat-x",
            task_id="feat-x-dev-auth-r1",
            input_artifacts=["artifacts/feat-x/task-context/auth.md"],
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
        state = FeatureState(
            feature_id="feat-x", status=FeatureStatus.developing
        ).with_tasks_added([entry])
        task = build_phase_task(state, FeatureStatus.developing, self._config())
        assert task.task_id == existing.task_id
        assert task.agent_role == "developer"

    def test_developer_target_falls_back_to_pending_task(self):
        from agentharness.dispatcher import build_phase_task
        pending_msg = TaskMessage(
            feature_id="feat-x",
            task_id="feat-x-dev-api-r1",
            input_artifacts=[],
            output_artifact="artifacts/feat-x/impl/api.r1.md",
            agent_role="developer",
            context="api",
        )
        entry = TaskEntry(
            task_id=pending_msg.task_id,
            phase="developing",
            status=TaskStatus.pending,
            queued_message=pending_msg.model_dump(),
        )
        state = FeatureState(
            feature_id="feat-x", status=FeatureStatus.developing
        ).with_tasks_added([entry])
        task = build_phase_task(state, FeatureStatus.developing, self._config())
        assert task.task_id == pending_msg.task_id

    def test_developer_target_raises_when_no_task_available(self):
        from agentharness.dispatcher import build_phase_task
        state = FeatureState(feature_id="feat-x", status=FeatureStatus.developing)
        with pytest.raises(ValueError, match="No developer task"):
            build_phase_task(state, FeatureStatus.developing, self._config())

    def test_reviewing_target_uses_in_progress_dev_task(self):
        from agentharness.dispatcher import build_phase_task
        dev_msg = TaskMessage(
            feature_id="feat-x",
            task_id="feat-x-dev-auth-r1",
            input_artifacts=["artifacts/feat-x/task-context/auth.md"],
            output_artifact="artifacts/feat-x/impl/auth.r1.md",
            agent_role="developer",
            context="auth",
        )
        entry = TaskEntry(
            task_id=dev_msg.task_id,
            phase="developing",
            status=TaskStatus.in_progress,
            queued_message=dev_msg.model_dump(),
        )
        state = FeatureState(
            feature_id="feat-x", status=FeatureStatus.reviewing
        ).with_tasks_added([entry])
        task = build_phase_task(state, FeatureStatus.reviewing, self._config())
        assert task.agent_role == "reviewer"
        assert "review" in task.task_id
        assert dev_msg.output_artifact in task.input_artifacts

    def test_terminal_status_raises(self):
        from agentharness.dispatcher import build_phase_task
        state = FeatureState(feature_id="feat-x", status=FeatureStatus.failed)
        with pytest.raises(ValueError, match="no enqueueable task"):
            build_phase_task(state, FeatureStatus.failed, self._config())
