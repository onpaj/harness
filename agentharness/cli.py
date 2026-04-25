"""Click CLI entry points for AgentHarness."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table
from rich import box

from agentharness.config import load_config

console = Console()


@click.group()
@click.option("--config", "config_path", default=None, type=click.Path(), help="Path to config.json")
@click.pass_context
def main(ctx: click.Context, config_path: str | None) -> None:
    """AgentHarness — autonomous agentic development pipeline."""
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = Path(config_path) if config_path else None


@main.command()
@click.pass_context
def brainstorm(ctx: click.Context) -> None:
    """Start an interactive brainstorm session to define a feature brief."""
    config_path = ctx.obj.get("config_path")
    try:
        config = load_config(config_path) if config_path else None
    except FileNotFoundError:
        config = None  # Config not required until submission

    from agentharness.brainstorm import start_brainstorm
    start_brainstorm(config)


@main.command()
@click.argument("brief_file", type=click.Path(exists=True))
@click.pass_context
def submit(ctx: click.Context, brief_file: str) -> None:
    """Upload a brief file to Azure blob storage. Does not start the pipeline."""
    config = load_config(ctx.obj.get("config_path"))
    from agentharness.brainstorm import upload_brief_file
    feature_id = asyncio.run(upload_brief_file(Path(brief_file), config))
    console.print(f"[green]Brief uploaded:[/green] {feature_id}")
    console.print(f"Start pipeline: [bold]agentharness implement {feature_id}[/bold]")


@main.command()
@click.argument("feature_id")
@click.pass_context
def implement(ctx: click.Context, feature_id: str) -> None:
    """Start the pipeline for an uploaded feature brief."""
    config = load_config(ctx.obj.get("config_path"))
    from agentharness.brainstorm import enqueue_planner
    asyncio.run(enqueue_planner(feature_id, config))
    console.print(f"[green]Pipeline started:[/green] {feature_id}")
    console.print(f"Monitor: [bold]agentharness watch[/bold]")


@main.command()
@click.argument("queue_name")
@click.option("--concurrency", default=1, show_default=True, help="Number of concurrent workers")
@click.pass_context
def worker(ctx: click.Context, queue_name: str, concurrency: int) -> None:
    """Run a worker process for the given queue."""
    config = load_config(ctx.obj.get("config_path"))
    if queue_name not in config.queues:
        console.print(f"[red]Unknown queue:[/red] {queue_name}")
        console.print(f"Available queues: {', '.join(config.queue_names())}")
        sys.exit(1)

    from agentharness.worker import start_workers
    console.print(f"Starting {concurrency} worker(s) on [bold]{queue_name}[/bold]")
    asyncio.run(start_workers(queue_name, config, concurrency))


@main.command("start")
@click.option("--dev-concurrency", default=3, show_default=True, help="Concurrent developer workers")
@click.pass_context
def start_all(ctx: click.Context, dev_concurrency: int) -> None:
    """Start all pipeline workers in background processes."""
    import subprocess
    import os
    config = load_config(ctx.obj.get("config_path"))
    exe = str(Path(sys.executable).parent / "agentharness")

    queues = [
        ("planner-queue", 1),
        ("architect-queue", 1),
        ("designer-queue", 1),
        ("developer-queue", dev_concurrency),
        ("review-queue", 1),
    ]
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    pids = []
    for queue_name, concurrency in queues:
        if queue_name not in config.queues:
            continue
        log_file = log_dir / f"{queue_name}.log"
        fh = open(log_file, "a")
        proc = subprocess.Popen(
            [exe, "worker", queue_name, "--concurrency", str(concurrency)],
            stdout=fh,
            stderr=fh,
            start_new_session=True,
        )
        pids.append((queue_name, proc.pid))
        console.print(f"[green]Started[/green] {queue_name} (pid {proc.pid}) → logs/{queue_name}.log")

    console.print(f"\n[bold]{len(pids)} workers running in background.[/bold] Monitor with: [bold]agentharness watch[/bold]")


@main.command("observe")
@click.pass_context
def observe(ctx: click.Context) -> None:
    """Single observer process: polls all queues, spawns a subprocess per task."""
    import subprocess
    config = load_config(ctx.obj.get("config_path"))
    exe = str(Path(sys.executable).parent / "agentharness")
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / "observer.log"
    fh = open(log_file, "a")
    proc = subprocess.Popen(
        [exe, "_observe"],
        stdout=fh,
        stderr=fh,
        start_new_session=True,
    )
    console.print(f"[green]Observer started[/green] (pid {proc.pid}) → logs/observer.log")
    console.print("Monitor with: [bold]agentharness watch[/bold]")


@main.command("_observe")
@click.pass_context
def _observe(ctx: click.Context) -> None:
    """Internal: run the observer loop (do not call directly)."""
    from agentharness.observer import observe as _run_observe
    from agentharness.run_task import configure_logging
    configure_logging()
    config = load_config(ctx.obj.get("config_path"))
    asyncio.run(_run_observe(config))


@main.command("run-task")
@click.argument("queue_name")
@click.pass_context
def run_task_cmd(ctx: click.Context, queue_name: str) -> None:
    """Internal: run one task (reads TaskMessage JSON from stdin). Used by observer."""
    import sys as _sys
    from agentharness.run_task import configure_logging, run_task
    configure_logging()
    task_json = _sys.stdin.read()
    config = load_config(ctx.obj.get("config_path"))
    asyncio.run(run_task(queue_name, task_json, config))


@main.command()
@click.option("--lines", "-n", default=50, show_default=True, help="Lines of history per file")
@click.pass_context
def logs(ctx: click.Context, lines: int) -> None:
    """Stream all active task logs to the terminal (plain text, copyable)."""
    import subprocess
    log_dir = Path("logs")
    if not log_dir.exists():
        console.print("[yellow]No logs directory found. Start the observer first.[/yellow]")
        return
    log_files = sorted(log_dir.rglob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not log_files:
        console.print("[yellow]No log files found yet.[/yellow]")
        return
    console.print(f"[dim]Tailing {len(log_files)} log file(s). Ctrl+C to exit.[/dim]\n")
    subprocess.run(["tail", f"-n{lines}", "-F", *[str(f) for f in log_files]])


@main.command()
@click.pass_context
def watch(ctx: click.Context) -> None:
    """Open real-time TUI monitoring all pipeline features."""
    config = load_config(ctx.obj.get("config_path"))
    from agentharness.tui import run_monitor
    run_monitor(config)


@main.command()
@click.argument("feature_id")
@click.pass_context
def status(ctx: click.Context, feature_id: str) -> None:
    """Show the current status of a feature."""
    config = load_config(ctx.obj.get("config_path"))
    asyncio.run(_show_status(feature_id, config))


@main.command("init")
@click.option("--dir", "target_dir", default=".", show_default=True, type=click.Path(), help="Project directory to initialise")
@click.option("--force", is_flag=True, help="Overwrite existing files")
def init_project(target_dir: str, force: bool) -> None:
    """Copy agent definitions and pipeline config into a project directory."""
    import shutil
    data_root = Path(__file__).parent / "data"
    target = Path(target_dir).resolve()

    if not data_root.exists():
        console.print("[red]Data files not found in package — reinstall agentharness.[/red]")
        sys.exit(1)

    destinations = [
        (data_root / "agents", target / ".agents"),
        (data_root / "pipeline", target / ".pipeline"),
    ]

    for src, dst in destinations:
        if not src.exists():
            continue
        dst.mkdir(parents=True, exist_ok=True)
        for src_file in src.iterdir():
            dst_file = dst / src_file.name
            if dst_file.exists() and not force:
                console.print(f"[dim]skip[/dim] {dst_file.relative_to(target)} (use --force to overwrite)")
                continue
            shutil.copy2(src_file, dst_file)
            console.print(f"[green]wrote[/green] {dst_file.relative_to(target)}")

    env_example = target / ".env.example"
    if not env_example.exists() or force:
        env_example.write_text("AZURE_STORAGE_CONNECTION_STRING=\n")
        console.print(f"[green]wrote[/green] .env.example")

    console.print("\n[bold]Done.[/bold] Copy .env.example → .env and fill in your connection string.")


@main.command("list")
@click.pass_context
def list_features(ctx: click.Context) -> None:
    """List all features in the pipeline."""
    config = load_config(ctx.obj.get("config_path"))
    asyncio.run(_list_features(config))


async def _show_status(feature_id: str, config) -> None:
    from azure.storage.blob.aio import BlobServiceClient
    from agentharness.state_manager import StateManager
    from agentharness.models import TaskStatus

    blob_service = BlobServiceClient.from_connection_string(config.storage.connection_string)
    mgr = StateManager(blob_service, config.storage.container)
    try:
        state = await mgr.get(feature_id)
    except KeyError:
        console.print(f"[red]Feature not found:[/red] {feature_id}")
        sys.exit(1)
    finally:
        await blob_service.close()

    console.print(f"\n[bold]Feature:[/bold] {state.feature_id}")
    console.print(f"[bold]Status:[/bold]  {_status_style(state.status)}")
    console.print(f"[bold]Created:[/bold] {_fmt_dt(state.created_at)}")
    console.print(f"[bold]Updated:[/bold] {_fmt_dt(state.updated_at)}")

    if state.phases:
        console.print("\n[bold]Phases:[/bold]")
        phase_order = ["planning", "architecting", "designing", "developing", "reviewing"]
        for phase in phase_order:
            info = state.phases.get(phase)
            if info:
                icon = {"completed": "[green]✓[/green]", "in_progress": "[yellow]▶[/yellow]", "pending": "[dim]○[/dim]", "failed": "[red]✗[/red]"}.get(info.status, "?")
                duration = ""
                if info.started_at and info.completed_at:
                    secs = int((info.completed_at - info.started_at).total_seconds())
                    duration = f"  [dim]({_fmt_duration(secs)})[/dim]"
                console.print(f"  {icon} {phase:<14} {info.status}{duration}")

    if state.tasks:
        console.print("\n[bold]Tasks:[/bold]")
        table = Table(box=box.SIMPLE, show_header=True, header_style="bold")
        table.add_column("Task ID", style="cyan")
        table.add_column("Status")
        table.add_column("Worker")
        table.add_column("Rev")
        for t in state.tasks:
            status_str = _task_status_style(t.status)
            table.add_row(t.task_id, status_str, t.worker_id or "—", str(t.revision))
        console.print(table)

    if state.config.current_revision_round > 0:
        console.print(
            f"\n[yellow]Revision round:[/yellow] {state.config.current_revision_round} / {state.config.max_revisions}"
        )


async def _list_features(config) -> None:
    from azure.storage.blob.aio import BlobServiceClient

    blob_service = BlobServiceClient.from_connection_string(config.storage.connection_string)
    container = blob_service.get_container_client(config.storage.container)

    table = Table(box=box.SIMPLE, show_header=True, header_style="bold")
    table.add_column("Feature ID", style="cyan")
    table.add_column("Status")
    table.add_column("Updated")

    try:
        async for blob in container.list_blobs(name_starts_with="artifacts/"):
            if blob.name.endswith("/state.json"):
                feature_id = blob.name.split("/")[1]
                from agentharness.state_manager import StateManager
                mgr = StateManager(blob_service, config.storage.container)
                try:
                    state = await mgr.get(feature_id)
                    table.add_row(
                        feature_id,
                        _status_style(state.status),
                        _fmt_dt(state.updated_at),
                    )
                except Exception:
                    table.add_row(feature_id, "[dim]unreadable[/dim]", "—")
    finally:
        await blob_service.close()

    console.print(table)


def _status_style(status) -> str:
    styles = {
        "done": "[green]done[/green]",
        "failed": "[red]failed[/red]",
        "developing": "[yellow]developing[/yellow]",
        "reviewing": "[yellow]reviewing[/yellow]",
        "dev_revision": "[yellow]dev_revision[/yellow]",
        "planning": "[blue]planning[/blue]",
        "architecting": "[blue]architecting[/blue]",
        "designing": "[blue]designing[/blue]",
        "brainstorming": "[blue]brainstorming[/blue]",
    }
    return styles.get(str(status), str(status))


def _task_status_style(status) -> str:
    styles = {
        "completed": "[green]completed[/green]",
        "failed": "[red]failed[/red]",
        "in_progress": "[yellow]in_progress[/yellow]",
        "queued": "[dim]queued[/dim]",
    }
    return styles.get(str(status), str(status))


def _fmt_dt(dt) -> str:
    if dt is None:
        return "—"
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")


def _fmt_duration(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    m, s = divmod(seconds, 60)
    return f"{m}m {s}s"
