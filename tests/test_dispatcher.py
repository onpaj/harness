"""Unit tests for dispatcher — state transitions, parsing, serial dispatch."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agentharness.config import Config
from agentharness.dispatcher import (
    dispatch_after_completion,
    _dispatch_review_result,
    _dispatch_serial_next,
    _open_feature_pr,
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



class TestParseAnalystStatus:
    def test_complete(self):
        from agentharness.dispatcher import _parse_analyst_status
        assert _parse_analyst_status("# Spec\n\n## Status: COMPLETE\n") == "COMPLETE"

    def test_has_questions(self):
        from agentharness.dispatcher import _parse_analyst_status
        assert _parse_analyst_status("# Spec\n\n## Status: HAS_QUESTIONS\n") == "HAS_QUESTIONS"

    def test_missing_status_defaults_to_complete(self):
        from agentharness.dispatcher import _parse_analyst_status
        assert _parse_analyst_status("# Spec body without status line.") == "COMPLETE"

    def test_empty_string_defaults_to_complete(self):
        from agentharness.dispatcher import _parse_analyst_status
        assert _parse_analyst_status("") == "COMPLETE"

    def test_lowercase_value_defaults_to_complete(self):
        from agentharness.dispatcher import _parse_analyst_status
        assert _parse_analyst_status("## Status: has_questions\n") == "COMPLETE"

    def test_mixed_case_value_defaults_to_complete(self):
        from agentharness.dispatcher import _parse_analyst_status
        assert _parse_analyst_status("## Status: Has_Questions\n") == "COMPLETE"

    def test_garbage_value_defaults_to_complete(self):
        from agentharness.dispatcher import _parse_analyst_status
        assert _parse_analyst_status("## Status: WAT\n") == "COMPLETE"

    def test_status_at_end_of_file_no_trailing_newline(self):
        from agentharness.dispatcher import _parse_analyst_status
        assert _parse_analyst_status("body\n## Status: HAS_QUESTIONS") == "HAS_QUESTIONS"

    def test_extra_whitespace_around_value(self):
        from agentharness.dispatcher import _parse_analyst_status
        assert _parse_analyst_status("## Status:   HAS_QUESTIONS  \n") == "HAS_QUESTIONS"


class TestParseArchitectSkipDesign:
    def test_true_skips_design(self):
        from agentharness.dispatcher import _parse_architect_skip_design
        assert _parse_architect_skip_design("# Review\n\n## Skip Design: true\n") is True

    def test_false_does_not_skip(self):
        from agentharness.dispatcher import _parse_architect_skip_design
        assert _parse_architect_skip_design("# Review\n\n## Skip Design: false\n") is False

    def test_missing_defaults_to_false(self):
        from agentharness.dispatcher import _parse_architect_skip_design
        assert _parse_architect_skip_design("# Review body without signal") is False

    def test_case_insensitive(self):
        from agentharness.dispatcher import _parse_architect_skip_design
        assert _parse_architect_skip_design("## skip design: TRUE\n") is True

    def test_extra_whitespace_ignored(self):
        from agentharness.dispatcher import _parse_architect_skip_design
        assert _parse_architect_skip_design("## Skip Design:   true  \n") is True


@pytest.mark.asyncio
class TestDispatchAfterCompletionArchitecting:
    def _state(self) -> FeatureState:
        return FeatureState(feature_id="feat-arch", status=FeatureStatus.architecting)

    def _task(self) -> TaskMessage:
        return TaskMessage(
            feature_id="feat-arch",
            task_id="feat-arch-architecting-1",
            input_artifacts=["artifacts/feat-arch/spec.r1.md"],
            output_artifact="artifacts/feat-arch/arch-review.r1.md",
            agent_role="architect",
        )

    def _queues(self) -> dict:
        return {
            "designer-queue": AsyncMock(send_task=AsyncMock()),
            "planner-queue": AsyncMock(send_task=AsyncMock()),
        }

    def _config(self) -> MagicMock:
        from pathlib import Path
        cfg = MagicMock()
        cfg.agent_path_for_queue.side_effect = lambda q: {
            "designer-queue": Path(".agents/designer.md"),
            "planner-queue": Path(".agents/planner.md"),
        }[q]
        return cfg

    async def test_without_skip_signal_transitions_to_designing(self):
        queues = self._queues()
        result = await dispatch_after_completion(
            self._state(), self._task(), "# Arch Review\n\n## Skip Design: false\n",
            self._config(), queues,
        )
        assert result.status == FeatureStatus.designing
        queues["designer-queue"].send_task.assert_awaited_once()
        queues["planner-queue"].send_task.assert_not_awaited()

    async def test_with_skip_signal_jumps_to_planning(self):
        queues = self._queues()
        result = await dispatch_after_completion(
            self._state(), self._task(), "# Arch Review\n\n## Skip Design: true\n",
            self._config(), queues,
        )
        assert result.status == FeatureStatus.planning
        queues["planner-queue"].send_task.assert_awaited_once()
        queues["designer-queue"].send_task.assert_not_awaited()

    async def test_missing_skip_signal_defaults_to_designing(self):
        queues = self._queues()
        result = await dispatch_after_completion(
            self._state(), self._task(), "# Arch Review with no skip signal",
            self._config(), queues,
        )
        assert result.status == FeatureStatus.designing
        queues["designer-queue"].send_task.assert_awaited_once()


class TestLatestSpecRevision:
    def test_initial_state_returns_one(self):
        from agentharness.dispatcher import _latest_spec_revision
        from agentharness.models import PipelineConfig
        state = FeatureState(
            feature_id="feat-x",
            config=PipelineConfig(current_analyst_iteration=0),
        )
        assert _latest_spec_revision(state) == 1

    def test_after_one_increment_returns_two(self):
        from agentharness.dispatcher import _latest_spec_revision
        from agentharness.models import PipelineConfig
        state = FeatureState(
            feature_id="feat-x",
            config=PipelineConfig(current_analyst_iteration=1),
        )
        assert _latest_spec_revision(state) == 2

    def test_after_two_increments_returns_three(self):
        from agentharness.dispatcher import _latest_spec_revision
        from agentharness.models import PipelineConfig
        state = FeatureState(
            feature_id="feat-x",
            config=PipelineConfig(current_analyst_iteration=2),
        )
        assert _latest_spec_revision(state) == 3


class TestArtifactsForPhase:
    def _state(self, current: int = 0, status: FeatureStatus = FeatureStatus.analyzing) -> FeatureState:
        from agentharness.models import PipelineConfig
        return FeatureState(
            feature_id="feat-a",
            status=status,
            config=PipelineConfig(current_analyst_iteration=current),
        )

    def test_analyzing_initial_returns_brief_only(self):
        from agentharness.dispatcher import _artifacts_for_phase
        state = self._state(current=0)
        artifacts = _artifacts_for_phase(state, "analyzing")
        assert artifacts == ["artifacts/feat-a/brief.md"]

    def test_analyzing_after_one_loop_includes_spec_and_answers_r1(self):
        from agentharness.dispatcher import _artifacts_for_phase
        state = self._state(current=1)
        artifacts = _artifacts_for_phase(state, "analyzing")
        assert artifacts == [
            "artifacts/feat-a/brief.md",
            "artifacts/feat-a/spec.r1.md",
            "artifacts/feat-a/answers.r1.md",
        ]

    def test_analyzing_after_two_loops_includes_specs_and_answers_r1_r2(self):
        from agentharness.dispatcher import _artifacts_for_phase
        state = self._state(current=2)
        artifacts = _artifacts_for_phase(state, "analyzing")
        assert artifacts == [
            "artifacts/feat-a/brief.md",
            "artifacts/feat-a/spec.r1.md",
            "artifacts/feat-a/spec.r2.md",
            "artifacts/feat-a/answers.r1.md",
            "artifacts/feat-a/answers.r2.md",
        ]

    def test_questioning_first_iteration_includes_spec_r1_no_answers(self):
        from agentharness.dispatcher import _artifacts_for_phase
        state = self._state(current=0, status=FeatureStatus.questioning)
        artifacts = _artifacts_for_phase(state, "questioning")
        assert artifacts == [
            "artifacts/feat-a/brief.md",
            "artifacts/feat-a/spec.r1.md",
        ]

    def test_questioning_second_iteration_includes_spec_r2_and_answers_r1(self):
        from agentharness.dispatcher import _artifacts_for_phase
        state = self._state(current=1, status=FeatureStatus.questioning)
        artifacts = _artifacts_for_phase(state, "questioning")
        assert artifacts == [
            "artifacts/feat-a/brief.md",
            "artifacts/feat-a/spec.r2.md",
            "artifacts/feat-a/answers.r1.md",
        ]

    def test_architecting_uses_latest_spec(self):
        from agentharness.dispatcher import _artifacts_for_phase
        state = self._state(current=2)
        artifacts = _artifacts_for_phase(state, "architecting")
        assert "artifacts/feat-a/spec.r3.md" in artifacts
        assert "artifacts/feat-a/brief.md" in artifacts

    def test_designing_uses_latest_spec(self):
        from agentharness.dispatcher import _artifacts_for_phase
        state = self._state(current=1)
        artifacts = _artifacts_for_phase(state, "designing")
        assert "artifacts/feat-a/spec.r2.md" in artifacts
        assert "artifacts/feat-a/arch-review.r1.md" in artifacts

    def test_planning_uses_latest_spec(self):
        from agentharness.dispatcher import _artifacts_for_phase
        state = self._state(current=2)
        artifacts = _artifacts_for_phase(state, "planning")
        assert "artifacts/feat-a/spec.r3.md" in artifacts
        assert "artifacts/feat-a/design.r1.md" in artifacts

    def test_unknown_phase_returns_empty_list(self):
        from agentharness.dispatcher import _artifacts_for_phase
        state = self._state(current=0)
        assert _artifacts_for_phase(state, "nonexistent") == []


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


def _make_github_config() -> Config:
    cfg = MagicMock(spec=Config)
    cfg.storage_backend = "github"
    return cfg


def _mock_github_client(
    pr_number: int = 42,
    pr_url: str = "https://github.com/org/repo/pull/42",
    raise_exc: Exception | None = None,
):
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get_default_branch = AsyncMock(return_value="main")
    mock_client.close = AsyncMock()
    mock_client.create_comment = AsyncMock()
    if raise_exc:
        mock_client.create_pull_request = AsyncMock(side_effect=raise_exc)
    else:
        mock_client.create_pull_request = AsyncMock(
            return_value={"number": pr_number, "html_url": pr_url}
        )
    mock_cls = MagicMock(return_value=mock_client)
    mock_cls.from_config = MagicMock(return_value=mock_client)
    return patch("agentharness.github_client.GitHubClient", mock_cls)


@pytest.mark.asyncio
class TestDispatchSerialNext:
    async def test_done_transitions_to_done_directly(self):
        """Successful dev completion goes straight to done — no outer review queue."""
        state = _make_state_with_pending_tasks("feat-1", ["auth"])
        dev_task = _make_dev_task("feat-1", "auth")
        queues = _make_queues()
        cfg = _make_config()
        cfg.storage_backend = "azure"  # non-github, so _open_feature_pr is a no-op

        result = await _dispatch_serial_next(state, dev_task, "## Status\nDONE\n", cfg, queues)

        assert result.status == FeatureStatus.done
        queues["review-queue"].send_task.assert_not_awaited()

    async def test_done_with_concerns_transitions_to_done(self):
        state = _make_state_with_pending_tasks("feat-1", ["auth"])
        dev_task = _make_dev_task("feat-1", "auth")
        queues = _make_queues()

        result = await _dispatch_serial_next(
            state, dev_task, "## Status\nDONE_WITH_CONCERNS\n", _make_config(), queues
        )

        assert result.status == FeatureStatus.done

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

        assert result.status == FeatureStatus.done


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
        from unittest.mock import AsyncMock
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
        state_mgr = AsyncMock()
        state_mgr.open_review = AsyncMock(return_value=None)

        result = await _dispatch_review_result(state, review_task, review_output, _make_config(), queues, state_mgr)

        assert result.status == FeatureStatus.done
        queues["developer-queue"].send_task.assert_not_awaited()
        state_mgr.open_review.assert_awaited_once_with("feat-3", pr_title=None, pr_summary=None)

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

    async def test_pass_with_no_more_tasks_calls_open_review(self):
        """When all tasks pass review, open_review is called on the state_mgr."""
        state = _make_state_with_pending_tasks("feat-3", ["only-task"])
        state = state.model_copy(update={"branch_name": "feat-3-99", "state_issue_number": 99})
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
        cfg = _make_github_config()
        state_mgr = AsyncMock()

        result = await _dispatch_review_result(state, review_task, review_output, cfg, queues, state_mgr)

        assert result.status == FeatureStatus.done
        state_mgr.open_review.assert_awaited_once_with("feat-3", pr_title=None, pr_summary=None)

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
            "product-queue":   Path(".agents/product.md"),
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
        assert task.task_id == "feat-x-analyzing-r1"
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


def test_linear_transitions_no_longer_includes_analyzing():
    from agentharness.dispatcher import _LINEAR_TRANSITIONS
    assert "analyzing" not in _LINEAR_TRANSITIONS


def _make_questioning_queues() -> dict:
    q = AsyncMock()
    q.send_task = AsyncMock()
    return {
        "product-queue": q,
        "architect-queue": AsyncMock(send_task=AsyncMock()),
        "developer-queue": AsyncMock(send_task=AsyncMock()),
        "review-queue": AsyncMock(send_task=AsyncMock()),
        "analyst-queue": AsyncMock(send_task=AsyncMock()),
    }


def _make_questioning_config() -> MagicMock:
    from pathlib import Path
    cfg = MagicMock()
    cfg.agent_path_for_queue.side_effect = lambda q: {
        "product-queue": Path(".agents/product.md"),
        "analyst-queue": Path(".agents/analyst.md"),
        "architect-queue": Path(".agents/architect.md"),
        "designer-queue": Path(".agents/designer.md"),
        "planner-queue": Path(".agents/planner.md"),
    }[q]
    return cfg


@pytest.mark.asyncio
class TestDispatchQuestioning:
    async def test_enqueues_product_task_first_iteration(self):
        from agentharness.dispatcher import _dispatch_questioning
        from agentharness.models import PipelineConfig
        state = FeatureState(
            feature_id="feat-q",
            status=FeatureStatus.analyzing,
            config=PipelineConfig(current_analyst_iteration=0, max_analyst_iterations=2),
            state_issue_number=99,
        )
        queues = _make_questioning_queues()
        result = await _dispatch_questioning(state, _make_questioning_config(), queues)
        assert result.status == FeatureStatus.questioning
        queues["product-queue"].send_task.assert_awaited_once()
        sent = queues["product-queue"].send_task.call_args[0][0]
        assert sent.task_id == "feat-q-questioning-r1"
        assert sent.agent_role == "product"
        assert sent.output_artifact == "artifacts/feat-q/answers.r1.md"
        assert "artifacts/feat-q/brief.md" in sent.input_artifacts
        assert "artifacts/feat-q/spec.r1.md" in sent.input_artifacts
        assert sent.state_issue_number == 99

    async def test_enqueues_product_task_second_iteration(self):
        from agentharness.dispatcher import _dispatch_questioning
        from agentharness.models import PipelineConfig
        state = FeatureState(
            feature_id="feat-q",
            status=FeatureStatus.analyzing,
            config=PipelineConfig(current_analyst_iteration=1, max_analyst_iterations=2),
        )
        queues = _make_questioning_queues()
        result = await _dispatch_questioning(state, _make_questioning_config(), queues)
        sent = queues["product-queue"].send_task.call_args[0][0]
        assert sent.task_id == "feat-q-questioning-r2"
        assert sent.output_artifact == "artifacts/feat-q/answers.r2.md"
        assert "artifacts/feat-q/spec.r2.md" in sent.input_artifacts
        assert "artifacts/feat-q/answers.r1.md" in sent.input_artifacts
        assert result.status == FeatureStatus.questioning

    async def test_raises_when_product_queue_missing(self):
        from agentharness.dispatcher import _dispatch_questioning
        from agentharness.models import PipelineConfig
        state = FeatureState(feature_id="feat-q", config=PipelineConfig())
        with pytest.raises(RuntimeError, match="product-queue"):
            await _dispatch_questioning(state, _make_questioning_config(), {})


@pytest.mark.asyncio
class TestDispatchAnalystRerun:
    async def test_increments_counter_and_enqueues_analyst(self):
        from agentharness.dispatcher import _dispatch_analyst_rerun
        from agentharness.models import PipelineConfig
        state = FeatureState(
            feature_id="feat-rr",
            status=FeatureStatus.questioning,
            config=PipelineConfig(current_analyst_iteration=0, max_analyst_iterations=2),
            state_issue_number=12,
        )
        queues = _make_questioning_queues()
        result = await _dispatch_analyst_rerun(state, _make_questioning_config(), queues)
        assert result.config.current_analyst_iteration == 1
        assert result.status == FeatureStatus.analyzing
        queues["analyst-queue"].send_task.assert_awaited_once()
        sent = queues["analyst-queue"].send_task.call_args[0][0]
        assert sent.task_id == "feat-rr-analyzing-r2"
        assert sent.output_artifact == "artifacts/feat-rr/spec.r2.md"
        assert sent.agent_role == "analyst"
        assert "artifacts/feat-rr/brief.md" in sent.input_artifacts
        assert "artifacts/feat-rr/spec.r1.md" in sent.input_artifacts
        assert "artifacts/feat-rr/answers.r1.md" in sent.input_artifacts
        assert sent.state_issue_number == 12

    async def test_raises_when_analyst_queue_missing(self):
        from agentharness.dispatcher import _dispatch_analyst_rerun
        from agentharness.models import PipelineConfig
        state = FeatureState(feature_id="feat-rr", config=PipelineConfig())
        with pytest.raises(RuntimeError, match="analyst-queue"):
            await _dispatch_analyst_rerun(state, _make_questioning_config(), {})


@pytest.mark.asyncio
class TestDispatchAfterCompletionAnalyzing:
    def _state(self, current: int = 0, max_iter: int = 2) -> FeatureState:
        from agentharness.models import PipelineConfig
        return FeatureState(
            feature_id="feat-d",
            status=FeatureStatus.analyzing,
            config=PipelineConfig(
                current_analyst_iteration=current,
                max_analyst_iterations=max_iter,
            ),
        )

    def _analyst_task(self) -> TaskMessage:
        return TaskMessage(
            feature_id="feat-d",
            task_id="feat-d-analyzing-r1",
            input_artifacts=["artifacts/feat-d/brief.md"],
            output_artifact="artifacts/feat-d/spec.r1.md",
            agent_role="analyst",
        )

    async def test_complete_status_transitions_to_architecting(self):
        state = self._state()
        queues = _make_questioning_queues()
        result = await dispatch_after_completion(
            state, self._analyst_task(), "spec body\n\n## Status: COMPLETE\n",
            _make_questioning_config(), queues,
        )
        assert result.status == FeatureStatus.architecting
        queues["architect-queue"].send_task.assert_awaited_once()
        queues["product-queue"].send_task.assert_not_awaited()

    async def test_has_questions_under_cap_transitions_to_questioning(self):
        state = self._state(current=0, max_iter=2)
        queues = _make_questioning_queues()
        result = await dispatch_after_completion(
            state, self._analyst_task(), "spec body\n\n## Status: HAS_QUESTIONS\n",
            _make_questioning_config(), queues,
        )
        assert result.status == FeatureStatus.questioning
        queues["product-queue"].send_task.assert_awaited_once()
        queues["architect-queue"].send_task.assert_not_awaited()

    async def test_has_questions_at_cap_transitions_to_architecting(self, caplog):
        import logging
        state = self._state(current=2, max_iter=2)
        queues = _make_questioning_queues()
        with caplog.at_level(logging.WARNING, logger="agentharness.dispatcher"):
            result = await dispatch_after_completion(
                state, self._analyst_task(), "spec body\n\n## Status: HAS_QUESTIONS\n",
                _make_questioning_config(), queues,
            )
        assert result.status == FeatureStatus.architecting
        queues["product-queue"].send_task.assert_not_awaited()
        assert any("max_analyst_iterations cap reached" in r.message for r in caplog.records)

    async def test_cap_zero_disables_loop(self):
        state = self._state(current=0, max_iter=0)
        queues = _make_questioning_queues()
        result = await dispatch_after_completion(
            state, self._analyst_task(), "spec\n\n## Status: HAS_QUESTIONS\n",
            _make_questioning_config(), queues,
        )
        assert result.status == FeatureStatus.architecting
        queues["product-queue"].send_task.assert_not_awaited()

    async def test_questioning_complete_transitions_to_analyzing_with_increment(self):
        from agentharness.models import PipelineConfig
        state = FeatureState(
            feature_id="feat-d",
            status=FeatureStatus.questioning,
            config=PipelineConfig(current_analyst_iteration=0, max_analyst_iterations=2),
        )
        product_task = TaskMessage(
            feature_id="feat-d",
            task_id="feat-d-questioning-r1",
            input_artifacts=[],
            output_artifact="artifacts/feat-d/answers.r1.md",
            agent_role="product",
        )
        queues = _make_questioning_queues()
        result = await dispatch_after_completion(
            state, product_task, "### Question 1\n... answers ...\n",
            _make_questioning_config(), queues,
        )
        assert result.status == FeatureStatus.analyzing
        assert result.config.current_analyst_iteration == 1
        queues["analyst-queue"].send_task.assert_awaited_once()


class TestBuildPhaseTaskQuestioning:
    def test_phase_agent_task_for_questioning(self):
        from agentharness.dispatcher import build_phase_task
        from agentharness.models import PipelineConfig
        cfg = TestBuildPhaseTask()._config()
        state = FeatureState(
            feature_id="feat-q",
            status=FeatureStatus.questioning,
            config=PipelineConfig(current_analyst_iteration=0),
        )
        task = build_phase_task(state, FeatureStatus.questioning, cfg)
        assert task.task_id == "feat-q-questioning-r1"
        assert task.agent_role == "product"
        assert task.output_artifact == "artifacts/feat-q/answers.r1.md"
        assert "artifacts/feat-q/spec.r1.md" in task.input_artifacts

    def test_phase_agent_task_for_analyzing_is_revision_aware(self):
        from agentharness.dispatcher import build_phase_task
        from agentharness.models import PipelineConfig
        cfg = TestBuildPhaseTask()._config()
        state = FeatureState(
            feature_id="feat-x",
            status=FeatureStatus.analyzing,
            config=PipelineConfig(current_analyst_iteration=1),
        )
        task = build_phase_task(state, FeatureStatus.analyzing, cfg)
        assert task.task_id == "feat-x-analyzing-r2"
        assert task.output_artifact == "artifacts/feat-x/spec.r2.md"


@pytest.mark.asyncio
class TestOpenFeaturePr:
    def _done_state(self, issue_number: int = 42) -> FeatureState:
        return FeatureState(
            feature_id="feat-auth",
            status=FeatureStatus.done,
            state_issue_number=issue_number,
        )

    async def test_noop_when_state_mgr_is_none(self):
        """No-op when state_mgr is None (e.g. Azure backend with no reviewer)."""
        state = self._done_state()
        await _open_feature_pr(state, None)  # should not raise

    async def test_delegates_to_state_mgr_open_review(self):
        """Calls state_mgr.open_review with the feature_id."""
        state = self._done_state()
        state_mgr = AsyncMock()
        await _open_feature_pr(state, state_mgr)
        state_mgr.open_review.assert_awaited_once_with("feat-auth", pr_title=None, pr_summary=None)

    async def test_done_via_serial_next_marks_done(self):
        """_dispatch_serial_next transitions state to done and calls open_review."""
        state = _make_state_with_pending_tasks("feat-gh", ["auth"])
        state = state.model_copy(update={"branch_name": "feat-gh-10", "state_issue_number": 10})
        dev_task = _make_dev_task("feat-gh", "auth")
        queues = _make_queues()
        cfg = _make_github_config()
        state_mgr = AsyncMock()

        result = await _dispatch_serial_next(state, dev_task, "## Status\nDONE\n", cfg, queues, state_mgr)

        assert result.status == FeatureStatus.done
        state_mgr.open_review.assert_awaited_once_with("feat-gh", pr_title=None, pr_summary=None)


@pytest.mark.asyncio
class TestOpenFeaturePrWithStore:
    @pytest.mark.asyncio
    async def test_open_feature_pr_passes_title_and_summary_when_store_present(self):
        from agentharness.dispatcher import _open_feature_pr
        state = FeatureState(
            feature_id="feat-x",
            status=FeatureStatus.done,
            tasks=[
                TaskEntry(
                    task_id="t1",
                    phase="developing",
                    status=TaskStatus.completed,
                    output_artifact="artifacts/feat-x/impl/main.r1.md",
                ),
            ],
        )
        state_mgr = AsyncMock()
        state_mgr.open_review = AsyncMock(return_value="https://pr/123")

        class _FakeStoreWithSummary:
            async def download(self, path: str) -> str:
                if "brief" in path:
                    return "# Add PR Summary Design\n"
                if "spec" in path:
                    raise FileNotFoundError(path)
                return "## PR Summary\nDeveloper-authored body.\n## Status\nDONE\n"
            async def upload(self, path, content): pass
            async def exists(self, path): return True
            async def close(self): pass
            def get_work_dir(self): return None
            async def commit_workdir_changes(self, message): return False

        await _open_feature_pr(state, state_mgr, _FakeStoreWithSummary())

        state_mgr.open_review.assert_awaited_once_with(
            "feat-x",
            pr_title="feat: Add PR Summary Design",
            pr_summary="Developer-authored body.",
        )

    @pytest.mark.asyncio
    async def test_open_feature_pr_passes_none_when_store_none(self):
        from agentharness.dispatcher import _open_feature_pr
        state = FeatureState(feature_id="feat-x", status=FeatureStatus.done, tasks=[])
        state_mgr = AsyncMock()
        state_mgr.open_review = AsyncMock(return_value=None)

        await _open_feature_pr(state, state_mgr, None)

        state_mgr.open_review.assert_awaited_once_with(
            "feat-x",
            pr_title=None,
            pr_summary=None,
        )

    @pytest.mark.asyncio
    async def test_open_feature_pr_default_store_is_none(self):
        from agentharness.dispatcher import _open_feature_pr
        state = FeatureState(feature_id="feat-y", status=FeatureStatus.done, tasks=[])
        state_mgr = AsyncMock()
        state_mgr.open_review = AsyncMock(return_value=None)

        await _open_feature_pr(state, state_mgr)  # store omitted

        state_mgr.open_review.assert_awaited_once_with(
            "feat-y",
            pr_title=None,
            pr_summary=None,
        )


class TestExtractBriefTitle:
    def test_returns_h1_heading_text(self):
        from agentharness.dispatcher import _extract_brief_title
        content = "# Add PR Summary Design\n\nSome body text."
        assert _extract_brief_title(content) == "Add PR Summary Design"

    def test_strips_multiple_leading_hashes(self):
        from agentharness.dispatcher import _extract_brief_title
        assert _extract_brief_title("### Deep Heading\nbody") == "Deep Heading"

    def test_strips_surrounding_whitespace(self):
        from agentharness.dispatcher import _extract_brief_title
        assert _extract_brief_title("#   Padded Title   \nbody") == "Padded Title"

    def test_first_heading_wins_when_multiple_present(self):
        from agentharness.dispatcher import _extract_brief_title
        content = "intro line\n\n# First Heading\n\n# Second Heading"
        assert _extract_brief_title(content) == "First Heading"

    def test_falls_back_to_first_non_empty_line_when_no_heading(self):
        from agentharness.dispatcher import _extract_brief_title
        assert _extract_brief_title("\n\n  first real line  \nsecond") == "first real line"

    def test_returns_empty_string_for_empty_input(self):
        from agentharness.dispatcher import _extract_brief_title
        assert _extract_brief_title("") == ""

    def test_returns_empty_string_for_whitespace_only(self):
        from agentharness.dispatcher import _extract_brief_title
        assert _extract_brief_title("   \n\n  \t\n") == ""


class TestExtractSpecTitle:
    def test_strips_specification_prefix(self):
        from agentharness.dispatcher import _extract_spec_title
        content = "# Specification: Consolidate mapper into shared utility\nbody"
        assert _extract_spec_title(content) == "Consolidate mapper into shared utility"

    def test_strips_spec_prefix(self):
        from agentharness.dispatcher import _extract_spec_title
        assert _extract_spec_title("# Spec: Add telemetry\nbody") == "Add telemetry"

    def test_strips_feature_specification_prefix(self):
        from agentharness.dispatcher import _extract_spec_title
        assert _extract_spec_title("# Feature Specification: Auth flow\n") == "Auth flow"

    def test_strips_feature_spec_prefix(self):
        from agentharness.dispatcher import _extract_spec_title
        assert _extract_spec_title("# Feature Spec: Auth flow\n") == "Auth flow"

    def test_case_insensitive_prefix_match(self):
        from agentharness.dispatcher import _extract_spec_title
        assert _extract_spec_title("# SPECIFICATION: Auth flow\n") == "Auth flow"

    def test_returns_heading_without_prefix_unchanged(self):
        from agentharness.dispatcher import _extract_spec_title
        assert _extract_spec_title("# Add payment support\nbody") == "Add payment support"

    def test_returns_empty_for_empty_input(self):
        from agentharness.dispatcher import _extract_spec_title
        assert _extract_spec_title("") == ""


class TestFormatPrTitle:
    def test_wraps_plain_title_with_feat_prefix(self):
        from agentharness.dispatcher import _format_pr_title
        assert _format_pr_title("Telemetry") == "feat: Telemetry"

    def test_preserves_existing_feat_prefix(self):
        from agentharness.dispatcher import _format_pr_title
        assert _format_pr_title("feat: Something") == "feat: Something"

    def test_preserves_feat_with_scope(self):
        from agentharness.dispatcher import _format_pr_title
        assert _format_pr_title("feat(scope): Something") == "feat(scope): Something"

    def test_preserves_fix_prefix(self):
        from agentharness.dispatcher import _format_pr_title
        assert _format_pr_title("fix: broken thing") == "fix: broken thing"

    def test_preserves_breaking_change_marker(self):
        from agentharness.dispatcher import _format_pr_title
        assert _format_pr_title("feat!: breaking change") == "feat!: breaking change"

    def test_returns_empty_string_unchanged(self):
        from agentharness.dispatcher import _format_pr_title
        assert _format_pr_title("") == ""

    def test_case_insensitive_detection(self):
        from agentharness.dispatcher import _format_pr_title
        assert _format_pr_title("FEAT: Something") == "FEAT: Something"


class TestExtractBriefBody:
    def test_returns_content_after_first_heading(self):
        from agentharness.dispatcher import _extract_brief_body
        content = "# Title\n\n## Problem\nSome problem.\n"
        assert _extract_brief_body(content) == "## Problem\nSome problem."

    def test_returns_none_when_no_body(self):
        from agentharness.dispatcher import _extract_brief_body
        assert _extract_brief_body("# Title\n") is None

    def test_returns_none_for_whitespace_only_body(self):
        from agentharness.dispatcher import _extract_brief_body
        assert _extract_brief_body("# Title\n\n   \n") is None

    def test_returns_none_when_no_heading(self):
        from agentharness.dispatcher import _extract_brief_body
        assert _extract_brief_body("plain text\n") is None

    def test_returns_none_for_empty_input(self):
        from agentharness.dispatcher import _extract_brief_body
        assert _extract_brief_body("") is None


class TestExtractPrSummary:
    def test_returns_section_body_until_next_h2(self):
        from agentharness.dispatcher import _extract_pr_summary
        impl = (
            "# Implementation: foo\n"
            "## Notes\n"
            "n/a\n"
            "## PR Summary\n"
            "Implemented X to do Y.\n"
            "\n"
            "### Changes\n"
            "- `file.py` — added foo\n"
            "## Status\n"
            "DONE\n"
        )
        result = _extract_pr_summary(impl)
        assert result is not None
        assert result.startswith("Implemented X to do Y.")
        assert "### Changes" in result
        assert "- `file.py` — added foo" in result
        assert "## Status" not in result
        assert "DONE" not in result

    def test_returns_section_body_until_eof_when_no_following_h2(self):
        from agentharness.dispatcher import _extract_pr_summary
        impl = "## PR Summary\nA standalone summary at end of file.\n"
        assert _extract_pr_summary(impl) == "A standalone summary at end of file."

    def test_returns_none_when_section_absent(self):
        from agentharness.dispatcher import _extract_pr_summary
        impl = "## Notes\nn/a\n## Status\nDONE\n"
        assert _extract_pr_summary(impl) is None

    def test_returns_none_when_body_is_whitespace_only(self):
        from agentharness.dispatcher import _extract_pr_summary
        impl = "## PR Summary\n   \n\n\n## Status\nDONE\n"
        assert _extract_pr_summary(impl) is None

    def test_returns_none_when_body_is_only_empty_changes_heading(self):
        from agentharness.dispatcher import _extract_pr_summary
        impl = "## PR Summary\n### Changes\n## Status\nDONE\n"
        assert _extract_pr_summary(impl) is None

    def test_returns_summary_when_changes_has_at_least_one_item(self):
        from agentharness.dispatcher import _extract_pr_summary
        impl = (
            "## PR Summary\n"
            "### Changes\n"
            "- `file.py` — explanation\n"
            "## Status\nDONE\n"
        )
        result = _extract_pr_summary(impl)
        assert result is not None
        assert "### Changes" in result

    def test_preserves_internal_blank_lines(self):
        from agentharness.dispatcher import _extract_pr_summary
        impl = (
            "## PR Summary\n"
            "Paragraph one.\n"
            "\n"
            "Paragraph two.\n"
            "## Status\nDONE\n"
        )
        result = _extract_pr_summary(impl)
        assert result is not None
        assert "Paragraph one." in result
        assert "Paragraph two." in result

    def test_section_at_top_of_file(self):
        from agentharness.dispatcher import _extract_pr_summary
        impl = "## PR Summary\nFirst-thing summary.\n## Status\nDONE\n"
        assert _extract_pr_summary(impl) == "First-thing summary."

    def test_h3_heading_inside_body_does_not_terminate(self):
        from agentharness.dispatcher import _extract_pr_summary
        impl = (
            "## PR Summary\n"
            "Intro.\n"
            "### Changes\n"
            "- `a.py` — note\n"
            "## Status\nDONE\n"
        )
        result = _extract_pr_summary(impl)
        assert result is not None
        assert "### Changes" in result
        assert "- `a.py` — note" in result

    def test_rstrips_trailing_whitespace(self):
        from agentharness.dispatcher import _extract_pr_summary
        impl = "## PR Summary\nSummary text.\n\n\n   \n## Status\nDONE\n"
        result = _extract_pr_summary(impl)
        assert result is not None
        assert result == "Summary text."

    def test_returns_none_for_empty_input(self):
        from agentharness.dispatcher import _extract_pr_summary
        assert _extract_pr_summary("") is None


class TestLastDeveloperArtifact:
    def _state(self, tasks: list) -> FeatureState:
        return FeatureState(
            feature_id="feat-x",
            status=FeatureStatus.developing,
            tasks=tasks,
        )

    def test_returns_none_when_no_tasks(self):
        from agentharness.dispatcher import _last_developer_artifact
        assert _last_developer_artifact(self._state([])) is None

    def test_returns_none_when_no_completed_developer_task(self):
        from agentharness.dispatcher import _last_developer_artifact
        tasks = [
            TaskEntry(
                task_id="t1",
                phase="developing",
                status=TaskStatus.in_progress,
                output_artifact="artifacts/x/impl/main.r1.md",
            ),
        ]
        assert _last_developer_artifact(self._state(tasks)) is None

    def test_returns_none_when_completed_task_has_no_artifact(self):
        from agentharness.dispatcher import _last_developer_artifact
        tasks = [
            TaskEntry(
                task_id="t1",
                phase="developing",
                status=TaskStatus.completed,
                output_artifact=None,
            ),
        ]
        assert _last_developer_artifact(self._state(tasks)) is None

    def test_returns_artifact_for_single_completed_developer_task(self):
        from agentharness.dispatcher import _last_developer_artifact
        tasks = [
            TaskEntry(
                task_id="t1",
                phase="developing",
                status=TaskStatus.completed,
                output_artifact="artifacts/x/impl/main.r1.md",
            ),
        ]
        assert _last_developer_artifact(self._state(tasks)) == "artifacts/x/impl/main.r1.md"

    def test_returns_artifact_of_last_matching_task(self):
        from agentharness.dispatcher import _last_developer_artifact
        tasks = [
            TaskEntry(
                task_id="t1",
                phase="developing",
                status=TaskStatus.completed,
                output_artifact="artifacts/x/impl/a.r1.md",
            ),
            TaskEntry(
                task_id="t2",
                phase="developing",
                status=TaskStatus.completed,
                output_artifact="artifacts/x/impl/b.r1.md",
            ),
        ]
        assert _last_developer_artifact(self._state(tasks)) == "artifacts/x/impl/b.r1.md"

    def test_skips_non_developer_phases(self):
        from agentharness.dispatcher import _last_developer_artifact
        tasks = [
            TaskEntry(
                task_id="d1",
                phase="developing",
                status=TaskStatus.completed,
                output_artifact="artifacts/x/impl/main.r1.md",
            ),
            TaskEntry(
                task_id="r1",
                phase="reviewing",
                status=TaskStatus.completed,
                output_artifact="artifacts/x/review/main.r1.md",
            ),
        ]
        assert _last_developer_artifact(self._state(tasks)) == "artifacts/x/impl/main.r1.md"

    def test_returns_revision_artifact_when_multiple_revisions(self):
        from agentharness.dispatcher import _last_developer_artifact
        tasks = [
            TaskEntry(
                task_id="d1",
                phase="developing",
                status=TaskStatus.completed,
                output_artifact="artifacts/x/impl/main.r1.md",
            ),
            TaskEntry(
                task_id="d1-rev",
                phase="developing",
                status=TaskStatus.completed,
                revision=2,
                output_artifact="artifacts/x/impl/main.r2.md",
            ),
        ]
        assert _last_developer_artifact(self._state(tasks)) == "artifacts/x/impl/main.r2.md"


@pytest.mark.asyncio
class TestStaleTaskGuard:
    """dispatch_after_completion drops tasks whose agent_role doesn't match the current phase."""

    def _planning_state(self) -> FeatureState:
        return FeatureState(feature_id="feat-x", status=FeatureStatus.planning)

    def _analyzing_state(self) -> FeatureState:
        return FeatureState(feature_id="feat-x", status=FeatureStatus.analyzing)

    def _developing_state(self) -> FeatureState:
        entries = [
            TaskEntry(
                task_id="feat-x-dev-main",
                phase="developing",
                status=TaskStatus.in_progress,
                queued_message=TaskMessage(
                    feature_id="feat-x",
                    task_id="feat-x-dev-main",
                    input_artifacts=[],
                    output_artifact="artifacts/feat-x/impl/main.r1.md",
                    agent_role="developer",
                ).model_dump(),
            )
        ]
        return FeatureState(feature_id="feat-x", status=FeatureStatus.developing).with_tasks_added(entries)

    def _stale_analyst_task(self) -> TaskMessage:
        return TaskMessage(
            feature_id="feat-x",
            task_id="feat-x-analyst",
            input_artifacts=["artifacts/feat-x/brief.md"],
            output_artifact="artifacts/feat-x/spec.r1.md",
            agent_role="analyst",
        )

    def _planner_task(self) -> TaskMessage:
        return TaskMessage(
            feature_id="feat-x",
            task_id="feat-x-planning-1",
            input_artifacts=[],
            output_artifact="artifacts/feat-x/task-plan.r1.md",
            agent_role="planner",
        )

    def _analyst_task(self) -> TaskMessage:
        return TaskMessage(
            feature_id="feat-x",
            task_id="feat-x-analyzing-r1",
            input_artifacts=["artifacts/feat-x/brief.md"],
            output_artifact="artifacts/feat-x/spec.r1.md",
            agent_role="analyst",
        )

    def _queues_with_dev(self) -> dict:
        return {"developer-queue": AsyncMock(send_task=AsyncMock())}

    def _queues_with_architect(self) -> dict:
        from pathlib import Path
        cfg = MagicMock()
        cfg.agent_path_for_queue.side_effect = lambda q: {
            "architect-queue": Path(".agents/architect.md"),
            "product-queue": Path(".agents/product.md"),
        }[q]
        return {"architect-queue": AsyncMock(send_task=AsyncMock()), "product-queue": AsyncMock(send_task=AsyncMock())}

    def _config_for_planning(self) -> MagicMock:
        from pathlib import Path
        cfg = MagicMock()
        cfg.agent_path_for_queue.side_effect = lambda q: {
            "developer-queue": Path(".agents/developer.md"),
        }[q]
        return cfg

    def _config_for_analyzing(self) -> MagicMock:
        from pathlib import Path
        cfg = MagicMock()
        cfg.agent_path_for_queue.side_effect = lambda q: {
            "architect-queue": Path(".agents/architect.md"),
            "product-queue": Path(".agents/product.md"),
        }[q]
        return cfg

    async def test_stale_analyst_completing_during_planning_returns_none(self):
        queues = self._queues_with_dev()
        result = await dispatch_after_completion(
            self._planning_state(), self._stale_analyst_task(), "analyst output",
            self._config_for_planning(), queues,
        )
        assert result is None
        queues["developer-queue"].send_task.assert_not_awaited()

    async def test_stale_analyst_completing_during_developing_returns_none(self):
        queues = self._queues_with_dev()
        result = await dispatch_after_completion(
            self._developing_state(), self._stale_analyst_task(), "analyst output",
            self._config_for_planning(), queues,
        )
        assert result is None
        queues["developer-queue"].send_task.assert_not_awaited()

    async def test_stale_task_drop_is_logged_as_warning(self, caplog):
        import logging
        queues = self._queues_with_dev()
        with caplog.at_level(logging.WARNING, logger="agentharness.dispatcher"):
            await dispatch_after_completion(
                self._planning_state(), self._stale_analyst_task(), "analyst output",
                self._config_for_planning(), queues,
            )
        assert any("stale" in r.message.lower() or "dropping" in r.message.lower() for r in caplog.records)

    async def test_planner_completing_during_planning_proceeds_normally(self):
        queues = self._queues_with_dev()
        result = await dispatch_after_completion(
            self._planning_state(), self._planner_task(), "planner output",
            self._config_for_planning(), queues,
        )
        assert result is not None
        assert result.status == FeatureStatus.developing

    async def test_analyst_completing_during_analyzing_proceeds_normally(self):
        from pathlib import Path
        cfg = MagicMock()
        cfg.agent_path_for_queue.side_effect = lambda q: Path(f".agents/{q.replace('-queue', '')}.md")
        queues = {
            "architect-queue": AsyncMock(send_task=AsyncMock()),
            "product-queue": AsyncMock(send_task=AsyncMock()),
        }
        result = await dispatch_after_completion(
            self._analyzing_state(), self._analyst_task(), "## Status: COMPLETE\n",
            cfg, queues,
        )
        assert result is not None
        assert result.status == FeatureStatus.architecting


class _FakeStore:
    """Minimal in-memory ArtifactStorage for unit tests."""

    def __init__(self, files: dict | None = None, fail_paths: set | None = None):
        self._files = files or {}
        self._fail = fail_paths or set()

    async def download(self, path: str) -> str:
        if path in self._fail:
            raise RuntimeError(f"simulated download failure for {path}")
        try:
            return self._files[path]
        except KeyError as exc:
            raise FileNotFoundError(path) from exc

    async def upload(self, path: str, content): pass
    async def exists(self, path: str) -> bool: return path in self._files
    async def close(self) -> None: pass
    def get_work_dir(self): return None
    async def commit_workdir_changes(self, message: str) -> bool: return False


class TestBuildPrContent:
    def _state_with_dev_task(
        self,
        feature_id: str = "feat-x",
        impl_path: str = "artifacts/feat-x/impl/main.r1.md",
    ) -> FeatureState:
        return FeatureState(
            feature_id=feature_id,
            status=FeatureStatus.done,
            tasks=[
                TaskEntry(
                    task_id="t1",
                    phase="developing",
                    status=TaskStatus.completed,
                    output_artifact=impl_path,
                ),
            ],
        )

    @pytest.mark.asyncio
    async def test_returns_none_none_when_store_is_none(self):
        from agentharness.dispatcher import _build_pr_content
        state = self._state_with_dev_task()
        assert await _build_pr_content(state, None) == (None, None)

    @pytest.mark.asyncio
    async def test_returns_title_and_summary_when_both_artifacts_present(self):
        from agentharness.dispatcher import _build_pr_content
        state = self._state_with_dev_task()
        store = _FakeStore({
            "artifacts/feat-x/brief.md": "# Add PR Summary Design\n\nbody.",
            "artifacts/feat-x/impl/main.r1.md": (
                "## Notes\nn/a\n"
                "## PR Summary\nImplemented PR summary support.\n\n"
                "### Changes\n- `dispatcher.py` — added helpers\n"
                "## Status\nDONE\n"
            ),
        })
        title, summary = await _build_pr_content(state, store)
        assert title == "feat: Add PR Summary Design"
        assert summary is not None
        assert "Implemented PR summary support." in summary
        assert "### Changes" in summary
        assert "## Status" not in summary

    @pytest.mark.asyncio
    async def test_brief_missing_returns_none_title_summary_present(self):
        from agentharness.dispatcher import _build_pr_content
        state = self._state_with_dev_task()
        store = _FakeStore({
            "artifacts/feat-x/impl/main.r1.md": "## PR Summary\nA summary.\n## Status\nDONE\n",
        })
        title, summary = await _build_pr_content(state, store)
        assert title is None
        assert summary == "A summary."

    @pytest.mark.asyncio
    async def test_brief_empty_returns_none_title(self):
        from agentharness.dispatcher import _build_pr_content
        state = self._state_with_dev_task()
        store = _FakeStore({
            "artifacts/feat-x/brief.md": "   \n\n",
            "artifacts/feat-x/impl/main.r1.md": "## PR Summary\nx.\n## Status\nDONE\n",
        })
        title, _ = await _build_pr_content(state, store)
        assert title is None

    @pytest.mark.asyncio
    async def test_impl_missing_returns_none_summary_title_present(self):
        from agentharness.dispatcher import _build_pr_content
        state = self._state_with_dev_task()
        store = _FakeStore({
            "artifacts/feat-x/brief.md": "# Title\n",
        })
        title, summary = await _build_pr_content(state, store)
        assert title == "feat: Title"
        assert summary is None

    @pytest.mark.asyncio
    async def test_no_completed_developer_task_returns_none_summary(self):
        from agentharness.dispatcher import _build_pr_content
        state = FeatureState(feature_id="feat-x", status=FeatureStatus.done, tasks=[])
        store = _FakeStore({"artifacts/feat-x/brief.md": "# Title\n"})
        title, summary = await _build_pr_content(state, store)
        assert title == "feat: Title"
        assert summary is None

    @pytest.mark.asyncio
    async def test_pr_summary_section_absent_returns_none_summary(self):
        from agentharness.dispatcher import _build_pr_content
        state = self._state_with_dev_task()
        store = _FakeStore({
            "artifacts/feat-x/brief.md": "# Title\n",
            "artifacts/feat-x/impl/main.r1.md": "## Notes\nn/a\n## Status\nDONE\n",
        })
        _, summary = await _build_pr_content(state, store)
        assert summary is None

    @pytest.mark.asyncio
    async def test_brief_download_exception_falls_back(self, caplog):
        import logging
        from agentharness.dispatcher import _build_pr_content
        state = self._state_with_dev_task()
        store = _FakeStore(
            files={"artifacts/feat-x/impl/main.r1.md": "## PR Summary\nbody.\n"},
            fail_paths={"artifacts/feat-x/brief.md"},
        )
        with caplog.at_level(logging.INFO, logger="agentharness.dispatcher"):
            title, summary = await _build_pr_content(state, store)
        assert title is None
        assert summary == "body."
        assert any("PR title fallback" in rec.message for rec in caplog.records)

    @pytest.mark.asyncio
    async def test_impl_download_exception_falls_back(self, caplog):
        import logging
        from agentharness.dispatcher import _build_pr_content
        state = self._state_with_dev_task()
        store = _FakeStore(
            files={"artifacts/feat-x/brief.md": "# Title\n"},
            fail_paths={"artifacts/feat-x/impl/main.r1.md"},
        )
        with caplog.at_level(logging.INFO, logger="agentharness.dispatcher"):
            title, summary = await _build_pr_content(state, store)
        assert title == "feat: Title"
        assert summary is None
        assert any("PR summary fallback" in rec.message for rec in caplog.records)

    @pytest.mark.asyncio
    async def test_never_raises_on_unexpected_exception(self):
        from agentharness.dispatcher import _build_pr_content

        class BoomStore:
            async def download(self, path: str):
                raise ValueError("boom")
            async def upload(self, path, content): pass
            async def exists(self, path): return False
            async def close(self): pass
            def get_work_dir(self): return None
            async def commit_workdir_changes(self, message): return False

        state = self._state_with_dev_task()
        title, summary = await _build_pr_content(state, BoomStore())
        assert title is None
        assert summary is None

    @pytest.mark.asyncio
    async def test_falls_back_to_brief_body_when_impl_has_no_pr_summary(self):
        from agentharness.dispatcher import _build_pr_content
        state = self._state_with_dev_task()
        store = _FakeStore({
            "artifacts/feat-x/brief.md": "# Telemetry\n\n## Problem\nNeed metrics.\n",
            "artifacts/feat-x/impl/main.r1.md": "## Notes\nno summary here\n## Status\nDONE\n",
        })
        title, summary = await _build_pr_content(state, store)
        assert title == "feat: Telemetry"
        assert summary is not None
        assert "## Problem" in summary
        assert "Need metrics." in summary

    @pytest.mark.asyncio
    async def test_spec_title_overrides_generic_brief_heading(self):
        from agentharness.dispatcher import _build_pr_content
        state = self._state_with_dev_task()
        store = _FakeStore({
            "artifacts/feat-x/brief.md": "## Module\nJournal\n\n## Finding\nDuplicated mapper.",
            "artifacts/feat-x/spec.r1.md": (
                "# Specification: Consolidate JournalEntry→JournalEntryDto into shared mapper\n\nbody"
            ),
            "artifacts/feat-x/impl/main.r1.md": "## PR Summary\nDone.\n## Status\nDONE\n",
        })
        title, _ = await _build_pr_content(state, store)
        assert title == "feat: Consolidate JournalEntry→JournalEntryDto into shared mapper"

    @pytest.mark.asyncio
    async def test_falls_back_to_brief_title_when_spec_missing(self):
        from agentharness.dispatcher import _build_pr_content
        state = self._state_with_dev_task()
        store = _FakeStore({
            "artifacts/feat-x/brief.md": "# Add auth flow\n",
            "artifacts/feat-x/impl/main.r1.md": "## PR Summary\nDone.\n## Status\nDONE\n",
        })
        title, _ = await _build_pr_content(state, store)
        assert title == "feat: Add auth flow"

    @pytest.mark.asyncio
    async def test_spec_with_already_conventional_title_preserved(self):
        from agentharness.dispatcher import _build_pr_content
        state = self._state_with_dev_task()
        store = _FakeStore({
            "artifacts/feat-x/brief.md": "## Module\nPayments\n",
            "artifacts/feat-x/spec.r1.md": "# refactor: extract payment mapper\nbody",
            "artifacts/feat-x/impl/main.r1.md": "## PR Summary\nDone.\n## Status\nDONE\n",
        })
        title, _ = await _build_pr_content(state, store)
        assert title == "refactor: extract payment mapper"
