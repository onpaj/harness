"""Tests for PipelineMonitor.action_copy_name (y keybinding)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


def _make_monitor():
    from agentharness.tui import PipelineMonitor

    config = MagicMock()
    monitor = PipelineMonitor.__new__(PipelineMonitor)
    monitor._config = config
    monitor._states = []
    monitor._refresh_seconds = 2.0
    return monitor


def _wire_copy(monitor, *, feature_id: str | None, task_id: str | None):
    from agentharness.tui import FeatureList, TaskPanel

    feature_list = MagicMock()
    feature_list.selected_feature_id.return_value = feature_id

    task_panel = MagicMock()
    task_panel.selected_task_id.return_value = task_id

    def _query_one(widget_type):
        if widget_type is FeatureList:
            return feature_list
        if widget_type is TaskPanel:
            return task_panel
        raise RuntimeError(f"unexpected {widget_type}")

    copied: list[str] = []
    monitor.query_one = _query_one
    monitor.copy_to_clipboard = lambda text: copied.append(text)
    monitor.notify = MagicMock()
    return copied


def test_copy_name_copies_feature_id_when_no_task_selected() -> None:
    """y copies the feature_id when no task row is selected."""
    monitor = _make_monitor()
    copied = _wire_copy(monitor, feature_id="feat-20260501-abc123", task_id=None)

    monitor.action_copy_name()

    assert copied == ["feat-20260501-abc123"]
    monitor.notify.assert_called_once()
    assert "feat-20260501-abc123" in monitor.notify.call_args.args[0]


def test_copy_name_copies_task_id_when_dev_task_selected() -> None:
    """y copies the full task_id when a developer task row is selected."""
    monitor = _make_monitor()
    task_id = "feat-20260501-abc123-dev-implement-auth"
    copied = _wire_copy(monitor, feature_id="feat-20260501-abc123", task_id=task_id)

    monitor.action_copy_name()

    assert copied == [task_id]
    monitor.notify.assert_called_once()
    assert "implement-auth" in monitor.notify.call_args.args[0]


def test_copy_name_copies_feature_id_when_phase_row_selected() -> None:
    """y copies the feature_id when a phase row (e.g. 'analyzing') is selected."""
    monitor = _make_monitor()
    copied = _wire_copy(monitor, feature_id="feat-20260501-abc123", task_id="analyzing")

    monitor.action_copy_name()

    assert copied == ["feat-20260501-abc123"]


def test_copy_name_warns_when_no_feature_selected() -> None:
    """y shows a warning notification when no feature is selected."""
    monitor = _make_monitor()
    copied = _wire_copy(monitor, feature_id=None, task_id=None)

    monitor.action_copy_name()

    assert copied == []
    monitor.notify.assert_called_once()
    assert monitor.notify.call_args.kwargs.get("severity") == "warning"
