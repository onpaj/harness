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
