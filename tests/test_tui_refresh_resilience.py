"""Tests that PipelineMonitor._refresh_data survives network failures."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from agentharness.github_client import GitHubApiError


def _make_monitor():
    """Build a PipelineMonitor without a running Textual event loop."""
    from agentharness.tui import PipelineMonitor

    config = MagicMock()
    config.queue_names.return_value = []
    monitor = PipelineMonitor.__new__(PipelineMonitor)
    monitor._config = config
    monitor._states = []
    monitor._refresh_seconds = 2.0
    return monitor


def _wire_monitor(monitor, *, list_features_side_effect, queue_depths=None):
    """Patch create_state_manager and create_task_queue for a single tick."""
    state_mgr = MagicMock()
    state_mgr.list_features = AsyncMock(side_effect=list_features_side_effect)

    status_bar = MagicMock()
    feature_list = MagicMock()
    feature_list.update_features = AsyncMock()
    worker_log = MagicMock()

    def _query_one(widget_type):
        from agentharness.tui import FeatureList, StatusBar, WorkerLogPanel
        if widget_type is StatusBar:
            return status_bar
        if widget_type is FeatureList:
            return feature_list
        if widget_type is WorkerLogPanel:
            return worker_log
        raise RuntimeError(f"unexpected query_one({widget_type})")

    monitor.query_one = _query_one
    monitor._update_detail_panels = MagicMock()

    return state_mgr, status_bar, feature_list


# ---------------------------------------------------------------------------
# Crash prevention: _refresh_data must not propagate exceptions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refresh_survives_github_503() -> None:
    """`_refresh_data` must not raise when GitHub returns 503."""
    monitor = _make_monitor()
    exc = GitHubApiError(503, "unavailable")
    state_mgr, status_bar, _ = _wire_monitor(monitor, list_features_side_effect=exc)

    with patch("agentharness.tui.create_state_manager", return_value=state_mgr), \
         patch("agentharness.tui._load_queue_depths", new=AsyncMock(return_value={})):
        await monitor._refresh_data()  # must not raise

    status_bar.update_time.assert_called_once()
    call_kwargs = status_bar.update_time.call_args.kwargs
    assert "error" in call_kwargs
    assert "503" in call_kwargs["error"]


@pytest.mark.asyncio
async def test_refresh_survives_read_timeout() -> None:
    """`_refresh_data` must not raise on httpx.ReadTimeout."""
    monitor = _make_monitor()
    exc = httpx.ReadTimeout("timeout")
    state_mgr, status_bar, _ = _wire_monitor(monitor, list_features_side_effect=exc)

    with patch("agentharness.tui.create_state_manager", return_value=state_mgr), \
         patch("agentharness.tui._load_queue_depths", new=AsyncMock(return_value={})):
        await monitor._refresh_data()

    call_kwargs = status_bar.update_time.call_args.kwargs
    assert "error" in call_kwargs
    assert call_kwargs["error"]  # non-empty


@pytest.mark.asyncio
async def test_refresh_preserves_stale_state_on_failure() -> None:
    """After a failed tick, the previous `_states` list must be unchanged."""
    from agentharness.models import FeatureState, FeatureStatus
    monitor = _make_monitor()
    prior = [FeatureState(feature_id="feat-x", status=FeatureStatus.done)]
    monitor._states = prior

    exc = GitHubApiError(503, "unavailable")
    state_mgr, status_bar, _ = _wire_monitor(monitor, list_features_side_effect=exc)

    with patch("agentharness.tui.create_state_manager", return_value=state_mgr), \
         patch("agentharness.tui._load_queue_depths", new=AsyncMock(return_value={})):
        await monitor._refresh_data()

    assert monitor._states is prior  # unchanged


@pytest.mark.asyncio
async def test_successful_tick_clears_error() -> None:
    """A healthy tick passes no `error` to the StatusBar."""
    from agentharness.models import FeatureState, FeatureStatus
    monitor = _make_monitor()
    state_mgr, status_bar, feature_list = _wire_monitor(
        monitor,
        list_features_side_effect=[[FeatureState(feature_id="feat-y", status=FeatureStatus.analyzing)]],
    )

    with patch("agentharness.tui.create_state_manager", return_value=state_mgr), \
         patch("agentharness.tui._load_queue_depths", new=AsyncMock(return_value={"analyze-queue": 1})):
        await monitor._refresh_data()

    status_bar.update_time.assert_called_once()
    call_kwargs = status_bar.update_time.call_args.kwargs
    assert call_kwargs.get("error") is None


# ---------------------------------------------------------------------------
# StatusBar.update_time shows error indicator
# ---------------------------------------------------------------------------


def test_status_bar_renders_error_indicator() -> None:
    from agentharness.tui import StatusBar
    bar = StatusBar.__new__(StatusBar)
    rendered: list[str] = []
    bar.update = lambda text: rendered.append(text)

    bar.update_time(error="GitHub 503")

    assert rendered
    assert "503" in rendered[0]
    assert "⚠" in rendered[0]


def test_status_bar_normal_when_no_error() -> None:
    from agentharness.tui import StatusBar
    bar = StatusBar.__new__(StatusBar)
    rendered: list[str] = []
    bar.update = lambda text: rendered.append(text)

    with patch("agentharness.tui._observer_pid", return_value=None):
        bar.update_time(queue_depths={}, refresh_seconds=2.0)

    assert rendered
    assert "⚠" not in rendered[0]
    assert "refresh failed" not in rendered[0]
