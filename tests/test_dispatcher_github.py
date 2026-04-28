"""Tests for GitHub PR opening on feature completion."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from agentharness.dispatcher import _open_feature_pr
from agentharness.models import (
    FeatureState,
    FeatureStatus,
    PhaseInfo,
    PhaseStatus,
    TaskEntry,
    TaskStatus,
)


def _make_state_mgr(pr_url: str | None = "https://github.com/owner/repo/pull/42") -> AsyncMock:
    state_mgr = AsyncMock()
    state_mgr.open_review = AsyncMock(return_value=pr_url)
    return state_mgr


def _make_done_state(feature_id: str = "feat-20260427-abc") -> FeatureState:
    state = FeatureState(feature_id=feature_id, status=FeatureStatus.done)
    state = state.with_phase("analyzing", PhaseInfo(status=PhaseStatus.completed))
    state = state.with_phase("planning", PhaseInfo(status=PhaseStatus.completed))
    state = state.with_tasks_added([
        TaskEntry(
            task_id=f"{feature_id}-dev-task-a",
            phase="developing",
            status=TaskStatus.completed,
        ),
        TaskEntry(
            task_id=f"{feature_id}-dev-task-b",
            phase="developing",
            status=TaskStatus.completed,
        ),
    ])
    return state



@pytest.mark.asyncio
class TestOpenFeaturePr:
    async def test_calls_open_review_on_state_mgr(self):
        state = _make_done_state("feat-pr-test")
        state_mgr = _make_state_mgr()

        await _open_feature_pr(state, state_mgr)

        state_mgr.open_review.assert_awaited_once_with("feat-pr-test")

    async def test_no_op_when_state_mgr_is_none(self):
        state = _make_done_state("feat-no-mgr")
        # Should not raise
        await _open_feature_pr(state, None)

    async def test_delegates_to_state_mgr_open_review(self):
        state = _make_done_state("feat-delegate")
        state_mgr = _make_state_mgr(pr_url="https://github.com/owner/repo/pull/7")

        await _open_feature_pr(state, state_mgr)

        state_mgr.open_review.assert_awaited_once_with("feat-delegate")

    async def test_open_review_error_propagates(self):
        state = _make_done_state("feat-error")
        state_mgr = AsyncMock()
        state_mgr.open_review = AsyncMock(side_effect=RuntimeError("API down"))

        with pytest.raises(RuntimeError, match="API down"):
            await _open_feature_pr(state, state_mgr)
