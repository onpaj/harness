"""Unit tests for the observer auto-mode loop."""

from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentharness.config import Config
from agentharness.models import FeatureState, FeatureStatus
from agentharness.observer import _auto_mode_loop


def _feature(
    feature_id: str,
    status: FeatureStatus,
    created_at: datetime,
    epic_parent: int | None = None,
) -> FeatureState:
    return FeatureState(
        feature_id=feature_id,
        status=status,
        created_at=created_at,
        epic_parent=epic_parent,
    )


def _brainstormed(feature_id: str, year: int = 2024, epic_parent: int | None = None) -> FeatureState:
    return _feature(feature_id, FeatureStatus.brainstormed, datetime(year, 1, 1), epic_parent)


def _active(feature_id: str, status: FeatureStatus = FeatureStatus.developing) -> FeatureState:
    return _feature(feature_id, status, datetime(2024, 1, 1))


def _terminal(feature_id: str, done: bool = True) -> FeatureState:
    status = FeatureStatus.done if done else FeatureStatus.failed
    return _feature(feature_id, status, datetime(2024, 1, 1))


async def _run_one_cycle(
    features: list[FeatureState],
    is_auto_enabled: bool,
    config: Config | None = None,
) -> AsyncMock:
    """Run _auto_mode_loop for exactly one active cycle, return patched enqueue_planner mock."""
    if config is None:
        config = Config()

    mock_state_mgr = AsyncMock()
    mock_state_mgr.list_features = AsyncMock(return_value=features)
    mock_state_mgr.close = AsyncMock()

    sleep_count = 0

    async def raise_after_first(seconds: float) -> None:
        nonlocal sleep_count
        sleep_count += 1
        if sleep_count >= 1:
            raise asyncio.CancelledError

    mock_enqueue = AsyncMock()

    with (
        patch("agentharness.auto_mode.is_enabled", return_value=is_auto_enabled),
        patch("agentharness.storage.create_state_manager", return_value=mock_state_mgr),
        patch("agentharness.brainstorm.enqueue_planner", mock_enqueue),
        patch("asyncio.sleep", side_effect=raise_after_first),
    ):
        with pytest.raises(asyncio.CancelledError):
            await _auto_mode_loop(config)

    return mock_enqueue


class TestAutoModeLoopToggle:
    async def test_does_nothing_when_toggle_is_off(self):
        mock_enqueue = await _run_one_cycle(
            features=[_brainstormed("feat-a")],
            is_auto_enabled=False,
        )
        mock_enqueue.assert_not_called()

    async def test_acts_when_toggle_is_on(self):
        mock_enqueue = await _run_one_cycle(
            features=[_brainstormed("feat-a")],
            is_auto_enabled=True,
        )
        mock_enqueue.assert_called_once()


class TestAutoModeLoopCandidateSelection:
    async def test_starts_oldest_brainstormed_feature(self):
        mock_enqueue = await _run_one_cycle(
            features=[
                _brainstormed("new-feat", year=2025),
                _brainstormed("old-feat", year=2023),
                _brainstormed("mid-feat", year=2024),
            ],
            is_auto_enabled=True,
        )
        mock_enqueue.assert_called_once()
        feature_id = mock_enqueue.call_args.args[0]
        assert feature_id == "old-feat"

    async def test_starts_epic_children(self):
        """Brainstormed epic children are eligible — all brainstormed TUI entries should be startable."""
        mock_enqueue = await _run_one_cycle(
            features=[_brainstormed("epic-child", epic_parent=99)],
            is_auto_enabled=True,
        )
        mock_enqueue.assert_called_once_with("epic-child", Config())

    async def test_oldest_brainstormed_wins_regardless_of_epic_parent(self):
        """Oldest feature by created_at wins, even if it has an epic parent."""
        mock_enqueue = await _run_one_cycle(
            features=[
                _brainstormed("epic-child", year=2023, epic_parent=1),
                _brainstormed("standalone", year=2025),
            ],
            is_auto_enabled=True,
        )
        feature_id = mock_enqueue.call_args.args[0]
        assert feature_id == "epic-child"

    async def test_does_not_start_brainstorming_status(self):
        """Features in 'brainstorming' (brief upload in progress) must be skipped."""
        feature = _feature("in-progress-brief", FeatureStatus.brainstorming, datetime(2020, 1, 1))
        mock_enqueue = await _run_one_cycle(
            features=[feature],
            is_auto_enabled=True,
        )
        mock_enqueue.assert_not_called()

    async def test_does_not_start_when_no_candidates(self):
        mock_enqueue = await _run_one_cycle(
            features=[_terminal("done-feat"), _terminal("failed-feat", done=False)],
            is_auto_enabled=True,
        )
        mock_enqueue.assert_not_called()

    async def test_does_not_start_when_no_features(self):
        mock_enqueue = await _run_one_cycle(features=[], is_auto_enabled=True)
        mock_enqueue.assert_not_called()


class TestAutoModeLoopActiveGate:
    @pytest.mark.parametrize("active_status", [
        FeatureStatus.analyzing,
        FeatureStatus.questioning,
        FeatureStatus.architecting,
        FeatureStatus.designing,
        FeatureStatus.planning,
        FeatureStatus.developing,
        FeatureStatus.reviewing,
        FeatureStatus.dev_revision,
    ])
    async def test_does_not_start_when_another_feature_is_active(self, active_status: FeatureStatus):
        mock_enqueue = await _run_one_cycle(
            features=[
                _active("running", status=active_status),
                _brainstormed("waiting"),
            ],
            is_auto_enabled=True,
        )
        mock_enqueue.assert_not_called()

    async def test_starts_when_only_terminal_features_present(self):
        mock_enqueue = await _run_one_cycle(
            features=[_terminal("done"), _brainstormed("next")],
            is_auto_enabled=True,
        )
        mock_enqueue.assert_called_once_with("next", Config())


class TestAutoModeLoopErrorHandling:
    async def test_continues_on_list_features_error(self):
        config = Config()
        mock_state_mgr = AsyncMock()
        mock_state_mgr.list_features = AsyncMock(side_effect=RuntimeError("API down"))
        mock_state_mgr.close = AsyncMock()

        sleep_count = 0

        async def raise_after_second(seconds: float) -> None:
            nonlocal sleep_count
            sleep_count += 1
            if sleep_count >= 2:
                raise asyncio.CancelledError

        mock_enqueue = AsyncMock()

        with (
            patch("agentharness.auto_mode.is_enabled", return_value=True),
            patch("agentharness.storage.create_state_manager", return_value=mock_state_mgr),
            patch("agentharness.brainstorm.enqueue_planner", mock_enqueue),
            patch("asyncio.sleep", side_effect=raise_after_second),
        ):
            with pytest.raises(asyncio.CancelledError):
                await _auto_mode_loop(config)

        mock_enqueue.assert_not_called()
        assert sleep_count == 2

    async def test_continues_after_enqueue_error(self):
        """If enqueue_planner raises, the loop logs and sleeps rather than crashing."""
        config = Config()
        mock_state_mgr = AsyncMock()
        mock_state_mgr.list_features = AsyncMock(return_value=[_brainstormed("feat-a")])
        mock_state_mgr.close = AsyncMock()

        sleep_count = 0

        async def raise_after_first(seconds: float) -> None:
            nonlocal sleep_count
            sleep_count += 1
            raise asyncio.CancelledError

        with (
            patch("agentharness.auto_mode.is_enabled", return_value=True),
            patch("agentharness.storage.create_state_manager", return_value=mock_state_mgr),
            patch("agentharness.brainstorm.enqueue_planner", AsyncMock(side_effect=RuntimeError("enqueue failed"))),
            patch("asyncio.sleep", side_effect=raise_after_first),
        ):
            with pytest.raises(asyncio.CancelledError):
                await _auto_mode_loop(config)
