"""Unit tests for agentharness.github_queue."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentharness.github_queue import (
    GitHubTaskQueue,
    _build_issue_body,
)

# _parse_task_from_body was moved to GitHubTaskQueue as a @staticmethod
_parse_task_from_body = GitHubTaskQueue._parse_task_from_body
from agentharness.github_labels import (
    FEATURE_MARKER,
    STATE_BLOCKED,
    STATE_COMPLETED,
    STATE_DEAD_LETTER,
    STATE_IN_PROGRESS,
    STATE_QUEUED,
)
from agentharness.models import TaskMessage
from agentharness.storage_protocol import RawMessage

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_QUEUE_NAME = "analyst-queue"
_WORKER_ID = "test-host-1234"
_QUEUE_LABEL = "queue:analyst"


def _make_task(task_id: str = "task-001") -> TaskMessage:
    return TaskMessage(
        feature_id="feat-20260427-abc123",
        task_id=task_id,
        input_artifacts=["artifacts/feat-20260427-abc123/brief.md"],
        output_artifact="artifacts/feat-20260427-abc123/spec.r1.md",
        agent_role="analyst",
    )


def _make_client() -> MagicMock:
    client = MagicMock()
    client.owner = "test-owner"
    client.repo = "test-repo"
    # Wire async methods as AsyncMocks
    for method in (
        "create_issue",
        "get_issue",
        "update_issue",
        "add_labels",
        "remove_label",
        "create_comment",
        "update_comment",
        "search_issues",
        "ensure_label",
        "ensure_labels",
        "close",
    ):
        setattr(client, method, AsyncMock())
    return client


def _make_queue(client: MagicMock | None = None) -> GitHubTaskQueue:
    return GitHubTaskQueue(
        client=client or _make_client(),
        queue_name=_QUEUE_NAME,
        worker_id=_WORKER_ID,
    )


# ---------------------------------------------------------------------------
# Helper round-trip
# ---------------------------------------------------------------------------


def test_build_and_parse_issue_body_round_trips() -> None:
    task = _make_task()
    body = _build_issue_body(task)
    recovered = _parse_task_from_body(body)
    assert recovered == task


def test_parse_task_from_body_raises_on_missing_fence() -> None:
    with pytest.raises(ValueError, match="agentharness-task"):
        _parse_task_from_body("no fence here")


# ---------------------------------------------------------------------------
# send_task
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_task_creates_issue_with_correct_labels() -> None:
    client = _make_client()
    client.create_issue.return_value = {"number": 42, "html_url": "https://github.com/x"}
    queue = _make_queue(client)
    task = _make_task()

    await queue.send_task(task)

    client.create_issue.assert_called_once()
    _, kwargs = client.create_issue.call_args
    assert kwargs["title"] == f"[{_QUEUE_NAME}] {task.task_id}"
    assert set(kwargs["labels"]) == {_QUEUE_LABEL, STATE_QUEUED, FEATURE_MARKER}
    assert "agentharness-task" in kwargs["body"]


@pytest.mark.asyncio
async def test_send_task_uses_state_blocked_when_visibility_timeout_set() -> None:
    client = _make_client()
    client.create_issue.return_value = {"number": 43}
    queue = _make_queue(client)
    task = _make_task()

    await queue.send_task(task, visibility_timeout=30)

    _, kwargs = client.create_issue.call_args
    labels = set(kwargs["labels"])
    assert STATE_BLOCKED in labels
    assert STATE_QUEUED not in labels


# ---------------------------------------------------------------------------
# receive_task — empty queue
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_receive_task_returns_none_when_no_issues() -> None:
    client = _make_client()
    client.search_issues.return_value = []
    queue = _make_queue(client)

    result = await queue.receive_task()

    assert result is None
    client.add_labels.assert_not_called()
    client.create_comment.assert_not_called()


# ---------------------------------------------------------------------------
# receive_task — successful claim
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_receive_task_claims_issue_and_returns_task_and_raw() -> None:
    task = _make_task()
    body = _build_issue_body(task)

    client = _make_client()
    client.search_issues.return_value = [
        {
            "number": 7,
            "body": body,
            "labels": [{"name": STATE_QUEUED}, {"name": _QUEUE_LABEL}],
        }
    ]

    queue = _make_queue(client)
    result = await queue.receive_task()

    assert result is not None
    returned_task, raw = result

    # Correct task parsed
    assert returned_task == task

    # RawMessage populated correctly
    assert raw.id == "7"
    assert raw.pop_receipt == ""
    assert raw.dequeue_count == 0

    # Labels transitioned correctly
    client.remove_label.assert_called_once_with(7, STATE_QUEUED)
    add_call_labels = client.add_labels.call_args[0][1]
    assert STATE_IN_PROGRESS in add_call_labels
    assert any(lbl.startswith("claimed-by:") for lbl in add_call_labels)


# ---------------------------------------------------------------------------
# extend_visibility
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extend_visibility_is_noop() -> None:
    client = _make_client()
    queue = _make_queue(client)
    raw = RawMessage(id="7", pop_receipt="", content="body")

    returned_raw = await queue.extend_visibility(raw, timeout=60)

    client.update_comment.assert_not_called()
    assert returned_raw is raw


# ---------------------------------------------------------------------------
# delete_message
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_message_removes_in_progress_and_closes_issue() -> None:
    client = _make_client()
    client.get_issue.return_value = {
        "number": 7,
        "labels": [
            {"name": STATE_IN_PROGRESS},
            {"name": "claimed-by:test-host-1234"},
            {"name": _QUEUE_LABEL},
        ],
    }
    queue = _make_queue(client)
    raw = RawMessage(id="7", pop_receipt="999", content="body")

    await queue.delete_message(raw)

    # in-progress and claimed-by labels removed
    removed = {call[0][1] for call in client.remove_label.call_args_list}
    assert STATE_IN_PROGRESS in removed
    assert "claimed-by:test-host-1234" in removed
    assert _QUEUE_LABEL not in removed

    # completed label added
    added_labels = client.add_labels.call_args[0][1]
    assert STATE_COMPLETED in added_labels

    # issue closed
    client.update_issue.assert_called_once_with(7, state="closed")


# ---------------------------------------------------------------------------
# move_to_dead_letter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_move_to_dead_letter_adds_dead_letter_label_and_closes() -> None:
    client = _make_client()
    client.get_issue.return_value = {
        "number": 7,
        "labels": [
            {"name": STATE_IN_PROGRESS},
            {"name": "claimed-by:worker-5678"},
        ],
    }
    queue = _make_queue(client)
    raw = RawMessage(id="7", pop_receipt="999", content="body")

    await queue.move_to_dead_letter(raw, "dead-letter-queue")

    added_labels = client.add_labels.call_args[0][1]
    assert STATE_DEAD_LETTER in added_labels

    # dead-letter comment posted
    client.create_comment.assert_called_once()
    assert "Dead-lettered" in client.create_comment.call_args[0][1]

    client.update_issue.assert_called_once_with(7, state="closed")


# ---------------------------------------------------------------------------
# purge
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_purge_closes_all_open_issues() -> None:
    client = _make_client()
    client.search_issues.return_value = [
        {"number": 1},
        {"number": 2},
        {"number": 3},
    ]
    queue = _make_queue(client)

    await queue.purge()

    assert client.update_issue.call_count == 3
    closed_numbers = {call[0][0] for call in client.update_issue.call_args_list}
    assert closed_numbers == {1, 2, 3}


@pytest.mark.asyncio
async def test_purge_does_nothing_when_no_open_issues() -> None:
    client = _make_client()
    client.search_issues.return_value = []
    queue = _make_queue(client)

    await queue.purge()

    client.update_issue.assert_not_called()


# ---------------------------------------------------------------------------
# get_depth
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_depth_returns_count_of_queued_issues() -> None:
    client = _make_client()
    client.search_issues.return_value = [
        {"number": 1},
        {"number": 2},
    ]
    queue = _make_queue(client)

    depth = await queue.get_depth()

    assert depth == 2
    query_arg: str = client.search_issues.call_args[0][0]
    assert STATE_QUEUED in query_arg
    assert _QUEUE_LABEL in query_arg


@pytest.mark.asyncio
async def test_get_depth_returns_zero_when_empty() -> None:
    client = _make_client()
    client.search_issues.return_value = []
    queue = _make_queue(client)

    depth = await queue.get_depth()

    assert depth == 0


# ---------------------------------------------------------------------------
# ensure_exists
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ensure_exists_calls_ensure_labels_with_all_required_labels() -> None:
    client = _make_client()
    queue = _make_queue(client)

    await queue.ensure_exists()

    client.ensure_labels.assert_called_once()
    called_labels = set(client.ensure_labels.call_args[0][0])
    expected = {
        _QUEUE_LABEL,
        STATE_QUEUED,
        STATE_IN_PROGRESS,
        STATE_COMPLETED,
        STATE_DEAD_LETTER,
        STATE_BLOCKED,
        FEATURE_MARKER,
    }
    assert expected.issubset(called_labels)


# ---------------------------------------------------------------------------
# close
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_delegates_to_client() -> None:
    client = _make_client()
    queue = _make_queue(client)

    await queue.close()

    client.close.assert_called_once()
