"""Tests for Task 5: epic dispatcher logic — worktree retention, draft PR lifecycle, pause-on-failure."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agentharness.dispatcher import run_terminal_cleanup, _open_feature_pr
from agentharness.models import FeatureState, FeatureStatus


def _make_epic_state(
    *,
    status: FeatureStatus = FeatureStatus.done,
    epic_parent: int | None = 10,
    epic_position: int | None = 1,
    epic_total: int | None = 2,
    worktree_path: str | None = "/tmp/wt/feat-x",
    state_issue_number: int | None = 42,
    epic_branch: str | None = "epic-my-epic",
) -> FeatureState:
    return FeatureState(
        feature_id="feat-my-feature",
        status=status,
        worktree_path=worktree_path,
        epic_parent=epic_parent,
        epic_position=epic_position,
        epic_total=epic_total,
        epic_branch=epic_branch,
        state_issue_number=state_issue_number,
    )


# ---------------------------------------------------------------------------
# 5a. Worktree retention
# ---------------------------------------------------------------------------

class TestWorktreeRetention:
    @pytest.mark.asyncio
    async def test_non_last_epic_child_done_preserves_worktree(self):
        """Non-last epic child (position < total): worktree should NOT be removed."""
        state = _make_epic_state(
            status=FeatureStatus.done,
            epic_parent=10,
            epic_position=1,
            epic_total=2,
        )
        state_manager = MagicMock()

        with patch("agentharness.dispatcher.remove_worktree") as mock_remove:
            await run_terminal_cleanup(state, state_manager)

        mock_remove.assert_not_called()

    @pytest.mark.asyncio
    async def test_last_epic_child_done_removes_worktree(self):
        """Last epic child (position == total): worktree SHOULD be removed."""
        state = _make_epic_state(
            status=FeatureStatus.done,
            epic_parent=10,
            epic_position=2,
            epic_total=2,
        )
        state_manager = MagicMock()
        state_manager.set_cleanup_warning = AsyncMock()

        with patch("agentharness.dispatcher.asyncio.to_thread", new_callable=AsyncMock) as mock_thread:
            await run_terminal_cleanup(state, state_manager)

        mock_thread.assert_called_once()

    @pytest.mark.asyncio
    async def test_non_epic_done_removes_worktree(self):
        """Non-epic feature: worktree should be removed normally on done."""
        state = FeatureState(
            feature_id="feat-normal",
            status=FeatureStatus.done,
            worktree_path="/tmp/wt/feat-normal",
        )
        state_manager = MagicMock()
        state_manager.set_cleanup_warning = AsyncMock()

        with patch("agentharness.dispatcher.asyncio.to_thread", new_callable=AsyncMock) as mock_thread:
            await run_terminal_cleanup(state, state_manager)

        mock_thread.assert_called_once()

    @pytest.mark.asyncio
    async def test_epic_failed_applies_pause(self):
        """Failed epic child triggers handle_epic_child_failed on GitHubStateManager."""
        from agentharness.github_state import GitHubStateManager

        state = _make_epic_state(
            status=FeatureStatus.failed,
            epic_parent=10,
            epic_position=1,
            epic_total=2,
        )

        state_manager = MagicMock(spec=GitHubStateManager)
        state_manager.handle_epic_child_failed = AsyncMock()

        await run_terminal_cleanup(state, state_manager)

        state_manager.handle_epic_child_failed.assert_called_once_with(
            state,
            reason="Feature feat-my-feature reached failed status",
        )

    @pytest.mark.asyncio
    async def test_non_epic_failed_does_not_call_pause(self):
        """Failed non-epic feature does NOT call handle_epic_child_failed."""
        from agentharness.github_state import GitHubStateManager

        state = FeatureState(
            feature_id="feat-normal",
            status=FeatureStatus.failed,
            worktree_path="/tmp/wt/feat-normal",
        )

        state_manager = MagicMock(spec=GitHubStateManager)
        state_manager.handle_epic_child_failed = AsyncMock()

        await run_terminal_cleanup(state, state_manager)

        state_manager.handle_epic_child_failed.assert_not_called()


# ---------------------------------------------------------------------------
# 5b. Eager draft PR lifecycle
# ---------------------------------------------------------------------------

class TestHandleEpicChildDone:
    def _make_github_state_manager(self) -> MagicMock:
        from agentharness.github_state import GitHubStateManager
        mgr = MagicMock(spec=GitHubStateManager)
        mgr._client = MagicMock()
        return mgr

    @pytest.mark.asyncio
    async def test_opens_draft_pr_for_first_child(self):
        """First epic child with no existing PR: draft PR should be opened with a checklist."""
        from agentharness.github_state import GitHubStateManager

        state = _make_epic_state(
            epic_position=1,
            epic_total=2,
            state_issue_number=42,
        )

        mgr = GitHubStateManager.__new__(GitHubStateManager)
        mgr._client = MagicMock()
        mgr._client.list_pull_requests = AsyncMock(return_value=[])
        mgr._client.get_issue = AsyncMock(return_value={"title": "My Epic Feature", "number": 10})
        mgr._client.list_sub_issues = AsyncMock(return_value=[
            {"number": 42, "title": "Sub-task 1"},
            {"number": 43, "title": "Sub-task 2"},
        ])
        mgr._client.get_default_branch = AsyncMock(return_value="main")
        mgr._client.create_pull_request = AsyncMock(return_value={
            "number": 99,
            "state": "open",
            "body": "## Epic\n\nPart of #10\n\n### Tasks\n\n- [ ] #42 Sub-task 1\n- [ ] #43 Sub-task 2",
        })
        mgr._client.update_pull_request = AsyncMock(return_value={})
        mgr._client.mark_pr_ready = AsyncMock()

        await mgr.handle_epic_child_done(state)

        mgr._client.create_pull_request.assert_called_once()
        call_kwargs = mgr._client.create_pull_request.call_args
        assert call_kwargs.kwargs.get("draft") is True
        body = call_kwargs.kwargs.get("body", "")
        assert "- [ ] #42" in body
        assert "- [ ] #43" in body
        # First child's checkbox should be ticked via update_pull_request
        mgr._client.update_pull_request.assert_called_once()
        updated_body = mgr._client.update_pull_request.call_args.kwargs.get("body", "")
        assert "- [x] #42" in updated_body
        assert "- [ ] #43" in updated_body
        # Not last child: should NOT mark ready
        mgr._client.mark_pr_ready.assert_not_called()

    @pytest.mark.asyncio
    async def test_ticks_checkbox_for_subsequent_child(self):
        """Subsequent child with existing open PR: checkbox ticked, PR not marked ready."""
        from agentharness.github_state import GitHubStateManager

        state = _make_epic_state(
            epic_position=1,
            epic_total=2,
            state_issue_number=42,
        )

        existing_pr = {
            "number": 99,
            "state": "open",
            "body": "## Epic\n\nPart of #10\n\n### Tasks\n\n- [ ] #42 Sub-task 1\n- [ ] #43 Sub-task 2",
        }

        mgr = GitHubStateManager.__new__(GitHubStateManager)
        mgr._client = MagicMock()
        mgr._client.list_pull_requests = AsyncMock(return_value=[existing_pr])
        mgr._client.update_pull_request = AsyncMock(return_value={})
        mgr._client.mark_pr_ready = AsyncMock()

        await mgr.handle_epic_child_done(state)

        mgr._client.update_pull_request.assert_called_once()
        updated_body = mgr._client.update_pull_request.call_args.kwargs.get("body", "")
        assert "- [x] #42" in updated_body
        assert "- [ ] #43" in updated_body
        # Not last child: should NOT mark ready
        mgr._client.mark_pr_ready.assert_not_called()

    @pytest.mark.asyncio
    async def test_marks_pr_ready_for_last_child(self):
        """Last epic child: PR should be marked ready for review after update."""
        from agentharness.github_state import GitHubStateManager

        state = _make_epic_state(
            epic_position=2,
            epic_total=2,
            state_issue_number=43,
        )

        existing_pr = {
            "number": 99,
            "state": "open",
            "body": "## Epic\n\nPart of #10\n\n### Tasks\n\n- [x] #42 Sub-task 1\n- [ ] #43 Sub-task 2",
        }

        mgr = GitHubStateManager.__new__(GitHubStateManager)
        mgr._client = MagicMock()
        mgr._client.list_pull_requests = AsyncMock(return_value=[existing_pr])
        mgr._client.update_pull_request = AsyncMock(return_value={})
        mgr._client.mark_pr_ready = AsyncMock(return_value={})

        await mgr.handle_epic_child_done(state)

        mgr._client.mark_pr_ready.assert_called_once_with(99)

    @pytest.mark.asyncio
    async def test_returns_early_when_no_epic_parent(self):
        """State with no epic_parent: handle_epic_child_done is a no-op."""
        from agentharness.github_state import GitHubStateManager

        state = FeatureState(
            feature_id="feat-standalone",
            status=FeatureStatus.done,
        )

        mgr = GitHubStateManager.__new__(GitHubStateManager)
        mgr._client = MagicMock()
        mgr._client.list_pull_requests = AsyncMock()

        await mgr.handle_epic_child_done(state)

        mgr._client.list_pull_requests.assert_not_called()


# ---------------------------------------------------------------------------
# 5b. _open_feature_pr routing
# ---------------------------------------------------------------------------

class TestOpenFeaturePr:
    @pytest.mark.asyncio
    async def test_open_feature_pr_bypasses_regular_pr_for_epic(self):
        """Epic child: open_review should NOT be called; handle_epic_child_done IS called."""
        from agentharness.github_state import GitHubStateManager

        state = _make_epic_state(
            status=FeatureStatus.done,
            epic_parent=10,
        )

        state_mgr = MagicMock(spec=GitHubStateManager)
        state_mgr.handle_epic_child_done = AsyncMock()
        state_mgr.open_review = AsyncMock()

        await _open_feature_pr(state, state_mgr)

        state_mgr.handle_epic_child_done.assert_called_once_with(state)
        state_mgr.open_review.assert_not_called()

    @pytest.mark.asyncio
    async def test_open_feature_pr_calls_open_review_for_non_epic(self):
        """Non-epic feature: open_review should be called normally."""
        from agentharness.github_state import GitHubStateManager

        state = FeatureState(
            feature_id="feat-normal",
            status=FeatureStatus.done,
        )

        state_mgr = MagicMock(spec=GitHubStateManager)
        state_mgr.open_review = AsyncMock()
        state_mgr.handle_epic_child_done = AsyncMock()

        with patch("agentharness.dispatcher._build_pr_content", new_callable=AsyncMock) as mock_build:
            mock_build.return_value = ("PR Title", "PR Summary")
            await _open_feature_pr(state, state_mgr)

        state_mgr.open_review.assert_called_once()
        state_mgr.handle_epic_child_done.assert_not_called()

    @pytest.mark.asyncio
    async def test_open_feature_pr_returns_early_for_none_state_mgr(self):
        """state_mgr=None: returns immediately without error."""
        state = _make_epic_state()
        # Should not raise
        await _open_feature_pr(state, None)


# ---------------------------------------------------------------------------
# 5c. handle_epic_child_failed
# ---------------------------------------------------------------------------

class TestHandleEpicChildFailed:
    @pytest.mark.asyncio
    async def test_applies_pause_label_and_posts_comment(self):
        """handle_epic_child_failed applies EPIC_PAUSED label and posts a comment."""
        from agentharness.github_state import GitHubStateManager
        from agentharness.github_labels import EPIC_PAUSED

        state = _make_epic_state(
            status=FeatureStatus.failed,
            epic_parent=10,
            state_issue_number=42,
        )

        mgr = GitHubStateManager.__new__(GitHubStateManager)
        mgr._client = MagicMock()
        mgr._client.add_labels = AsyncMock()
        mgr._client.create_comment = AsyncMock()

        await mgr.handle_epic_child_failed(state, reason="test failure")

        mgr._client.add_labels.assert_called_once_with(10, [EPIC_PAUSED])
        mgr._client.create_comment.assert_called_once()
        comment_body = mgr._client.create_comment.call_args.args[1]
        assert "test failure" in comment_body
        assert "epic:paused" in comment_body
        assert "feat-my-feature" in comment_body

    @pytest.mark.asyncio
    async def test_returns_early_when_no_epic_parent(self):
        """State with no epic_parent: handle_epic_child_failed is a no-op."""
        from agentharness.github_state import GitHubStateManager

        state = FeatureState(
            feature_id="feat-standalone",
            status=FeatureStatus.failed,
        )

        mgr = GitHubStateManager.__new__(GitHubStateManager)
        mgr._client = MagicMock()
        mgr._client.add_labels = AsyncMock()

        await mgr.handle_epic_child_failed(state)

        mgr._client.add_labels.assert_not_called()

    @pytest.mark.asyncio
    async def test_label_failure_does_not_prevent_comment(self):
        """If add_labels raises, the method still attempts to post the comment."""
        from agentharness.github_state import GitHubStateManager

        state = _make_epic_state(
            status=FeatureStatus.failed,
            epic_parent=10,
            state_issue_number=42,
        )

        mgr = GitHubStateManager.__new__(GitHubStateManager)
        mgr._client = MagicMock()
        mgr._client.add_labels = AsyncMock(side_effect=Exception("network error"))
        mgr._client.create_comment = AsyncMock()

        await mgr.handle_epic_child_failed(state, reason="something bad")

        mgr._client.create_comment.assert_called_once()
