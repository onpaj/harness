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
    async def test_non_last_epic_child_done_removes_worktree(self):
        """Non-last epic child: worktree IS removed (per-child branches are independent)."""
        state = _make_epic_state(
            status=FeatureStatus.done,
            epic_parent=10,
            epic_position=1,
            epic_total=2,
        )
        state_manager = MagicMock()
        state_manager.set_cleanup_warning = AsyncMock()

        with patch("agentharness.dispatcher.asyncio.to_thread", new_callable=AsyncMock) as mock_thread:
            await run_terminal_cleanup(state, state_manager)

        mock_thread.assert_called_once()  # worktree removal IS triggered

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
    """handle_epic_child_done ticks umbrella PR checklist; marks ready when last child."""

    def _make_mgr(self):
        from agentharness.github_state import GitHubStateManager
        mgr = GitHubStateManager.__new__(GitHubStateManager)
        mgr._client = MagicMock()
        return mgr

    @pytest.mark.asyncio
    async def test_ticks_checkbox_for_child(self):
        """Ticks the child's issue-number checkbox in the existing umbrella PR body."""
        mgr = self._make_mgr()
        state = _make_epic_state(
            epic_position=1,
            epic_total=2,
            state_issue_number=42,
            epic_branch="epic-my-epic",
        )
        existing_pr = {
            "number": 99,
            "state": "open",
            "body": "## Epic\n\nPart of #10\n\n### Tasks\n\n- [ ] #42 Sub-task 1\n- [ ] #43 Sub-task 2",
        }
        mgr._client.list_pull_requests = AsyncMock(return_value=[existing_pr])
        mgr._client.update_pull_request = AsyncMock(return_value={})
        mgr._client.mark_pr_ready = AsyncMock()

        await mgr.handle_epic_child_done(state)

        mgr._client.update_pull_request.assert_called_once()
        updated_body = mgr._client.update_pull_request.call_args.kwargs["body"]
        assert "- [x] #42" in updated_body
        assert "- [ ] #43" in updated_body  # other child still unchecked
        mgr._client.mark_pr_ready.assert_not_called()  # not last child

    @pytest.mark.asyncio
    async def test_marks_ready_when_last_child(self):
        """Calls mark_pr_ready when epic_position == epic_total."""
        mgr = self._make_mgr()
        state = _make_epic_state(
            epic_position=2,
            epic_total=2,
            state_issue_number=43,
            epic_branch="epic-my-epic",
        )
        existing_pr = {
            "number": 99,
            "state": "open",
            "body": "- [x] #42 done\n- [ ] #43 last",
        }
        mgr._client.list_pull_requests = AsyncMock(return_value=[existing_pr])
        mgr._client.update_pull_request = AsyncMock(return_value={})
        mgr._client.mark_pr_ready = AsyncMock()

        await mgr.handle_epic_child_done(state)

        mgr._client.mark_pr_ready.assert_called_once_with(99)

    @pytest.mark.asyncio
    async def test_does_nothing_when_no_umbrella_pr(self):
        """Logs a warning and returns when no open umbrella PR exists."""
        mgr = self._make_mgr()
        state = _make_epic_state(epic_position=1, epic_total=2)
        mgr._client.list_pull_requests = AsyncMock(return_value=[])
        mgr._client.update_pull_request = AsyncMock()
        mgr._client.mark_pr_ready = AsyncMock()

        await mgr.handle_epic_child_done(state)

        mgr._client.update_pull_request.assert_not_called()
        mgr._client.mark_pr_ready.assert_not_called()


# ---------------------------------------------------------------------------
# 5b. _open_feature_pr routing
# ---------------------------------------------------------------------------

class TestOpenFeaturePrEpic:
    @pytest.mark.asyncio
    async def test_epic_child_calls_open_review_and_handle_done(self):
        """Epic child: _open_feature_pr calls open_review (per-child PR) then handle_epic_child_done."""
        from agentharness.github_state import GitHubStateManager

        state = _make_epic_state(
            epic_position=1,
            epic_total=2,
            epic_branch="epic-my-epic",
        )
        state_mgr = MagicMock(spec=GitHubStateManager)
        state_mgr.open_review = AsyncMock(return_value="https://example.com/pull/5")
        state_mgr.handle_epic_child_done = AsyncMock()

        with patch("agentharness.dispatcher._build_pr_content", new_callable=AsyncMock) as mock_build:
            mock_build.return_value = (None, None)
            await _open_feature_pr(state, state_mgr)

        state_mgr.open_review.assert_called_once_with(
            state.feature_id,
            pr_title=None,
            pr_summary=None,
        )
        state_mgr.handle_epic_child_done.assert_called_once_with(state)

    @pytest.mark.asyncio
    async def test_epic_child_handle_done_called_even_if_open_review_raises(self):
        """handle_epic_child_done is called even when open_review raises."""
        from agentharness.github_state import GitHubStateManager

        state = _make_epic_state(
            epic_position=1,
            epic_total=2,
            epic_branch="epic-my-epic",
        )
        state_mgr = MagicMock(spec=GitHubStateManager)
        state_mgr.open_review = AsyncMock(side_effect=RuntimeError("network error"))
        state_mgr.handle_epic_child_done = AsyncMock()

        with patch("agentharness.dispatcher._build_pr_content", new_callable=AsyncMock) as mock_build:
            mock_build.return_value = (None, None)
            await _open_feature_pr(state, state_mgr)  # should not raise

        state_mgr.handle_epic_child_done.assert_called_once_with(state)

    @pytest.mark.asyncio
    async def test_non_epic_calls_only_open_review(self):
        """Non-epic feature: _open_feature_pr calls open_review only, not handle_epic_child_done."""
        from agentharness.github_state import GitHubStateManager

        state = FeatureState(
            feature_id="feat-standalone",
            status=FeatureStatus.done,
        )
        state_mgr = MagicMock(spec=GitHubStateManager)
        state_mgr.open_review = AsyncMock(return_value="https://example.com/pull/1")
        state_mgr.handle_epic_child_done = AsyncMock()

        with patch("agentharness.dispatcher._build_pr_content", new_callable=AsyncMock) as mock_build:
            mock_build.return_value = (None, None)
            await _open_feature_pr(state, state_mgr)

        state_mgr.open_review.assert_called_once()
        state_mgr.handle_epic_child_done.assert_not_called()


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
