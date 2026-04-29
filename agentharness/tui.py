"""Textual TUI for real-time pipeline monitoring."""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
from datetime import UTC, datetime
from typing import ClassVar

from pathlib import Path

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.coordinate import Coordinate
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Header, Label, ListItem, ListView, RichLog, Static

from agentharness.config import Config
from agentharness.dispatcher import STATE_TO_QUEUE
from agentharness.models import FeatureState, FeatureStatus, TaskStatus, TokenUsage
from agentharness.state_change import (
    StateChangeError,
    StateChangeResult,
    apply_state_change,
)
from agentharness.storage import create_state_manager, create_task_queue
from agentharness.tui_state_change import StateChangeModal

_REFRESH_SECONDS = 2.0

_STATUS_ICONS = {
    FeatureStatus.done: "✓",
    FeatureStatus.failed: "✗",
    FeatureStatus.developing: "▶",
    FeatureStatus.reviewing: "▶",
    FeatureStatus.dev_revision: "↺",
    FeatureStatus.analyzing: "◌",
    FeatureStatus.questioning: "◌",
    FeatureStatus.planning: "◌",
    FeatureStatus.architecting: "◌",
    FeatureStatus.designing: "◌",
    FeatureStatus.brainstorming: "◌",
    FeatureStatus.brainstormed: "◎",
}

_STATUS_COLORS = {
    FeatureStatus.done: "green",
    FeatureStatus.failed: "red",
    FeatureStatus.developing: "yellow",
    FeatureStatus.reviewing: "yellow",
    FeatureStatus.dev_revision: "magenta",
    FeatureStatus.questioning: "cyan",
}

_PHASE_ORDER = ["analyzing", "questioning", "architecting", "designing", "planning", "developing", "reviewing"]

_PHASE_TO_QUEUE = {
    status.value: queue
    for status, queue in STATE_TO_QUEUE.items()
    if queue is not None and status.value in {
        "analyzing", "questioning", "architecting", "designing",
        "planning", "developing", "reviewing",
    }
}

_OBSERVER_PID_FILE = Path("logs/observer.pid")

_GITHUB_CALL_PATTERNS = ("api.github.com", "mcp__github__", "X-GitHub-Api-Version")


def _is_github_call_line(line: str) -> bool:
    return any(p in line for p in _GITHUB_CALL_PATTERNS)


def _observer_pid() -> int | None:
    if not _OBSERVER_PID_FILE.exists():
        return None
    try:
        pid = int(_OBSERVER_PID_FILE.read_text().strip())
        os.kill(pid, 0)
        return pid
    except (ValueError, ProcessLookupError, PermissionError):
        _OBSERVER_PID_FILE.unlink(missing_ok=True)
        return None


def _start_observer() -> int:
    exe = str(Path(sys.executable).parent / "agentharness")
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    fh = open(log_dir / "observer.log", "a")
    proc = subprocess.Popen(
        [exe, "_observe"],
        stdout=fh,
        stderr=fh,
        start_new_session=True,
    )
    _OBSERVER_PID_FILE.write_text(str(proc.pid))
    return proc.pid


def _stop_observer(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    _OBSERVER_PID_FILE.unlink(missing_ok=True)


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


def _fmt_duration(started_at: datetime | None, completed_at: datetime | None = None) -> str:
    if not started_at:
        return ""
    ref = completed_at or datetime.now(UTC)
    started = started_at.replace(tzinfo=UTC) if started_at.tzinfo is None else started_at
    ref = ref.replace(tzinfo=UTC) if ref.tzinfo is None else ref
    secs = int((ref - started).total_seconds())
    m, s = divmod(secs, 60)
    return f"{m}m {s}s"


def _fmt_num(n: int) -> str:
    return f"{n // 1000}k" if n >= 1000 else str(n)


def _fmt_tokens(tokens: TokenUsage | None) -> str:
    if not tokens or tokens.total == 0:
        return "—"
    return f"↑{_fmt_num(tokens.input_tokens)} ↓{_fmt_num(tokens.output_tokens)}"


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

    async def update_features(self, states: list[FeatureState]) -> None:
        new_ids = [s.feature_id for s in states]
        if new_ids == self._feature_ids:
            for list_item, state in zip(self.query(ListItem), states):
                list_item.query_one(Label).update(self._feature_label(state))
            return
        prev_id = self.selected_feature_id()
        self._feature_ids = new_ids
        await self.clear()
        if states:
            await self.extend([ListItem(Label(self._feature_label(s))) for s in states])
        if prev_id and prev_id in self._feature_ids:
            self.index = self._feature_ids.index(prev_id)

    @staticmethod
    def _feature_label(state: FeatureState) -> str:
        icon = _STATUS_ICONS.get(state.status, "?")
        bar = _phase_bar(state)
        summary = _task_summary(state) or state.status.value
        color = _STATUS_COLORS.get(state.status, "white")
        short_id = state.feature_id.removeprefix("feat-")
        total = _fmt_tokens(state.total_tokens_used())
        token_part = f"  [dim cyan]{total}[/dim cyan]" if total != "—" else ""
        return f"[{color}]{icon}[/]  {short_id}  [{color}]{bar}[/]  [dim]{summary}[/dim]{token_part}"

    def selected_feature_id(self) -> str | None:
        idx = self.index
        if idx is not None and 0 <= idx < len(self._feature_ids):
            return self._feature_ids[idx]
        return None


class TaskPanel(DataTable):
    """Tasks for the selected feature."""

    BORDER_TITLE = "Tasks"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._row_task_ids: list[str] = []

    def on_mount(self) -> None:
        self.add_columns("Task", "Status", "Agent", "Rev", "Running", "Tokens")
        self.cursor_type = "row"

    def update_tasks(self, state: FeatureState) -> None:
        total = _fmt_tokens(state.total_tokens_used())
        title = f"Tasks  —  total: {total}" if total != "—" else "Tasks"
        cfg = state.config
        if cfg.current_analyst_iteration > 0:
            cap_note = " (cap)" if cfg.current_analyst_iteration >= cfg.max_analyst_iterations else ""
            title = f"{title}  —  analyst: {cfg.current_analyst_iteration} / {cfg.max_analyst_iterations}{cap_note}"
        self.border_title = title
        new_rows, new_ids = self._build_task_rows(state)
        if new_ids == self._row_task_ids:
            for row_idx, row_data in enumerate(new_rows):
                for col_idx, cell_value in enumerate(row_data):
                    self.update_cell_at(Coordinate(row_idx, col_idx), cell_value)
            return
        prev_task_id = self.selected_task_id()
        self._row_task_ids = new_ids
        self.clear()
        for row_data in new_rows:
            self.add_row(*row_data)
        if prev_task_id and prev_task_id in self._row_task_ids:
            self.move_cursor(row=self._row_task_ids.index(prev_task_id))

    def _build_task_rows(self, state: FeatureState) -> tuple[list[tuple], list[str]]:
        _phase_colors = {"completed": "green", "in_progress": "yellow", "failed": "red", "pending": "dim"}
        rows: list[tuple] = []
        ids: list[str] = []
        for phase in _PHASE_ORDER:
            info = state.phases.get(phase)
            if not info:
                continue
            color = _phase_colors.get(info.status.value, "dim")
            phase_tasks = state.tasks_for_phase(phase)
            phase_tokens = (
                sum((t.tokens_used for t in phase_tasks if t.tokens_used), TokenUsage())
                if phase_tasks
                else info.tokens_used
            )
            rows.append((
                f"[{color}]{phase}[/]",
                f"[{color}]{info.status.value}[/]",
                info.agent or "—",
                str(info.revision),
                _fmt_duration(info.started_at, info.completed_at),
                _fmt_tokens(phase_tokens),
            ))
            ids.append(phase)
        for task in state.tasks:
            color = _task_status_color(task.status)
            rows.append((
                f"[{color}]{task.task_id.split('-dev-')[-1]}[/]",
                f"[{color}]{task.status.value}[/]",
                task.worker_id or "—",
                str(task.revision),
                _fmt_duration(task.started_at, task.completed_at),
                _fmt_tokens(task.tokens_used),
            ))
            ids.append(task.task_id)
        return rows, ids

    def selected_task_id(self) -> str | None:
        idx = self.cursor_row
        if 0 <= idx < len(self._row_task_ids):
            return self._row_task_ids[idx]
        return None


class EventLogPanel(RichLog):
    """Scrollable event history."""

    BORDER_TITLE = "Event Log"
    MAX_LINES: ClassVar[int] = 200

    def update_events(self, state: FeatureState) -> None:
        self.clear()
        for evt in state.history[-50:]:
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
            self.write(Text.from_markup("  ".join(parts)))
        self.scroll_end(animate=False)


_LOG_DIR = Path("logs")
_LOG_TAIL_LINES = 150
_MAX_ACTIVE_LOGS = 6   # most recently modified log files to show


class TaskLogPanel(RichLog):
    """Realtime log for the selected feature's task log files."""

    BORDER_TITLE = "Task Log"
    MAX_LINES: ClassVar[int] = 500

    def update_for_task(self, state: FeatureState | None, task_id: str | None) -> None:
        if not state or not task_id:
            self.clear()
            self.border_title = "Task Log"
            return

        short = task_id.split("-dev-")[-1]
        self.border_title = f"Task Log  [{short}]"
        self.clear()

        task_entry = next((t for t in state.tasks if t.task_id == task_id), None)
        if task_entry and task_entry.log_file:
            log_path = Path(task_entry.log_file)
            if log_path.exists():
                try:
                    raw_lines = log_path.read_text().splitlines()[-_LOG_TAIL_LINES:]
                    for line in raw_lines:
                        if _is_github_call_line(line):
                            continue
                        self.write(Text.from_markup(f"[dim green]{log_path.stem}[/dim green]  {line}"))
                    self.scroll_end(animate=False)
                except OSError:
                    self.write(Text.from_markup(f"[dim red]Cannot read: {task_entry.log_file}[/dim red]"))
            else:
                self.write(Text.from_markup(f"[dim]No log yet for {short}[/dim]"))
            return

        # Fallback: scan log dir by task_id stem match or queue directory
        if not _LOG_DIR.exists():
            self.write(Text.from_markup("[dim]No logs directory[/dim]"))
            return
        lines: list[tuple[str, str, str]] = []
        queue_dir = _LOG_DIR / _PHASE_TO_QUEUE.get(task_id, "")
        for lf in _LOG_DIR.rglob("*.log"):
            # Phase rows: match by queue directory; task rows: match by stem
            in_queue_dir = queue_dir.name and lf.parent == queue_dir
            if not in_queue_dir and task_id not in lf.stem:
                continue
            label = lf.stem
            try:
                text = lf.read_text()
            except OSError:
                continue
            for line in text.splitlines()[-_LOG_TAIL_LINES:]:
                if _is_github_call_line(line):
                    continue
                ts = line[:8] if len(line) >= 8 and line[2] == ":" else "00:00:00"
                lines.append((ts, label, line))
        if not lines:
            self.write(Text.from_markup(f"[dim]No log found for {short}[/dim]"))
            return
        lines.sort(key=lambda t: t[0])
        for _, label, line in lines[-_LOG_TAIL_LINES:]:
            self.write(Text.from_markup(f"[dim green]{label}[/dim green]  {line}"))
        self.scroll_end(animate=False)


class WorkerLogPanel(RichLog):
    """Live tail of active task log files (logs/{queue}/{task_id}.log)."""

    BORDER_TITLE = "Worker Logs"
    MAX_LINES: ClassVar[int] = 500

    def refresh_logs(self) -> None:
        if not _LOG_DIR.exists():
            return

        all_logs = sorted(
            _LOG_DIR.rglob("*.log"),
            key=lambda p: p.stat().st_mtime if p.exists() else 0,
            reverse=True,
        )
        active_logs = all_logs[:_MAX_ACTIVE_LOGS]

        lines: list[tuple[str, str, str]] = []
        for log_file in active_logs:
            parts = log_file.relative_to(_LOG_DIR).parts
            label = "/".join(parts[:-1]) if len(parts) > 1 else log_file.stem
            try:
                text = log_file.read_text()
            except OSError:
                continue
            for line in text.splitlines()[-_LOG_TAIL_LINES:]:
                if _is_github_call_line(line):
                    continue
                ts = line[:8] if len(line) >= 8 and line[2] == ":" else "00:00:00"
                lines.append((ts, label, line))

        lines.sort(key=lambda t: t[0])

        self.clear()
        for _, label, line in lines[-_LOG_TAIL_LINES:]:
            self.write(Text.from_markup(f"[dim cyan]{label}[/dim cyan]  {line}"))
        self.scroll_end(animate=False)


class ConfirmScreen(ModalScreen[bool]):
    """Modal confirmation dialog."""

    CSS = """
    ConfirmScreen {
        align: center middle;
    }
    #dialog {
        width: 50;
        height: 9;
        border: thick $error;
        background: $surface;
        padding: 1 2;
    }
    #buttons {
        layout: horizontal;
        align: center middle;
        margin-top: 1;
    }
    Button {
        margin: 0 1;
    }
    """

    def __init__(self, message: str) -> None:
        super().__init__()
        self._message = message

    def compose(self) -> ComposeResult:
        from textual.containers import Container
        with Container(id="dialog"):
            yield Label(self._message)
            with Horizontal(id="buttons"):
                yield Button("Confirm", variant="error", id="confirm")
                yield Button("Cancel", variant="default", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm")


class StatusBar(Static):
    """Bottom status line with last-refresh time and queue depths."""

    def update_time(self, queue_depths: dict[str, int] | None = None, refresh_seconds: float = _REFRESH_SECONDS) -> None:
        now = datetime.now(UTC).strftime("%H:%M:%S UTC")
        if queue_depths:
            active = {q: n for q, n in queue_depths.items() if n > 0}
            queue_str = "  ".join(f"[yellow]{q.replace('-queue','')}:{n}[/yellow]" for q, n in active.items())
            queues_part = f"  |  queues: {queue_str}" if active else "  |  [dim]all queues idle[/dim]"
        else:
            queues_part = ""
        pid = _observer_pid()
        observer_part = f"  |  [green]observer pid:{pid}[/green]" if pid else "  |  [red]observer off[/red]"
        self.update(f"[dim]Last refresh: {now}  |  Refreshing every {refresh_seconds:.0f}s{queues_part}{observer_part}[/dim]")


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
        width: 81;
        border: round $primary;
    }
    #right-col {
        width: 1fr;
        layout: vertical;
    }
    TaskPanel {
        height: 20%;
        border: round $primary;
    }
    EventLogPanel {
        height: 20%;
        border: round $primary;
    }
    TaskLogPanel {
        height: 1fr;
        border: round $success;
    }
    WorkerLogPanel {
        height: 15%;
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
        Binding("c", "clear_logs", "Clear worker logs"),
        Binding("p", "purge_queues", "Purge all queues"),
        Binding("i", "implement", "Implement selected feature"),
        Binding("o", "toggle_observer", "Observer on/off"),
        Binding("k", "kill_task", "Kill selected task"),
        Binding("t", "resume_task", "Resume selected task"),
        Binding("s", "open_state_change", "Change state"),
    ]

    TITLE = "AgentHarness Pipeline Monitor"

    def __init__(self, config: Config) -> None:
        super().__init__()
        self._config = config
        self._states: list[FeatureState] = []
        self._refresh_seconds = _REFRESH_SECONDS

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main-row"):
            yield FeatureList(id="feature-list")
            with Vertical(id="right-col"):
                yield TaskPanel(id="task-panel")
                yield EventLogPanel(id="event-log")
                yield TaskLogPanel(id="task-log")
                yield WorkerLogPanel(id="worker-log")
        yield StatusBar(id="status-bar")
        yield Footer()

    def on_mount(self) -> None:
        self.set_interval(self._refresh_seconds, self._refresh_data)
        self.call_after_refresh(self._refresh_data)

    async def _refresh_data(self) -> None:
        states, queue_depths = await asyncio.gather(
            _load_all_states(self._config),
            _load_queue_depths(self._config),
        )
        self._states = states
        feature_list = self.query_one(FeatureList)
        await feature_list.update_features(states)
        self.query_one(StatusBar).update_time(queue_depths, self._refresh_seconds)
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
        task_panel = self.query_one(TaskPanel)
        task_panel.update_tasks(state)
        self.query_one(EventLogPanel).update_events(state)
        task_id = task_panel.selected_task_id()
        self.query_one(TaskLogPanel).update_for_task(state, task_id)

    def on_list_view_selected(self) -> None:
        self._update_detail_panels()

    def on_data_table_cursor_moved(self) -> None:
        self._update_task_log()

    def _update_task_log(self) -> None:
        feature_list = self.query_one(FeatureList)
        selected_id = feature_list.selected_feature_id()
        if not selected_id:
            return
        state = next((s for s in self._states if s.feature_id == selected_id), None)
        if not state:
            return
        task_id = self.query_one(TaskPanel).selected_task_id()
        self.query_one(TaskLogPanel).update_for_task(state, task_id)

    def action_refresh(self) -> None:
        self.call_after_refresh(self._refresh_data)

    def action_clear_logs(self) -> None:
        self.query_one(WorkerLogPanel).clear()

    def action_kill_task(self) -> None:
        task_id = self.query_one(TaskPanel).selected_task_id()
        if not task_id:
            self.notify("No task selected.", severity="warning")
            return

        feature_id = self.query_one(FeatureList).selected_feature_id()
        state = next((s for s in self._states if s.feature_id == feature_id), None)
        entry = next((t for t in (state.tasks if state else []) if t.task_id == task_id), None)
        pid = entry.pid if entry else None

        def on_confirm(confirmed: bool) -> None:
            if not confirmed:
                return
            if not pid:
                self.notify(f"No PID recorded for task {task_id.split('-dev-')[-1]}.", severity="warning")
                return
            try:
                os.kill(pid, signal.SIGTERM)
                self.notify(f"Sent SIGTERM to pid {pid} for {task_id.split('-dev-')[-1]}.", severity="warning")
            except ProcessLookupError:
                self.notify(f"Process {pid} already exited.", severity="warning")
            except Exception as exc:
                self.notify(f"Kill failed: {exc}", severity="error")

        short = task_id.split("-dev-")[-1]
        self.push_screen(ConfirmScreen(f"Kill process for task: {short}?"), on_confirm)

    def action_resume_task(self) -> None:
        feature_id = self.query_one(FeatureList).selected_feature_id()
        task_id = self.query_one(TaskPanel).selected_task_id()
        if not feature_id or not task_id:
            self.notify("No task selected.", severity="warning")
            return
        label = task_id if task_id in _PHASE_ORDER else task_id.split("-dev-")[-1]
        self.push_screen(
            ConfirmScreen(f"Resume: {label}?"),
            lambda confirmed: self.run_worker(self._do_resume_task(feature_id, task_id), exclusive=False) if confirmed else None,
        )

    def action_open_state_change(self) -> None:
        feature_id = self.query_one(FeatureList).selected_feature_id()
        if not feature_id:
            self.notify("No feature selected.", severity="warning")
            return
        state = next((s for s in self._states if s.feature_id == feature_id), None)
        if state is None:
            self.notify("Selected feature has no cached state.", severity="warning")
            return
        if state.is_raw:
            self.notify(
                "Convert to harness feature first (press i)",
                severity="warning",
            )
            return
        if state.status == FeatureStatus.done:
            self.notify(
                "State change unavailable for completed features.",
                severity="warning",
            )
            return

        def on_result(result: StateChangeResult | None) -> None:
            if result is None:
                return
            if result.mode == "fail":
                self.push_screen(
                    ConfirmScreen(
                        f"Mark {feature_id} as failed?\nThis cannot be undone automatically."
                    ),
                    lambda confirmed: (
                        self.run_worker(
                            self._do_apply_state_change(feature_id, result, state.status),
                            exclusive=False,
                        )
                        if confirmed
                        else None
                    ),
                )
                return
            self.run_worker(
                self._do_apply_state_change(feature_id, result, state.status),
                exclusive=False,
            )

        self.push_screen(StateChangeModal(state), on_result)

    async def _do_apply_state_change(
        self,
        feature_id: str,
        result: StateChangeResult,
        previous_status: FeatureStatus,
    ) -> None:
        state_mgr = create_state_manager(self._config)
        try:
            await apply_state_change(
                feature_id,
                result,
                state_mgr=state_mgr,
                queue_factory=lambda name: create_task_queue(self._config, name),
                config=self._config,
            )
            self.notify(
                f"State changed: {previous_status.value} → {result.target_status.value} ({result.mode})",
                severity="information",
            )
            self.call_after_refresh(self._refresh_data)
        except StateChangeError as exc:
            self.notify(
                f"State updated but re-queue failed — press S to retry: {exc}",
                severity="error",
            )
        except Exception as exc:
            self.notify(f"State change failed: {exc}", severity="error")
        finally:
            close = getattr(state_mgr, "close", None)
            if callable(close):
                try:
                    await close()
                except Exception:
                    pass

    async def _do_resume_task(self, feature_id: str, task_id: str) -> None:
        from agentharness.models import FeatureStatus, PhaseInfo, PhaseStatus, TaskMessage, TaskStatus
        from agentharness.storage import phase_artifact_path, review_artifact_path

        state_mgr = create_state_manager(self._config)
        state = await state_mgr.get(feature_id)

        if task_id in _PHASE_ORDER:
            await self._resume_phase(state_mgr, state, feature_id, task_id, TaskMessage, FeatureStatus, PhaseInfo, PhaseStatus, phase_artifact_path, review_artifact_path)
        else:
            await self._resume_dev_task(state_mgr, state, feature_id, task_id, TaskMessage, TaskStatus)

    async def _resume_phase(self, state_mgr, state, feature_id, phase, TaskMessage, FeatureStatus, PhaseInfo, PhaseStatus, phase_artifact_path, review_artifact_path) -> None:
        queue_name = _PHASE_TO_QUEUE.get(phase)
        if not queue_name:
            self.notify(f"No queue mapped for phase {phase!r}.", severity="error")
            return

        _phase_inputs = {
            "analyzing": [f"artifacts/{feature_id}/brief.md"],
            "architecting": [phase_artifact_path(feature_id, "spec", 1), f"artifacts/{feature_id}/brief.md"],
            "designing": [phase_artifact_path(feature_id, "spec", 1), phase_artifact_path(feature_id, "arch-review", 1)],
            "planning": [phase_artifact_path(feature_id, "spec", 1), phase_artifact_path(feature_id, "arch-review", 1), phase_artifact_path(feature_id, "design", 1)],
            "reviewing": [phase_artifact_path(feature_id, "spec", 1), phase_artifact_path(feature_id, "arch-review", 1)],
        }
        _phase_outputs = {
            "analyzing": phase_artifact_path(feature_id, "spec", 1),
            "architecting": phase_artifact_path(feature_id, "arch-review", 1),
            "designing": phase_artifact_path(feature_id, "design", 1),
            "planning": phase_artifact_path(feature_id, "task-plan", 1),
            "reviewing": review_artifact_path(feature_id, 1),
        }
        _phase_agents = {
            "analyzing": "analyst",
            "architecting": "architect",
            "designing": "designer",
            "planning": "planner",
            "reviewing": "reviewer",
        }
        _phase_status = {
            "analyzing": FeatureStatus.analyzing,
            "architecting": FeatureStatus.architecting,
            "designing": FeatureStatus.designing,
            "planning": FeatureStatus.planning,
            "reviewing": FeatureStatus.reviewing,
        }

        task_msg = TaskMessage(
            feature_id=feature_id,
            task_id=f"{feature_id}-{phase}-1",
            input_artifacts=_phase_inputs.get(phase, []),
            output_artifact=_phase_outputs[phase],
            agent_role=_phase_agents[phase],
            state_issue_number=state.state_issue_number,
        )

        await state_mgr.update(
            feature_id,
            lambda s: (
                s.with_status(_phase_status[phase])
                .with_phase(phase, PhaseInfo(status=PhaseStatus.pending))
                .with_event("phase_resumed", phase=phase)
            ),
        )

        queue = create_task_queue(self._config, queue_name)
        try:
            await queue.send_task(task_msg)
        finally:
            await queue.close()

        self.notify(f"Phase {phase!r} requeued → {queue_name}", severity="information")

    async def _resume_dev_task(self, state_mgr, state, feature_id, task_id, TaskMessage, TaskStatus) -> None:
        task_entry = next((t for t in state.tasks if t.task_id == task_id), None)
        if not task_entry:
            self.notify(f"Task {task_id!r} not found in state.", severity="error")
            return
        if task_entry.status == TaskStatus.completed:
            self.notify("Task is already completed — cannot resume.", severity="warning")
            return
        if not task_entry.queued_message:
            self.notify("No saved message for this task — cannot resume.", severity="error")
            return

        queue_name = _PHASE_TO_QUEUE.get(task_entry.phase)
        if not queue_name:
            self.notify(f"Unknown phase {task_entry.phase!r}.", severity="error")
            return

        await state_mgr.update(
            feature_id,
            lambda s: s.with_task_update(
                task_id,
                status=TaskStatus.queued,
                worker_id=None,
                started_at=None,
                completed_at=None,
            ).with_event("task_resumed", task_id=task_id),
        )

        queue = create_task_queue(self._config, queue_name)
        try:
            await queue.send_task(TaskMessage(**task_entry.queued_message))
        finally:
            await queue.close()

        short = task_id.split("-dev-")[-1]
        self.notify(f"Task {short!r} queued → {queue_name}", severity="information")

    def action_toggle_observer(self) -> None:
        pid = _observer_pid()
        if pid:
            _stop_observer(pid)
            self.notify(f"Observer stopped (pid {pid}).", severity="warning")
        else:
            new_pid = _start_observer()
            self.notify(f"Observer started (pid {new_pid}).", severity="information")

    def action_implement(self) -> None:
        feature_id = self.query_one(FeatureList).selected_feature_id()
        if not feature_id:
            self.notify("No feature selected.", severity="warning")
            return
        self.run_worker(self._do_implement(feature_id), exclusive=False)

    async def _do_implement(self, feature_id: str) -> None:
        from agentharness.brainstorm import enqueue_planner
        await enqueue_planner(feature_id, self._config)
        self.notify(f"Analyzing: {feature_id}", severity="information")

    def action_purge_queues(self) -> None:
        def on_confirm(confirmed: bool) -> None:
            if confirmed:
                self.run_worker(self._do_purge_queues(), exclusive=True)
        self.push_screen(ConfirmScreen("Purge ALL queues? This cannot be undone."), on_confirm)

    async def _do_purge_queues(self) -> None:
        for queue_name in self._config.queue_names():
            queue = create_task_queue(self._config, queue_name)
            try:
                await queue.purge()
            finally:
                await queue.close()
        self.notify("All queues purged.", severity="warning")

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
    state_mgr = create_state_manager(config)
    states = await state_mgr.list_features()

    def sort_key(s: FeatureState):
        active = s.status not in (FeatureStatus.done, FeatureStatus.failed)
        return (not active, -(s.updated_at.timestamp() if s.updated_at else 0))

    return sorted(states, key=sort_key)


async def _load_queue_depths(config: Config) -> dict[str, int]:
    depths: dict[str, int] = {}
    for queue_name in config.queue_names():
        queue = create_task_queue(config, queue_name)
        try:
            depths[queue_name] = await queue.get_depth()
        except Exception:
            depths[queue_name] = 0
        finally:
            await queue.close()
    return depths


def run_monitor(config: Config) -> None:
    app = PipelineMonitor(config)
    app.run()
