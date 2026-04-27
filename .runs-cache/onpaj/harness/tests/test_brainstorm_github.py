"""Unit tests for the GitHub backend paths in agentharness.brainstorm."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from agentharness.brainstorm import _enqueue_planner_github, _upload_brief_github
from agentharness.models import FeatureStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FEATURE_ID = "feat-my-feature"
_BRIEF_CONTENT = "# Feature Brief: My Feature\n\nDo something cool.\n"
_MAIN_SHA = "abc123def456"


def _make_config(
    token: str = "gh-token",
    owner: str = "test-owner",
    runs_repo: str = "test-repo",
    max_revisions: int = 3,
) -> MagicMock:
    config = MagicMock()
    config.storage_backend = "github"
    config.defaults.max_revisions = max_revisions
    config.defaults.dead_letter_threshold = 3
    config.github.token = token
    config.github.owner = owner
    config.github.runs_repo = runs_repo
    return config


def _make_gh_client() -> MagicMock:
    client = MagicMock()
    for method in (
        "get_ref",
        "create_ref",
        "put_content",
        "create_issue",
        "ensure_label",
        "search_issues",
        "close",
    ):
        setattr(client, method, AsyncMock())
    # get_ref returns the main-branch SHA payload
    client.get_ref.return_value = {"object": {"sha": _MAIN_SHA}}
    # create_issue returns a minimal issue dict
    client.create_issue.return_value = {"number": 42, "labels": []}
    # search_issues returns empty by default (state not found yet)
    client.search_issues.return_value = []
    return client


# ---------------------------------------------------------------------------
# Tests for _upload_brief_github
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_brief_github_calls_in_order() -> None:
    """_upload_brief_github calls get_ref, create_ref, put_content, state.create in order."""
    config = _make_config()
    client = _make_gh_client()

    mock_mgr_instance = MagicMock()
    mock_mgr_instance.create = AsyncMock()

    with (
        patch(
            "agentharness.github_client.GitHubClient.from_config", return_value=client
        ),
        patch(
            "agentharness.github_state.GitHubStateManager",
            return_value=mock_mgr_instance,
        ),
    ):
        await _upload_brief_github(_FEATURE_ID, _BRIEF_CONTENT, config)

    # 1. Fetched main SHA
    client.get_ref.assert_awaited_once_with("heads/main")

    # 2. Created feature branch from main SHA
    client.create_ref.assert_awaited_once_with(
        f"refs/heads/{_FEATURE_ID}", _MAIN_SHA
    )

    # 3. Committed brief.md to the feature branch
    client.put_content.assert_awaited_once()
    put_kwargs = client.put_content.call_args
    assert put_kwargs.kwargs["path"] == f"artifacts/{_FEATURE_ID}/brief.md"
    assert put_kwargs.kwargs["branch"] == _FEATURE_ID
    assert put_kwargs.kwargs["sha"] is None
    # content must be base64-encoded
    import base64
    decoded = base64.b64decode(put_kwargs.kwargs["content"]).decode()
    assert decoded == _BRIEF_CONTENT

    # 4. Created the state issue
    mock_mgr_instance.create.assert_awaited_once()
    created_state = mock_mgr_instance.create.call_args.args[0]
    assert created_state.feature_id == _FEATURE_ID
    assert created_state.status == FeatureStatus.analyzing

    # 5. Client was closed
    client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_upload_brief_github_closes_client_on_error() -> None:
    """_upload_brief_github closes the client even when get_ref raises."""
    config = _make_config()
    client = _make_gh_client()
    client.get_ref.side_effect = RuntimeError("network error")

    with patch(
        "agentharness.github_client.GitHubClient.from_config", return_value=client
    ):
        with pytest.raises(RuntimeError, match="network error"):
            await _upload_brief_github(_FEATURE_ID, _BRIEF_CONTENT, config)

    client.close.assert_awaited_once()


# ---------------------------------------------------------------------------
# Tests for _enqueue_planner_github
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enqueue_planner_github_sends_correct_task() -> None:
    """_enqueue_planner_github sends a TaskMessage with the right task_id and artifacts."""
    config = _make_config()

    mock_queue = MagicMock()
    mock_queue.ensure_exists = AsyncMock()
    mock_queue.send_task = AsyncMock()
    mock_queue.close = AsyncMock()

    with patch(
        "agentharness.storage.create_task_queue", return_value=mock_queue
    ) as mock_create:
        await _enqueue_planner_github(_FEATURE_ID, config)

    # Queue was created for analyst-queue
    mock_create.assert_called_once_with(config, "analyst-queue")

    # ensure_exists called before send_task
    assert mock_queue.ensure_exists.await_count == 1
    assert mock_queue.send_task.await_count == 1

    ensure_exists_order = mock_queue.method_calls.index(call.ensure_exists())
    send_task_order = next(
        i
        for i, c in enumerate(mock_queue.method_calls)
        if c[0] == "send_task"
    )
    assert ensure_exists_order < send_task_order

    # Check the TaskMessage
    task = mock_queue.send_task.call_args.args[0]
    assert task.feature_id == _FEATURE_ID
    assert task.task_id == f"{_FEATURE_ID}-analyst"
    assert task.agent_role == "analyst"
    assert task.input_artifacts == [f"artifacts/{_FEATURE_ID}/brief.md"]
    assert task.output_artifact == f"artifacts/{_FEATURE_ID}/spec.r1.md"

    # Queue was closed
    mock_queue.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_enqueue_planner_github_closes_queue_on_error() -> None:
    """_enqueue_planner_github closes the queue even when ensure_exists raises."""
    config = _make_config()

    mock_queue = MagicMock()
    mock_queue.ensure_exists = AsyncMock(side_effect=RuntimeError("label error"))
    mock_queue.send_task = AsyncMock()
    mock_queue.close = AsyncMock()

    with patch(
        "agentharness.storage.create_task_queue", return_value=mock_queue
    ):
        with pytest.raises(RuntimeError, match="label error"):
            await _enqueue_planner_github(_FEATURE_ID, config)

    mock_queue.close.assert_awaited_once()
