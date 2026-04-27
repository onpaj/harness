"""Unit tests for observer stale-claim sweeper functionality."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from agentharness.observer import _reclaim_issue
from agentharness.github_labels import (
    CLAIMED_BY_PREFIX,
    STATE_IN_PROGRESS,
    STATE_QUEUED,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client(owner: str = "test-owner", repo: str = "test-repo") -> MagicMock:
    client = MagicMock()
    client.owner = owner
    client.repo = repo
    client.search_issues = AsyncMock(return_value=[])
    client.remove_label = AsyncMock()
    client.add_labels = AsyncMock()
    client.create_comment = AsyncMock()
    client.close = AsyncMock()
    return client


def _make_issue(
    number: int = 42,
    labels: list[str] | None = None,
    body: str = "",
) -> dict:
    return {
        "number": number,
        "body": body,
        "labels": [{"name": lbl} for lbl in (labels or [])],
    }


# ---------------------------------------------------------------------------
# _reclaim_issue
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reclaim_issue_removes_in_progress_label() -> None:
    """_reclaim_issue removes STATE_IN_PROGRESS from the issue labels."""
    client = _make_client()
    issue = _make_issue(number=10, labels=[STATE_IN_PROGRESS])

    await _reclaim_issue(client, issue)

    client.remove_label.assert_awaited_once_with(10, STATE_IN_PROGRESS)


@pytest.mark.asyncio
async def test_reclaim_issue_removes_claimed_by_label() -> None:
    """_reclaim_issue removes any 'claimed-by:*' label from the issue."""
    client = _make_client()
    claimed_label = f"{CLAIMED_BY_PREFIX}worker-abc"
    issue = _make_issue(number=7, labels=[claimed_label, STATE_IN_PROGRESS])

    await _reclaim_issue(client, issue)

    removed_labels = {c.args[1] for c in client.remove_label.await_args_list}
    assert claimed_label in removed_labels
    assert STATE_IN_PROGRESS in removed_labels


@pytest.mark.asyncio
async def test_reclaim_issue_adds_state_queued() -> None:
    """_reclaim_issue re-labels the issue as state:queued."""
    client = _make_client()
    issue = _make_issue(number=5, labels=[STATE_IN_PROGRESS])

    await _reclaim_issue(client, issue)

    client.add_labels.assert_awaited_once_with(5, [STATE_QUEUED])


@pytest.mark.asyncio
async def test_reclaim_issue_posts_reclaimed_comment() -> None:
    """_reclaim_issue posts a reclaimed comment to the issue."""
    client = _make_client()
    issue = _make_issue(number=3, labels=[STATE_IN_PROGRESS])

    await _reclaim_issue(client, issue)

    client.create_comment.assert_awaited_once()
    comment_body = client.create_comment.await_args.args[1]
    assert "Reclaimed" in comment_body  # exact wording may vary


@pytest.mark.asyncio
async def test_reclaim_issue_tolerates_remove_label_error() -> None:
    """_reclaim_issue continues even if remove_label raises for one label."""
    client = _make_client()
    client.remove_label = AsyncMock(side_effect=Exception("network error"))
    issue = _make_issue(number=9, labels=[STATE_IN_PROGRESS])

    await _reclaim_issue(client, issue)

    client.add_labels.assert_awaited_once()
    client.create_comment.assert_awaited_once()


@pytest.mark.asyncio
async def test_reclaim_issue_no_labels_to_remove() -> None:
    """_reclaim_issue works correctly when there are no stale labels."""
    client = _make_client()
    issue = _make_issue(number=2, labels=[])

    await _reclaim_issue(client, issue)

    client.remove_label.assert_not_awaited()
    client.add_labels.assert_awaited_once_with(2, [STATE_QUEUED])
