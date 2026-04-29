"""Unit tests for backend-agnostic upload_brief and enqueue_planner in agentharness.brainstorm."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from agentharness.brainstorm import enqueue_planner, upload_brief
from agentharness.models import FeatureStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FEATURE_ID = "feat-my-feature"
_BRIEF_CONTENT = "# Feature Brief: My Feature\n\nDo something cool.\n"


def _make_config(
    storage_backend: str = "github",
    max_revisions: int = 3,
) -> MagicMock:
    config = MagicMock()
    config.storage_backend = storage_backend
    config.defaults.max_revisions = max_revisions
    config.defaults.dead_letter_threshold = 3
    config.max_analyst_iterations = 2
    return config


def _make_store(work_dir: str = "/clone/feat-my-feature") -> MagicMock:
    from pathlib import Path
    store = MagicMock()
    store.upload = AsyncMock()
    store.close = AsyncMock()
    store._ensure_clone = AsyncMock()
    store._checkout_or_create = AsyncMock()
    store.get_work_dir = MagicMock(return_value=Path(work_dir))
    return store


def _make_state_mgr(feature_id: str = _FEATURE_ID) -> MagicMock:
    from agentharness.models import FeatureState, FeatureStatus
    mgr = MagicMock()
    mgr.create = AsyncMock()
    mgr.update = AsyncMock(
        return_value=FeatureState(feature_id=feature_id, status=FeatureStatus.analyzing)
    )
    mgr.close = AsyncMock()
    return mgr


def _make_queue() -> MagicMock:
    queue = MagicMock()
    queue.ensure_exists = AsyncMock()
    queue.send_task = AsyncMock()
    queue.close = AsyncMock()
    return queue


# ---------------------------------------------------------------------------
# Tests for upload_brief
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_brief_uploads_and_creates_state() -> None:
    """upload_brief uploads brief artifact and creates initial state."""
    config = _make_config()
    store = _make_store()
    state_mgr = _make_state_mgr()

    with (
        patch("agentharness.brainstorm.create_artifact_store", return_value=store) as mock_store_factory,
        patch("agentharness.brainstorm.create_state_manager", return_value=state_mgr) as mock_state_factory,
    ):
        await upload_brief(_FEATURE_ID, _BRIEF_CONTENT, config)

    mock_store_factory.assert_called_once_with(config, feature_id=_FEATURE_ID)
    mock_state_factory.assert_called_once_with(config)

    store.upload.assert_awaited_once_with(
        f"artifacts/{_FEATURE_ID}/brief.md", _BRIEF_CONTENT
    )
    state_mgr.create.assert_awaited_once()
    created_state = state_mgr.create.call_args.args[0]
    assert created_state.feature_id == _FEATURE_ID
    assert created_state.status == FeatureStatus.brainstormed

    # brief_content passed as keyword arg
    assert state_mgr.create.call_args.kwargs.get("brief_content") == _BRIEF_CONTENT

    store.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_upload_brief_closes_store_on_error() -> None:
    """upload_brief closes the store even when upload raises."""
    config = _make_config()
    store = _make_store()
    store.upload.side_effect = RuntimeError("upload error")
    state_mgr = _make_state_mgr()

    with (
        patch("agentharness.brainstorm.create_artifact_store", return_value=store),
        patch("agentharness.brainstorm.create_state_manager", return_value=state_mgr),
    ):
        with pytest.raises(RuntimeError, match="upload error"):
            await upload_brief(_FEATURE_ID, _BRIEF_CONTENT, config)

    store.close.assert_awaited_once()


# ---------------------------------------------------------------------------
# Tests for enqueue_planner
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enqueue_planner_sends_correct_task() -> None:
    """enqueue_planner creates a worktree clone, writes brief.md, and sends analyst task."""
    import tempfile
    from pathlib import Path

    config = _make_config()
    queue = _make_queue()
    state_mgr = _make_state_mgr()

    with tempfile.TemporaryDirectory() as tmp:
        store = _make_store(work_dir=tmp)

        with (
            patch("agentharness.brainstorm.create_task_queue", return_value=queue) as mock_queue_factory,
            patch("agentharness.brainstorm.create_state_manager", return_value=state_mgr),
            patch("agentharness.brainstorm.create_artifact_store", return_value=store),
            patch(
                "agentharness.brainstorm._fetch_brief_for_feature",
                new=AsyncMock(return_value=_BRIEF_CONTENT),
            ),
        ):
            await enqueue_planner(_FEATURE_ID, config)

        mock_queue_factory.assert_called_once_with(config, "analyst-queue")

        # ensure_exists called before send_task
        assert queue.ensure_exists.await_count == 1
        assert queue.send_task.await_count == 1

        ensure_exists_order = queue.method_calls.index(call.ensure_exists())
        send_task_order = next(
            i
            for i, c in enumerate(queue.method_calls)
            if c[0] == "send_task"
        )
        assert ensure_exists_order < send_task_order

        # Check the TaskMessage
        task = queue.send_task.call_args.args[0]
        assert task.feature_id == _FEATURE_ID
        assert task.task_id == f"{_FEATURE_ID}-analyst"
        assert task.agent_role == "analyst"
        assert task.input_artifacts == [f"artifacts/{_FEATURE_ID}/brief.md"]
        assert task.output_artifact == f"artifacts/{_FEATURE_ID}/spec.r1.md"
        assert task.work_dir == tmp

        # brief.md should be written to the worktree
        assert (Path(tmp) / "brief.md").read_text() == _BRIEF_CONTENT

        queue.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_enqueue_planner_closes_queue_on_error() -> None:
    """enqueue_planner closes the queue even when ensure_exists raises."""
    import tempfile

    config = _make_config()
    queue = _make_queue()
    queue.ensure_exists.side_effect = RuntimeError("label error")
    state_mgr = _make_state_mgr()

    with tempfile.TemporaryDirectory() as tmp:
        store = _make_store(work_dir=tmp)

        with (
            patch("agentharness.brainstorm.create_task_queue", return_value=queue),
            patch("agentharness.brainstorm.create_state_manager", return_value=state_mgr),
            patch("agentharness.brainstorm.create_artifact_store", return_value=store),
            patch(
                "agentharness.brainstorm._fetch_brief_for_feature",
                new=AsyncMock(return_value=_BRIEF_CONTENT),
            ),
        ):
            with pytest.raises(RuntimeError, match="label error"):
                await enqueue_planner(_FEATURE_ID, config)

    queue.close.assert_awaited_once()


# ---------------------------------------------------------------------------
# _slug_from_brief delegation
# ---------------------------------------------------------------------------


class TestSlugFromBriefDelegates:
    def test_brief_h1_passed_through_slug_title(self):
        from agentharness.brainstorm import _slug_from_brief
        assert _slug_from_brief("# Feature Brief: My Cool Thing\n\nbody") == "my-cool-thing"

    def test_no_h1_yields_untitled(self):
        from agentharness.brainstorm import _slug_from_brief
        assert _slug_from_brief("body without heading") == "untitled"

    def test_round_trip_with_slug_title(self):
        from agentharness.brainstorm import _slug_from_brief
        from agentharness.github_state import slug_title
        assert _slug_from_brief("# Add User Export Endpoint\n") == slug_title("Add User Export Endpoint")


# ---------------------------------------------------------------------------
# _convert_raw_issue
# ---------------------------------------------------------------------------


class TestConvertRawIssue:
    @staticmethod
    def _raw_issue(*, number: int = 7, title: str, body: str = "Issue body content.") -> dict:
        return {
            "number": number,
            "title": title,
            "body": body,
            "created_at": "2026-04-25T10:00:00Z",
            "updated_at": "2026-04-25T10:00:00Z",
            "labels": [{"name": "agent"}],
        }

    @pytest.mark.asyncio
    async def test_happy_path_creates_branch_uploads_brief_patches_issue(self):
        from agentharness.brainstorm import _convert_raw_issue
        from agentharness.models import FeatureStatus

        config = _make_config()
        config.github.feature_marker = "agent"

        gh_client = AsyncMock()
        gh_client.list_issues.return_value = [
            TestConvertRawIssue._raw_issue(number=7, title="Add Export Endpoint")
        ]
        gh_client.get_default_branch.return_value = "main"
        gh_client.get_ref.return_value = {"object": {"sha": "abc123"}}
        gh_client.create_ref = AsyncMock(return_value={"ref": "refs/heads/feat-add-export-endpoint"})
        gh_client.close = AsyncMock()

        store = _make_store(work_dir="/clone/feat-add-export-endpoint")
        state_mgr = MagicMock()
        state_mgr.patch_existing_issue = AsyncMock()
        state_mgr.close = AsyncMock()

        with (
            patch("agentharness.brainstorm.GitHubClient.from_config", return_value=gh_client),
            patch("agentharness.brainstorm.create_artifact_store", return_value=store),
            patch("agentharness.brainstorm.create_state_manager", return_value=state_mgr),
        ):
            await _convert_raw_issue("feat-add-export-endpoint", config)

        # Branch creation
        gh_client.create_ref.assert_awaited_once()
        ref_args = gh_client.create_ref.call_args
        assert ref_args.args[0] == "refs/heads/feat-add-export-endpoint"
        assert ref_args.args[1] == "abc123"

        # Brief artifact upload
        store.upload.assert_awaited_once_with(
            "artifacts/feat-add-export-endpoint/brief.md",
            "Issue body content.",
        )

        # Issue patch
        state_mgr.patch_existing_issue.assert_awaited_once()
        call_args = state_mgr.patch_existing_issue.call_args
        assert call_args.args[0] == 7  # issue number
        patched_state = call_args.args[1]
        assert patched_state.feature_id == "feat-add-export-endpoint"
        assert patched_state.status == FeatureStatus.brainstormed
        assert patched_state.state_issue_number == 7
        assert patched_state.branch_name == "feat-add-export-endpoint"
        assert call_args.kwargs.get("brief_content") == "Issue body content."

    @pytest.mark.asyncio
    async def test_branch_already_exists_is_tolerated(self):
        """A 422 on create_ref means the branch exists; conversion still completes."""
        from agentharness.brainstorm import _convert_raw_issue
        from agentharness.github_client import GitHubApiError

        config = _make_config()
        config.github.feature_marker = "agent"

        gh_client = AsyncMock()
        gh_client.list_issues.return_value = [
            TestConvertRawIssue._raw_issue(number=7, title="Already Exists")
        ]
        gh_client.get_default_branch.return_value = "main"
        gh_client.get_ref.return_value = {"object": {"sha": "abc123"}}
        gh_client.create_ref.side_effect = GitHubApiError(422, "Reference already exists")
        gh_client.close = AsyncMock()

        store = _make_store(work_dir="/clone/feat-already-exists")
        state_mgr = MagicMock()
        state_mgr.patch_existing_issue = AsyncMock()
        state_mgr.close = AsyncMock()

        with (
            patch("agentharness.brainstorm.GitHubClient.from_config", return_value=gh_client),
            patch("agentharness.brainstorm.create_artifact_store", return_value=store),
            patch("agentharness.brainstorm.create_state_manager", return_value=state_mgr),
        ):
            # Must not raise
            await _convert_raw_issue("feat-already-exists", config)

        # Subsequent steps still run
        store.upload.assert_awaited_once()
        state_mgr.patch_existing_issue.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_matching_issue_raises_value_error(self):
        from agentharness.brainstorm import _convert_raw_issue

        config = _make_config()
        config.github.feature_marker = "agent"

        gh_client = AsyncMock()
        gh_client.list_issues.return_value = [
            TestConvertRawIssue._raw_issue(number=7, title="Different Title")
        ]
        gh_client.close = AsyncMock()

        with patch("agentharness.brainstorm.GitHubClient.from_config", return_value=gh_client):
            with pytest.raises(ValueError, match="feat-no-such-feature"):
                await _convert_raw_issue("feat-no-such-feature", config)

    @pytest.mark.asyncio
    async def test_closes_resources_even_on_error(self):
        """If patch_existing_issue raises, we still close client/store/state_mgr."""
        from agentharness.brainstorm import _convert_raw_issue

        config = _make_config()
        config.github.feature_marker = "agent"

        gh_client = AsyncMock()
        gh_client.list_issues.return_value = [
            TestConvertRawIssue._raw_issue(number=7, title="Boom Title")
        ]
        gh_client.get_default_branch.return_value = "main"
        gh_client.get_ref.return_value = {"object": {"sha": "abc123"}}
        gh_client.create_ref = AsyncMock(return_value={})
        gh_client.close = AsyncMock()

        store = _make_store()
        state_mgr = MagicMock()
        state_mgr.patch_existing_issue = AsyncMock(side_effect=RuntimeError("api down"))
        state_mgr.close = AsyncMock()

        with (
            patch("agentharness.brainstorm.GitHubClient.from_config", return_value=gh_client),
            patch("agentharness.brainstorm.create_artifact_store", return_value=store),
            patch("agentharness.brainstorm.create_state_manager", return_value=state_mgr),
        ):
            with pytest.raises(RuntimeError, match="api down"):
                await _convert_raw_issue("feat-boom-title", config)

        gh_client.close.assert_awaited_once()
        store.close.assert_awaited_once()
        state_mgr.close.assert_awaited_once()
