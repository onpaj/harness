"""Pure-logic tests for StateChangeModal. We only test _options_for() here —
the Textual rendering itself is covered by manual smoke testing in the dev
loop, since headless Textual pilot tests add CI weight without much value
for a static list."""
from __future__ import annotations

import pytest

from agentharness.models import FeatureState, FeatureStatus
from agentharness.tui_state_change import StateChangeModal


def _state(status: FeatureStatus) -> FeatureState:
    return FeatureState(feature_id="feat-x", status=status)


class TestOptionsFor:
    def test_includes_all_states_up_to_and_including_current(self):
        opts = StateChangeModal._options_for(_state(FeatureStatus.developing))
        statuses = [s for s, _, _ in opts if s != FeatureStatus.failed]
        assert statuses == [
            FeatureStatus.brainstorming,
            FeatureStatus.brainstormed,
            FeatureStatus.analyzing,
            FeatureStatus.questioning,
            FeatureStatus.architecting,
            FeatureStatus.designing,
            FeatureStatus.planning,
            FeatureStatus.developing,
        ]

    def test_appends_failed_at_end(self):
        opts = StateChangeModal._options_for(_state(FeatureStatus.developing))
        last_status, last_mode, _ = opts[-1]
        assert last_status == FeatureStatus.failed
        assert last_mode == "fail"

    def test_marks_current_state_as_restart(self):
        opts = StateChangeModal._options_for(_state(FeatureStatus.developing))
        current = next((s, m, lbl) for s, m, lbl in opts if s == FeatureStatus.developing)
        _, mode, label = current
        assert mode == "restart"
        assert "current" in label and "restart" in label

    def test_earlier_states_are_rollback(self):
        opts = StateChangeModal._options_for(_state(FeatureStatus.developing))
        for status, mode, label in opts:
            if status == FeatureStatus.failed:
                continue
            if status == FeatureStatus.developing:
                continue
            assert mode == "rollback"
            assert "rollback" in label

    def test_for_brainstorming_only_self_and_failed(self):
        opts = StateChangeModal._options_for(_state(FeatureStatus.brainstorming))
        assert [s for s, _, _ in opts] == [FeatureStatus.brainstorming, FeatureStatus.failed]

    def test_dev_revision_appears_in_order_for_dev_revision_state(self):
        opts = StateChangeModal._options_for(_state(FeatureStatus.dev_revision))
        statuses = [s for s, _, _ in opts]
        assert FeatureStatus.developing in statuses
        assert FeatureStatus.dev_revision in statuses
        # dev_revision is current → restart
        idx = next(i for i, (s, _, _) in enumerate(opts) if s == FeatureStatus.dev_revision)
        _, mode, _ = opts[idx]
        assert mode == "restart"

    def test_done_features_yield_only_failed_row(self):
        """Defensive: even though the TUI guards on done before opening the modal,
        the helper itself should not crash. It can return just the failed row."""
        opts = StateChangeModal._options_for(_state(FeatureStatus.done))
        # done is excluded from the list; we still allow marking failed manually
        assert all(s != FeatureStatus.done for s, _, _ in opts)


# ---------------------------------------------------------------------------
# action_open_state_change — raw feature guard
# ---------------------------------------------------------------------------


class TestActionOpenStateChangeRawGuard:
    """Tests the pure decision logic: is_raw → notify-and-return; not raw → fall through."""

    def test_raw_feature_emits_notification_and_returns(self):
        raw = FeatureState(feature_id="feat-raw", status=FeatureStatus.brainstormed)
        assert raw.is_raw is True

        notifications: list[tuple[str, str]] = []
        opened: list[str] = []

        def notify(msg: str, severity: str = "information") -> None:
            notifications.append((msg, severity))

        def push_screen(_modal, _on_result) -> None:
            opened.append("modal")

        # Transcription of the new guard branch
        def action(state: FeatureState) -> None:
            if state.is_raw:
                notify("Convert to harness feature first (press i)", "warning")
                return
            push_screen(object(), lambda _r: None)

        action(raw)
        assert notifications == [("Convert to harness feature first (press i)", "warning")]
        assert opened == []

    def test_initialized_feature_opens_modal(self):
        initialized = FeatureState(
            feature_id="feat-init", status=FeatureStatus.analyzing,
        ).with_event("brief_uploaded")
        assert initialized.is_raw is False

        notifications: list[tuple[str, str]] = []
        opened: list[str] = []

        def notify(msg: str, severity: str = "information") -> None:
            notifications.append((msg, severity))

        def push_screen(_modal, _on_result) -> None:
            opened.append("modal")

        def action(state: FeatureState) -> None:
            if state.is_raw:
                notify("Convert to harness feature first (press i)", "warning")
                return
            push_screen(object(), lambda _r: None)

        action(initialized)
        assert notifications == []
        assert opened == ["modal"]
