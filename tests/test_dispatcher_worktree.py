"""Tests for dispatcher worktree cleanup hooks on terminal state transitions."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentharness.dispatcher import run_terminal_cleanup
from agentharness.models import FeatureState, FeatureStatus
from agentharness.worktree_manager import WorktreeRemovalError


def _state(status: FeatureStatus, worktree_path: str | None = None) -> FeatureState:
    s = FeatureState(feature_id="feat-test-abc", status=status)
    if worktree_path is not None:
        s = s.model_copy(update={"worktree_path": worktree_path})
    return s


def _mock_state_manager() -> MagicMock:
    mgr = MagicMock()
    mgr.set_cleanup_warning = AsyncMock()
    return mgr


@pytest.mark.asyncio
class TestRunTerminalCleanupDone:
    async def test_done_with_worktree_calls_remove(self):
        state = _state(FeatureStatus.done, worktree_path="/repo/.worktrees/feat-test-abc")
        mgr = _mock_state_manager()

        with patch("agentharness.dispatcher.remove_worktree") as mock_remove:
            await run_terminal_cleanup(state, mgr)

        mock_remove.assert_called_once_with("/repo/.worktrees/feat-test-abc")

    async def test_done_with_no_worktree_skips_removal(self):
        state = _state(FeatureStatus.done, worktree_path=None)
        mgr = _mock_state_manager()

        with patch("agentharness.dispatcher.remove_worktree") as mock_remove:
            await run_terminal_cleanup(state, mgr)

        mock_remove.assert_not_called()

    async def test_done_cleanup_failure_persists_cleanup_warning(self):
        state = _state(FeatureStatus.done, worktree_path="/repo/.worktrees/feat-test-abc")
        mgr = _mock_state_manager()
        err = WorktreeRemovalError("disk full", returncode=1, stderr="no space")

        with patch("agentharness.dispatcher.remove_worktree", side_effect=err):
            await run_terminal_cleanup(state, mgr)

        mgr.set_cleanup_warning.assert_awaited_once_with("feat-test-abc", str(err))

    async def test_done_cleanup_failure_does_not_raise(self):
        state = _state(FeatureStatus.done, worktree_path="/repo/.worktrees/feat-test-abc")
        mgr = _mock_state_manager()

        with patch(
            "agentharness.dispatcher.remove_worktree",
            side_effect=WorktreeRemovalError("gone wrong"),
        ):
            await run_terminal_cleanup(state, mgr)  # must not raise

    async def test_done_cleanup_failure_logs_error(self, caplog):
        state = _state(FeatureStatus.done, worktree_path="/repo/.worktrees/feat-test-abc")
        mgr = _mock_state_manager()

        with patch(
            "agentharness.dispatcher.remove_worktree",
            side_effect=WorktreeRemovalError("gone wrong"),
        ), caplog.at_level(logging.ERROR, logger="agentharness.dispatcher"):
            await run_terminal_cleanup(state, mgr)

        assert any("gone wrong" in r.message or "removal" in r.message.lower() for r in caplog.records)


@pytest.mark.asyncio
class TestRunTerminalCleanupFailed:
    async def test_failed_with_worktree_does_not_call_remove(self):
        state = _state(FeatureStatus.failed, worktree_path="/repo/.worktrees/feat-test-abc")
        mgr = _mock_state_manager()

        with patch("agentharness.dispatcher.remove_worktree") as mock_remove:
            await run_terminal_cleanup(state, mgr)

        mock_remove.assert_not_called()

    async def test_failed_with_worktree_logs_preservation(self, caplog):
        state = _state(FeatureStatus.failed, worktree_path="/repo/.worktrees/feat-test-abc")
        mgr = _mock_state_manager()

        with caplog.at_level(logging.INFO, logger="agentharness.dispatcher"):
            with patch("agentharness.dispatcher.remove_worktree"):
                await run_terminal_cleanup(state, mgr)

        assert any(
            "/repo/.worktrees/feat-test-abc" in r.message or "preserv" in r.message.lower()
            for r in caplog.records
        )

    async def test_failed_with_no_worktree_is_noop(self):
        state = _state(FeatureStatus.failed, worktree_path=None)
        mgr = _mock_state_manager()

        with patch("agentharness.dispatcher.remove_worktree") as mock_remove:
            await run_terminal_cleanup(state, mgr)

        mock_remove.assert_not_called()
        mgr.set_cleanup_warning.assert_not_awaited()

    async def test_failed_worktree_path_preserved_in_state(self):
        state = _state(FeatureStatus.failed, worktree_path="/repo/.worktrees/feat-test-abc")
        mgr = _mock_state_manager()

        with patch("agentharness.dispatcher.remove_worktree"):
            await run_terminal_cleanup(state, mgr)

        assert state.worktree_path == "/repo/.worktrees/feat-test-abc"


@pytest.mark.asyncio
class TestRunTerminalCleanupNonTerminal:
    async def test_non_terminal_status_is_noop(self):
        for status in (FeatureStatus.developing, FeatureStatus.reviewing, FeatureStatus.planning):
            state = _state(status, worktree_path="/repo/.worktrees/feat-test-abc")
            mgr = _mock_state_manager()

            with patch("agentharness.dispatcher.remove_worktree") as mock_remove:
                await run_terminal_cleanup(state, mgr)

            mock_remove.assert_not_called()
            mgr.set_cleanup_warning.assert_not_awaited()
