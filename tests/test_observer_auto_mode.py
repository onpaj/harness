"""Unit tests for the observer auto-mode loop."""

from __future__ import annotations

import asyncio
from contextlib import ExitStack
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from agentharness.config import Config
from agentharness.models import FeatureState, FeatureStatus
from agentharness.observer import _auto_mode_loop


def _feature(
    feature_id: str,
    status: FeatureStatus,
    created_at: datetime,
    epic_parent: int | None = None,
    state_issue_number: int | None = None,
) -> FeatureState:
    return FeatureState(
        feature_id=feature_id,
        status=status,
        created_at=created_at,
        epic_parent=epic_parent,
        state_issue_number=state_issue_number,
    )


def _brainstormed(
    feature_id: str,
    year: int = 2024,
    epic_parent: int | None = None,
    state_issue_number: int | None = None,
) -> FeatureState:
    return _feature(feature_id, FeatureStatus.brainstormed, datetime(year, 1, 1), epic_parent, state_issue_number)


def _active(feature_id: str, status: FeatureStatus = FeatureStatus.developing) -> FeatureState:
    return _feature(feature_id, status, datetime(2024, 1, 1))


def _terminal(feature_id: str, done: bool = True) -> FeatureState:
    status = FeatureStatus.done if done else FeatureStatus.failed
    return _feature(feature_id, status, datetime(2024, 1, 1))


def _raw_issue(number: int, title: str, labels: list[str], year: int = 2024) -> dict:
    return {
        "number": number,
        "title": title,
        "body": f"body of issue {number}",
        "created_at": f"{year}-06-01T00:00:00Z",
        "labels": [{"name": lbl} for lbl in labels],
    }


async def _run_one_cycle(
    features: list[FeatureState],
    is_auto_enabled: bool,
    config: Config | None = None,
    raw_issues: list[dict] | None = None,
) -> tuple[AsyncMock, AsyncMock]:
    """Run _auto_mode_loop for exactly one active cycle.

    Returns (mock_enqueue, mock_bootstrap).
    When *raw_issues* is provided a GitHub-backend config is used and
    _collect_raw_candidates / _bootstrap_github_issue are patched.
    """
    if config is None:
        if raw_issues is not None:
            config = Config(storage_backend="github")
        else:
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
    mock_bootstrap = AsyncMock(return_value="feat-auto-bootstrapped")
    mock_client = AsyncMock()
    mock_client.close = AsyncMock()

    all_patches = [
        patch("agentharness.auto_mode.is_enabled", return_value=is_auto_enabled),
        patch("agentharness.storage.create_state_manager", return_value=mock_state_mgr),
        patch("agentharness.brainstorm.enqueue_planner", mock_enqueue),
        patch("asyncio.sleep", side_effect=raise_after_first),
    ]
    if config.storage_backend == "github":
        all_patches += [
            patch("agentharness.github_client.GitHubClient.from_config", return_value=mock_client),
            patch("agentharness.observer._collect_raw_candidates", AsyncMock(return_value=raw_issues or [])),
            patch("agentharness.observer._bootstrap_github_issue", mock_bootstrap),
        ]

    with ExitStack() as stack:
        for p in all_patches:
            stack.enter_context(p)
        with pytest.raises(asyncio.CancelledError):
            await _auto_mode_loop(config)

    return mock_enqueue, mock_bootstrap


class TestAutoModeLoopToggle:
    async def test_does_nothing_when_toggle_is_off(self):
        mock_enqueue, _ = await _run_one_cycle(
            features=[_brainstormed("feat-a")],
            is_auto_enabled=False,
        )
        mock_enqueue.assert_not_called()

    async def test_acts_when_toggle_is_on(self):
        mock_enqueue, _ = await _run_one_cycle(
            features=[_brainstormed("feat-a")],
            is_auto_enabled=True,
        )
        mock_enqueue.assert_called_once()


class TestAutoModeLoopCandidateSelection:
    async def test_starts_oldest_brainstormed_feature(self):
        mock_enqueue, _ = await _run_one_cycle(
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
        mock_enqueue, _ = await _run_one_cycle(
            features=[_brainstormed("epic-child", epic_parent=99)],
            is_auto_enabled=True,
        )
        mock_enqueue.assert_called_once_with("epic-child", Config())

    async def test_oldest_brainstormed_wins_regardless_of_epic_parent(self):
        """Oldest feature by created_at wins, even if it has an epic parent."""
        mock_enqueue, _ = await _run_one_cycle(
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
        mock_enqueue, _ = await _run_one_cycle(
            features=[feature],
            is_auto_enabled=True,
        )
        mock_enqueue.assert_not_called()

    async def test_does_not_start_when_no_candidates(self):
        mock_enqueue, _ = await _run_one_cycle(
            features=[_terminal("done-feat"), _terminal("failed-feat", done=False)],
            is_auto_enabled=True,
        )
        mock_enqueue.assert_not_called()

    async def test_does_not_start_when_no_features(self):
        mock_enqueue, _ = await _run_one_cycle(features=[], is_auto_enabled=True)
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
        mock_enqueue, _ = await _run_one_cycle(
            features=[
                _active("running", status=active_status),
                _brainstormed("waiting"),
            ],
            is_auto_enabled=True,
        )
        mock_enqueue.assert_not_called()

    async def test_starts_when_only_terminal_features_present(self):
        mock_enqueue, _ = await _run_one_cycle(
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


class TestAutoModeLoopRawIssues:
    """Auto-mode bootstraps raw agent-labeled issues on GitHub backend."""

    async def test_bootstraps_and_enqueues_raw_issue(self):
        raw = _raw_issue(42, "Performance slow endpoint", ["agent", "performance"])
        mock_enqueue, mock_bootstrap = await _run_one_cycle(
            features=[],
            is_auto_enabled=True,
            raw_issues=[raw],
        )
        mock_bootstrap.assert_called_once()
        mock_enqueue.assert_called_once()

    async def test_raw_issue_older_than_brainstormed_feature_wins(self):
        """Raw issue created in 2022 should be started before a brainstormed feature from 2024."""
        raw = _raw_issue(99, "Old bug", ["agent"], year=2022)
        mock_enqueue, mock_bootstrap = await _run_one_cycle(
            features=[_brainstormed("newer-feat", year=2024)],
            is_auto_enabled=True,
            raw_issues=[raw],
        )
        mock_bootstrap.assert_called_once()
        # enqueue_planner called with the auto-bootstrapped feature_id
        mock_enqueue.assert_called_once_with("feat-auto-bootstrapped", Config(storage_backend="github"))

    async def test_brainstormed_feature_older_than_raw_issue_wins(self):
        """Brainstormed FeatureState from 2020 wins over raw issue from 2025."""
        raw = _raw_issue(77, "New issue", ["agent"], year=2025)
        mock_enqueue, mock_bootstrap = await _run_one_cycle(
            features=[_brainstormed("old-feat", year=2020)],
            is_auto_enabled=True,
            raw_issues=[raw],
        )
        mock_bootstrap.assert_not_called()
        mock_enqueue.assert_called_once_with("old-feat", Config(storage_backend="github"))

    async def test_raw_issue_not_started_when_feature_is_active(self):
        raw = _raw_issue(55, "Some fix", ["agent"])
        mock_enqueue, mock_bootstrap = await _run_one_cycle(
            features=[_active("running")],
            is_auto_enabled=True,
            raw_issues=[raw],
        )
        mock_bootstrap.assert_not_called()
        mock_enqueue.assert_not_called()

    async def test_no_raw_issues_checked_on_non_github_backend(self):
        """Azure backend: _collect_raw_candidates is never called."""
        mock_enqueue, mock_bootstrap = await _run_one_cycle(
            features=[],
            is_auto_enabled=True,
            config=Config(),  # Azure (default)
        )
        mock_bootstrap.assert_not_called()
        mock_enqueue.assert_not_called()
