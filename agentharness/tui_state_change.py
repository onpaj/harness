"""Textual modal for the operator-driven state-change dialog.

UI only: no I/O, no storage imports. Reads everything from the FeatureState
passed to __init__. Triggered by the `S` keybinding in PipelineMonitor.
"""
from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Label, ListItem, ListView

from agentharness.models import FeatureState, FeatureStatus
from agentharness.state_change import StateChangeMode, StateChangeResult


# Canonical pipeline order (excludes terminal `done`; `failed` is appended
# separately as an always-available action).
CANONICAL_STATE_ORDER: list[FeatureStatus] = [
    FeatureStatus.brainstorming,
    FeatureStatus.brainstormed,
    FeatureStatus.analyzing,
    FeatureStatus.architecting,
    FeatureStatus.designing,
    FeatureStatus.planning,
    FeatureStatus.developing,
    FeatureStatus.dev_revision,
    FeatureStatus.reviewing,
]


class StateChangeModal(ModalScreen["StateChangeResult | None"]):
    """Modal listing valid state-change targets for a single feature."""

    CSS = """
    StateChangeModal {
        align: center middle;
    }
    #dialog {
        width: 60;
        height: 22;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }
    #title {
        text-style: bold;
        margin-bottom: 1;
    }
    #footer {
        color: $text-muted;
        margin-top: 1;
    }
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "dismiss(None)", "Cancel"),
    ]

    def __init__(self, feature_state: FeatureState) -> None:
        super().__init__()
        self._feature_state = feature_state
        self._options = self._options_for(feature_state)

    def compose(self) -> ComposeResult:
        with Container(id="dialog"):
            yield Label(
                f"Change State: {self._feature_state.feature_id}\n"
                f"Current state: {self._feature_state.status.value}",
                id="title",
            )
            yield ListView(
                *[ListItem(Label(label)) for _, _, label in self._options],
                id="options",
            )
            yield Label("↑/↓ navigate   Enter confirm   Esc cancel", id="footer")

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        idx = self.query_one("#options", ListView).index
        if idx is None or idx < 0 or idx >= len(self._options):
            return
        target_status, mode, _ = self._options[idx]
        self.dismiss(StateChangeResult(target_status=target_status, mode=mode))

    @staticmethod
    def _options_for(
        state: FeatureState,
    ) -> list[tuple[FeatureStatus, StateChangeMode, str]]:
        """Compute the list of selectable rows for the given feature state.

        Returns [(status, mode, display_label)] where mode is one of
        'restart', 'rollback', 'fail'. The last row is always the
        `failed` action; states later than the current one are excluded.
        """
        current = state.status
        rows: list[tuple[FeatureStatus, StateChangeMode, str]] = []

        if current in CANONICAL_STATE_ORDER:
            current_idx = CANONICAL_STATE_ORDER.index(current)
            for status in CANONICAL_STATE_ORDER[: current_idx + 1]:
                if status == current:
                    label = f"{status.value:<20} (current — restart)"
                    rows.append((status, "restart", label))
                else:
                    label = f"{status.value:<20} (rollback)"
                    rows.append((status, "rollback", label))

        rows.append((
            FeatureStatus.failed,
            "fail",
            f"{'failed':<20} (mark failed)",
        ))
        return rows
