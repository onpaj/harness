"""Textual TUI for real-time pipeline monitoring."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import ClassVar

from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import DataTable, Footer, Header, Label, ListItem, ListView, Log, Static

from agentharness.config import Config
from agentharness.models import FeatureState, FeatureStatus, TaskStatus

_REFRESH_SECONDS = 2.0

_STATUS_ICONS = {
    FeatureStatus.done: "✓",
    FeatureStatus.failed: "✗",
    FeatureStatus.developing: "▶",
    FeatureStatus.reviewing: "▶",
    FeatureStatus.dev_revision: "↺",
    FeatureStatus.planning: "◌",
    FeatureStatus.architecting: "◌",
    FeatureStatus.designing: "◌",
    FeatureStatus.brainstorming: "◌",
}

_STATUS_COLORS = {
    FeatureStatus.done: "green",
    FeatureStatus.failed: "red",
    FeatureStatus.developing: "yellow",
    FeatureStatus.reviewing: "yellow",
    FeatureStatus.dev_revision: "magenta",
}

_PHASE_ORDER = ["planning", "architecting", "designing", "developing", "reviewing"]


def _phase_bar(state: FeatureState) -> str:
    filled = sum(
        1 for p in _PHASE_ORDER
        if state.phases.get(p) and state.phases[p].status.value == "completed"
    )
    in_progress = any(
        state.phases.get(p) and state.phases[p].status.value == "in_progress"
        for p in _PHASE_ORDER
    )
    bar = "▶" * filled + ("▷" if in_progress else "") + "□" * (5 - filled - (1 if in_progress else 0))
    return bar[:5]


def _task_summary(state: FeatureState, phase: str = "developing") -> str:
    tasks = state.tasks_for_phase(phase)
    if not tasks:
        return ""
    done = sum(1 for t in tasks if t.status == TaskStatus.completed)
    return f"{done}/{len(tasks)} tasks"


def _fmt_age(dt: datetime | None) -> str:
    if not dt:
        return "—"
    secs = int((datetime.now(UTC) - dt.replace(tzinfo=UTC) if dt.tzinfo is None else datetime.now(UTC) - dt).total_seconds())
    if secs < 60:
        return f"{secs}s ago"
    m = secs // 60
    if m < 60:
        return f"{m}m ago"
    return f"{m // 60}h {m % 60}m ago"


def _task_status_color(status: TaskStatus) -> str:
    return {
        TaskStatus.completed: "green",
        TaskStatus.in_progress: "yellow",
        TaskStatus.failed: "red",
        TaskStatus.queued: "dim",
    }.get(status, "white")


class FeatureList(ListView):
    """List of all features."""

    BORDER_TITLE = "Features"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._feature_ids: list[str] = []

    def update_features(self, states: list[FeatureState]) -> None:
        self._feature_ids = [s.feature_id for s in states]
        self.clear()
        for state in states:
            icon = _STATUS_ICONS.get(state.status, "?")
            bar = _phase_bar(state)
            summary = _task_summary(state) or state.status.value
            color = _STATUS_COLORS.get(state.status, "white")
            label = f"[{color}]{icon}[/]  {state.feature_id[-16:]}  [{color}]{bar}[/]  [dim]{summary}[/dim]"
            self.append(ListItem(Label(label)))

    def selected_feature_id(self) -> str | None:
        idx = self.index
        if idx is not None and 0 <= idx < len(self._feature_ids):
            return self._feature_ids[idx]
        return None


class TaskPanel(DataTable):
    """Tasks for the selected feature."""

    BORDER_TITLE = "Tasks"

    def on_mount(self) -> None:
        self.add_columns("Task", "Status", "Worker", "Rev", "Running")
        self.cursor_type = "row"

    def update_tasks(self, state: FeatureState) -> None:
        self.clear()
        for task in state.tasks:
            color = _task_status_color(task.status)
            duration = ""
            if task.started_at:
                ref = task.completed_at or datetime.now(UTC)
                started = task.started_at.replace(tzinfo=UTC) if task.started_at.tzinfo is None else task.started_at
                secs = int((ref.replace(tzinfo=UTC) if ref.tzinfo is None else ref - started).total_seconds())
                m, s = divmod(secs, 60)
                duration = f"{m}m {s}s"
            self.add_row(
                f"[{color}]{task.task_id.split('-dev-')[-1]}[/]",
                f"[{color}]{task.status.value}[/]",
                task.worker_id or "—",
                str(task.revision),
                duration,
            )


class EventLogPanel(Log):
    """Scrollable event history."""

    BORDER_TITLE = "Event Log"
    MAX_LINES: ClassVar[int] = 200

    def update_events(self, state: FeatureState) -> None:
        self.clear()
        for evt in reversed(state.history[-50:]):
            ts = evt.timestamp.strftime("%H:%M:%S")
            parts = [f"[dim]{ts}[/dim]  [bold]{evt.event}[/bold]"]
            if evt.phase:
                parts.append(f"[blue]{evt.phase}[/blue]")
            if evt.task_id:
                parts.append(f"[cyan]{evt.task_id.split('-dev-')[-1]}[/cyan]")
            if evt.worker_id:
                parts.append(f"[dim]{evt.worker_id}[/dim]")
            if evt.details:
                parts.append(f"[dim italic]{evt.details}[/dim italic]")
            self.write_line("  ".join(parts))


_LOG_DIR = Path("logs")
_LOG_TAIL_LINES = 150
_MAX_ACTIVE_LOGS = 6   # most recently modified log files to show


class WorkerLogPanel(Log):
    """Live tail of active task log files (logs/{queue}/{task_id}.log)."""

    BORDER_TITLE = "Worker Logs"
    MAX_LINES: ClassVar[int] = 500

    def refresh_logs(self) -> None:
        if not _LOG_DIR.exists():
            return

        # Collect all log files (observer + per-task), sorted by mtime desc
        all_logs = sorted(
            _LOG_DIR.rglob("*.log"),
            key=lambda p: p.stat().st_mtime if p.exists() else 0,
            reverse=True,
        )
        active_logs = all_logs[:_MAX_ACTIVE_LOGS]

        lines: list[tuple[float, str, str]] = []
        for log_file in active_logs:
            # label = queue/task_id or "observer"
            parts = log_file.relative_to(_LOG_DIR).parts
            label = "/".join(parts[:-1]) if len(parts) > 1 else log_file.stem
            try:
                text = log_file.read_text()
            except OSError:
                continue
            for line in text.splitlines()[-_LOG_TAIL_LINES:]:
                ts = line[:8] if len(line) >= 8 and line[2] == ":" else "00:00:00"
                lines.append((ts, label, line))

        lines.sort(key=lambda t: t[0])

        self.clear()
        for _, label, line in lines[-_LOG_TAIL_LINES:]:
            self.write_line(f"[dim cyan]{label}[/dim cyan]  {line}")


class StatusBar(Static):
    """Bottom status line with last-refresh time and queue depths."""

    def update_time(self, queue_depths: dict[str, int] | None = None) -> None:
        now = datetime.now(UTC).strftime("%H:%M:%S UTC")
        if queue_depths:
            active = {q: n for q, n in queue_depths.items() if n > 0}
            queue_str = "  ".join(f"[yellow]{q.replace('-queue','')}:{n}[/yellow]" for q, n in active.items())
            queues_part = f"  |  queues: {queue_str}" if active else "  |  [dim]all queues idle[/dim]"
        else:
            queues_part = ""
        self.update(f"[dim]Last refresh: {now}  |  Refreshing every {_REFRESH_SECONDS:.0f}s{queues_part}  |  q: quit  |  r: refresh[/dim]")


class PipelineMonitor(App):
    """Real-time Textual TUI for AgentHarness pipeline monitoring."""

    CSS = """
    Screen {
        layout: vertical;
    }
    #main-row {
        layout: horizontal;
        height: 1fr;
    }
    FeatureList {
        width: 36;
        border: round $primary;
    }
    #right-col {
        width: 1fr;
        layout: vertical;
    }
    TaskPanel {
        height: 25%;
        border: round $primary;
    }
    EventLogPanel {
        height: 25%;
        border: round $primary;
    }
    WorkerLogPanel {
        height: 1fr;
        border: round $accent;
    }
    StatusBar {
        height: 1;
        background: $surface;
        padding: 0 1;
    }
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh now"),
        Binding("l", "open_log", "Open log in less"),
    ]

    TITLE = "AgentHarness Pipeline Monitor"

    def __init__(self, config: Config) -> None:
        super().__init__()
        self._config = config
        self._states: list[FeatureState] = []

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main-row"):
            yield FeatureList(id="feature-list")
            with Vertical(id="right-col"):
                yield TaskPanel(id="task-panel")
                yield EventLogPanel(id="event-log")
                yield WorkerLogPanel(id="worker-log")
        yield StatusBar(id="status-bar")
        yield Footer()

    def on_mount(self) -> None:
        self.set_interval(_REFRESH_SECONDS, self._refresh_data)
        self.call_after_refresh(self._refresh_data)

    async def _refresh_data(self) -> None:
        states, queue_depths = await asyncio.gather(
            _load_all_states(self._config),
            _load_queue_depths(self._config),
        )
        self._states = states
        feature_list = self.query_one(FeatureList)
        feature_list.update_features(states)
        self.query_one(StatusBar).update_time(queue_depths)
        self.query_one(WorkerLogPanel).refresh_logs()
        self._update_detail_panels()

    def _update_detail_panels(self) -> None:
        feature_list = self.query_one(FeatureList)
        selected_id = feature_list.selected_feature_id()
        if not selected_id:
            return
        state = next((s for s in self._states if s.feature_id == selected_id), None)
        if not state:
            return
        self.query_one(TaskPanel).update_tasks(state)
        self.query_one(EventLogPanel).update_events(state)

    def on_list_view_selected(self) -> None:
        self._update_detail_panels()

    def action_refresh(self) -> None:
        self.call_after_refresh(self._refresh_data)

    async def action_open_log(self) -> None:
        import subprocess
        if not _LOG_DIR.exists():
            return
        log_files = sorted(
            _LOG_DIR.rglob("*.log"),
            key=lambda p: p.stat().st_mtime if p.exists() else 0,
            reverse=True,
        )
        if not log_files:
            return
        with self.suspend():
            subprocess.run(["less", "+G", str(log_files[0])])


async def _load_all_states(config: Config) -> list[FeatureState]:
    from azure.storage.blob.aio import BlobServiceClient
    from agentharness.state_manager import StateManager

    conn_str = config.storage.connection_string
    blob_service = BlobServiceClient.from_connection_string(conn_str)
    container = blob_service.get_container_client(config.storage.container)
    mgr = StateManager(blob_service, config.storage.container)

    states: list[FeatureState] = []
    try:
        async for blob in container.list_blobs(name_starts_with="artifacts/"):
            if blob.name.endswith("/state.json"):
                feature_id = blob.name.split("/")[1]
                try:
                    state = await mgr.get(feature_id)
                    states.append(state)
                except Exception:
                    pass
    finally:
        await blob_service.close()

    # Sort: active first, then by updated_at desc
    def sort_key(s: FeatureState):
        active = s.status not in (FeatureStatus.done, FeatureStatus.failed)
        return (not active, -(s.updated_at.timestamp() if s.updated_at else 0))

    return sorted(states, key=sort_key)


async def _load_queue_depths(config: Config) -> dict[str, int]:
    from agentharness.storage import PipelineQueue

    conn_str = config.storage.connection_string
    depths: dict[str, int] = {}
    for queue_name in config.queue_names():
        try:
            q = PipelineQueue.from_connection_string(conn_str, queue_name)
            props = await q._client.get_queue_properties()
            depths[queue_name] = props.get("approximate_message_count", 0)
            await q.close()
        except Exception:
            depths[queue_name] = 0
    return depths


def run_monitor(config: Config) -> None:
    app = PipelineMonitor(config)
    app.run()
