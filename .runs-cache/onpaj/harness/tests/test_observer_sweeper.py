"""Unit tests for observer stale-claim sweeper functionality."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from agentharness.observer import (
    _parse_heartbeat_timestamp,
    _reclaim_issue,
    _sweep_stale_claims,
)
from agentharness.github_labels import (
    CLAIMED_BY_PREFIX,
    STATE_IN_PROGRESS,
    STATE_QUEUED,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(storage_backend: str = "github") -> MagicMock:
    config = MagicMock()
    config.storage_backend = storage_backend
    return config


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
# _sweep_stale_claims — azure backend is a no-op
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sweep_stale_claims_noop_for_azure() -> None:
    """_sweep_stale_claims returns immediately when storage_backend is not 'github'."""
    config = _make_config(storage_backend="azure")
    # GitHubClient is lazily imported inside the function; patch it on the module it lives in
    with patch("agentharness.github_client.GitHubClient") as mock_cls:
        await _sweep_stale_claims(config)
    # The client constructor must never have been called
    mock_cls.assert_not_called()


# ---------------------------------------------------------------------------
# _parse_heartbeat_timestamp
# ---------------------------------------------------------------------------


def test_parse_heartbeat_timestamp_valid() -> None:
    """Returns a UTC datetime for a well-formed heartbeat line."""
    ts = "2026-04-27T12:34:56"
    issue = _make_issue(body=f"Some text\n⏱ Heartbeat: {ts}\nMore text")
    result = _parse_heartbeat_timestamp(issue)
    assert result is not None
    assert result == datetime(2026, 4, 27, 12, 34, 56, tzinfo=UTC)


def test_parse_heartbeat_timestamp_missing() -> None:
    """Returns None when the issue body contains no heartbeat marker."""
    issue = _make_issue(body="No heartbeat here at all")
    assert _parse_heartbeat_timestamp(issue) is None


def test_parse_heartbeat_timestamp_malformed() -> None:
    """Returns None when the timestamp string cannot be parsed as ISO datetime."""
    issue = _make_issue(body="⏱ Heartbeat: not-a-date")
    assert _parse_heartbeat_timestamp(issue) is None


def test_parse_heartbeat_timestamp_empty_body() -> None:
    """Returns None when body is empty string."""
    issue = _make_issue(body="")
    assert _parse_heartbeat_timestamp(issue) is None


def test_parse_heartbeat_timestamp_none_body() -> None:
    """Returns None when body key is absent from the issue dict."""
    issue = {"number": 1, "labels": []}
    assert _parse_heartbeat_timestamp(issue) is None


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
    assert "Reclaimed" in comment_body


@pytest.mark.asyncio
async def test_reclaim_issue_tolerates_remove_label_error() -> None:
    """_reclaim_issue continues even if remove_label raises for one label."""
    client = _make_client()
    client.remove_label = AsyncMock(side_effect=Exception("network error"))
    issue = _make_issue(number=9, labels=[STATE_IN_PROGRESS])

    # Should not raise; still proceeds to add_labels and create_comment
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
