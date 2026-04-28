"""Unit tests for dispatcher — state transitions, parsing, serial dispatch."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agentharness.config import Config
from agentharness.dispatcher import (
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

    async def test_pass_with_no_more_tasks_persists_pr_on_state(self):
        """When all tasks pass review and a PR is opened, pr_url is stored on the returned state."""
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

        with _mock_github_client(pr_number=7, pr_url="https://github.com/org/repo/pull/7") as mock_cls:
            result = await _dispatch_review_result(state, review_task, review_output, cfg, queues)

        assert result.status == FeatureStatus.done
        assert result.pr_number == 7
        assert result.pr_url == "https://github.com/org/repo/pull/7"

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


@pytest.mark.asyncio
class TestOpenFeaturePr:
    def _done_state(self, branch_name: str = "feat-auth-42", issue_number: int = 42) -> FeatureState:
        return FeatureState(
            feature_id="feat-auth",
            status=FeatureStatus.done,
            branch_name=branch_name,
            state_issue_number=issue_number,
        )

    async def test_noop_for_azure_backend(self):
        """Azure backend: _open_feature_pr returns (None, None) immediately."""
        state = self._done_state()
        cfg = _make_config()  # storage_backend = "azure"
        pr_number, pr_url = await _open_feature_pr(state, cfg)
        assert pr_number is None
        assert pr_url is None

    async def test_uses_branch_name_as_head(self):
        """PR is created with head = state.branch_name, not state.feature_id."""
        state = self._done_state(branch_name="feat-auth-42")
        cfg = _make_github_config()

        with _mock_github_client() as mock_cls:
            await _open_feature_pr(state, cfg)

        client = mock_cls.from_config.return_value
        call_kwargs = client.create_pull_request.call_args.kwargs
        assert call_kwargs["head"] == "feat-auth-42"

    async def test_falls_back_to_feature_id_when_branch_name_is_none(self):
        """If branch_name is not set, fall back to feature_id."""
        state = FeatureState(feature_id="feat-auth", status=FeatureStatus.done, state_issue_number=42)
        cfg = _make_github_config()

        with _mock_github_client() as mock_cls:
            await _open_feature_pr(state, cfg)

        client = mock_cls.from_config.return_value
        call_kwargs = client.create_pull_request.call_args.kwargs
        assert call_kwargs["head"] == "feat-auth"

    async def test_returns_pr_number_and_url(self):
        """Returns (pr_number, pr_url) on success."""
        state = self._done_state()
        cfg = _make_github_config()

        with _mock_github_client(pr_number=7, pr_url="https://github.com/org/repo/pull/7"):
            pr_number, pr_url = await _open_feature_pr(state, cfg)

        assert pr_number == 7
        assert pr_url == "https://github.com/org/repo/pull/7"

    async def test_posts_success_comment_on_tracking_issue(self):
        """On success, a comment with the PR URL is posted on state_issue_number."""
        state = self._done_state(issue_number=42)
        cfg = _make_github_config()

        with _mock_github_client(pr_number=5, pr_url="https://github.com/org/repo/pull/5") as mock_cls:
            await _open_feature_pr(state, cfg)

        client = mock_cls.from_config.return_value
        client.create_comment.assert_awaited_once()
        comment_body: str = client.create_comment.call_args.args[1]
        assert "https://github.com/org/repo/pull/5" in comment_body

    async def test_posts_error_comment_on_failure(self):
        """On PR creation failure, an error comment is posted on the tracking issue."""
        state = self._done_state(issue_number=42)
        cfg = _make_github_config()

        with _mock_github_client(raise_exc=Exception("API error")) as mock_cls:
            pr_number, pr_url = await _open_feature_pr(state, cfg)

        assert pr_number is None
        client = mock_cls.from_config.return_value
        client.create_comment.assert_awaited_once()
        comment_body: str = client.create_comment.call_args.args[1]
        assert "API error" in comment_body

    async def test_done_via_serial_next_persists_pr_url(self):
        """_dispatch_serial_next folds pr_url into returned state when GitHub backend."""
        state = _make_state_with_pending_tasks("feat-gh", ["auth"])
        state = state.model_copy(update={"branch_name": "feat-gh-10", "state_issue_number": 10})
        dev_task = _make_dev_task("feat-gh", "auth")
        queues = _make_queues()
        cfg = _make_github_config()

        with _mock_github_client(pr_number=3, pr_url="https://github.com/org/repo/pull/3"):
            result = await _dispatch_serial_next(state, dev_task, "## Status\nDONE\n", cfg, queues)

        assert result.status == FeatureStatus.done
        assert result.pr_url == "https://github.com/org/repo/pull/3"
        assert result.pr_number == 3
