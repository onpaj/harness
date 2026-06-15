"""Textual TUI for real-time pipeline monitoring."""

from __future__ import annotations

import logging
from pathlib import Path

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import DataTable, Footer, Header

from agentharness.checkpoint import list_checkpoints
from agentharness.models import Checkpoint

_REFRESH_SECONDS = 2.0

log = logging.getLogger(__name__)


def _load_all_checkpoints(base_dir: Path = Path(".")) -> list[Checkpoint]:
    return list_checkpoints(base_dir)


def _phase_summary(cp: Checkpoint) -> str:
    pipeline_phases = ["analyzing", "architecting", "designing", "planning"]
    completed = sum(1 for name in pipeline_phases if cp.phases.get(name, None) and cp.phases[name].status == "completed")
    total = len(pipeline_phases)
    in_progress = next(
        (name for name in pipeline_phases if cp.phases.get(name) and cp.phases[name].status == "in_progress"),
        None,
    )
    if in_progress:
        return f"{in_progress} ({completed}/{total})"
    if cp.phases.get("developing") and cp.phases["developing"].status == "in_progress":
        task = cp.next_pending_task()
        return f"developing: {task.name if task else '…'}"
    if completed == total and cp.all_tasks_complete():
        return "done"
    return f"{completed}/{total} phases"


def _task_summary(cp: Checkpoint) -> str:
    if not cp.tasks:
        return "—"
    completed = sum(1 for t in cp.tasks if t.status == "completed")
    total = len(cp.tasks)
    return f"{completed}/{total}"


def _overall_status(cp: Checkpoint) -> str:
    if any(p.status == "failed" for p in cp.phases.values()):
        return "failed"
    if any(t.status == "failed" for t in cp.tasks):
        return "failed"
    if cp.all_tasks_complete() and cp.phases.get("developing", None) and cp.phases["developing"].status == "completed":
        return "done"
    if any(p.status == "in_progress" for p in cp.phases.values()):
        return "running"
    if any(t.status == "in_progress" for t in cp.tasks):
        return "running"
    return "pending"


_STATUS_COLORS = {
    "done": "green",
    "failed": "red",
    "running": "yellow",
    "pending": "dim",
}


class PipelineMonitor(App):
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
    ]

    CSS = """
    DataTable { height: 1fr; }
    """

    def compose(self) -> ComposeResult:
        yield Header()
        yield DataTable(id="features")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#features", DataTable)
        table.add_columns("Feature", "Status", "Phase", "Tasks", "Created")
        self._refresh_table()
        self.set_interval(_REFRESH_SECONDS, self._refresh_table)

    def _refresh_table(self) -> None:
        table = self.query_one("#features", DataTable)
        table.clear()
        checkpoints = _load_all_checkpoints()
        for cp in checkpoints:
            status = _overall_status(cp)
            color = _STATUS_COLORS.get(status, "white")
            created_str = cp.created_at.strftime("%Y-%m-%d %H:%M")
            table.add_row(
                cp.feature_id,
                Text(status, style=color),
                _phase_summary(cp),
                _task_summary(cp),
                created_str,
            )

    def action_refresh(self) -> None:
        self._refresh_table()


def run_monitor(config=None) -> None:
    app = PipelineMonitor()
    app.run()
