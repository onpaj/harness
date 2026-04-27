"""Observer: polls all queues and spawns a subprocess per task message."""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from pathlib import Path

from agentharness.config import Config
from agentharness.models import TaskMessage
from agentharness.storage import create_task_queue
from agentharness.storage_protocol import RawMessage, TaskQueue

log = logging.getLogger(__name__)

_RENEWAL_INTERVAL = 60      # seconds between visibility renewals
_VISIBILITY_TIMEOUT = 150   # seconds of visibility granted per renewal

_STALE_CLAIM_TIMEOUT = 150  # seconds before a claimed task is reclaimed
_SWEEP_INTERVAL = 60        # seconds between sweeps
_STATE_CACHE_INTERVAL = 30  # seconds between local state cache writes (GitHub backend)
STATE_CACHE_PATH = Path("logs/state-cache.json")

# GitHub search API allows 30 req/min. With N queues staggered evenly across
# _GITHUB_POLL_INTERVAL, peak rate = N / _GITHUB_POLL_INTERVAL req/s.
# At 15s and 6 queues: 6/15 = 0.4 req/s = 24 req/min — safely under the limit.
_GITHUB_POLL_INTERVAL = 15.0


async def observe(config: Config) -> None:
    """Poll all queues and spawn a subprocess per message."""
    queues: dict[str, TaskQueue] = {}
    for q_name in config.queue_names():
        q = create_task_queue(config, q_name)
        await q.ensure_exists()
        queues[q_name] = q

    log.info("Observer started — watching %d queues: %s", len(queues), ", ".join(queues))
    exe = str(Path(sys.executable).parent / "agentharness")

    active_procs: dict[str, asyncio.Process] = {}

    is_github = config.storage_backend == "github"

    loop = asyncio.get_running_loop()

    def _shutdown() -> None:
        log.info("Observer shutting down — terminating %d active subprocess(es)", len(active_procs))
        for task_id, proc in list(active_procs.items()):
            try:
                proc.terminate()
                log.info("Sent SIGTERM to subprocess for task %s (pid %d)", task_id, proc.pid)
            except ProcessLookupError:
                pass
        for task in asyncio.all_tasks(loop):
            task.cancel()

    loop.add_signal_handler(signal.SIGTERM, _shutdown)
    loop.add_signal_handler(signal.SIGINT, _shutdown)

    try:
        if is_github:
            poll_tasks = [_poll_all_queues_github(queues, config, exe, active_procs)]
        else:
            poll_interval = config.defaults.poll_interval_seconds
            poll_tasks = [
                _poll_queue(q_name, q, config, exe, active_procs, poll_interval)
                for q_name, q in queues.items()
            ]
        await asyncio.gather(
            *poll_tasks,
            _sweep_stale_claims(config),
            _sync_state_cache(config),
        )
    except asyncio.CancelledError:
        pass
    finally:
        for q in queues.values():
            await q.close()


async def _poll_queue(
    queue_name: str,
    queue: TaskQueue,
    config: Config,
    exe: str,
    active_procs: dict[str, asyncio.Process],
    poll_interval: float,
) -> None:
    log.info("Polling %s (interval=%.1fs)", queue_name, poll_interval)
    while True:
        result = await queue.receive_task(visibility_timeout=_VISIBILITY_TIMEOUT)
        if result is None:
            await asyncio.sleep(poll_interval)
            continue
        task, raw_msg = result
        log.info("Received task %s from %s", task.task_id, queue_name)
        asyncio.create_task(
            _run_subprocess(queue_name, task, raw_msg, queue, exe, active_procs),
            name=f"task-{task.task_id}",
        )


async def _poll_all_queues_github(
    queues: dict[str, TaskQueue],
    config: Config,
    exe: str,
    active_procs: dict[str, asyncio.Process],
) -> None:
    """Single-search poller for GitHub backend: one API call per cycle for all queues."""
    from agentharness.github_client import GitHubClient
    from agentharness.github_labels import LABEL_TO_QUEUE_NAME, STATE_QUEUED
    from agentharness.github_queue import GitHubTaskQueue

    client = GitHubClient.from_config(config)
    log.info("GitHub single-search poller started (interval=%.1fs)", _GITHUB_POLL_INTERVAL)
    try:
        while True:
            try:
                issues = await client.search_issues(
                    f"is:open label:{STATE_QUEUED} repo:{client.owner}/{client.repo}",
                    sort="created",
                    order="asc",
                )
            except Exception as exc:
                log.warning("GitHub poll search failed: %s", exc)
                await asyncio.sleep(_GITHUB_POLL_INTERVAL)
                continue

            # Group by queue label; pick oldest (first) per queue
            dispatched: set[str] = set()
            for issue in issues:
                label_names = {lbl["name"] for lbl in issue.get("labels", [])}
                queue_name = next(
                    (LABEL_TO_QUEUE_NAME[lbl] for lbl in label_names if lbl in LABEL_TO_QUEUE_NAME),
                    None,
                )
                if not queue_name or queue_name in dispatched or queue_name not in queues:
                    continue
                dispatched.add(queue_name)
                queue = queues[queue_name]
                if not isinstance(queue, GitHubTaskQueue):
                    continue
                try:
                    task, raw_msg = await queue.claim_issue(issue)
                except Exception as exc:
                    log.warning("Failed to claim issue #%s for %s: %s", issue["number"], queue_name, exc)
                    continue
                log.info("Claimed task %s from %s", task.task_id, queue_name)
                asyncio.create_task(
                    _run_subprocess(queue_name, task, raw_msg, queue, exe, active_procs),
                    name=f"task-{task.task_id}",
                )

            await asyncio.sleep(_GITHUB_POLL_INTERVAL)
    finally:
        await client.close()


async def _run_subprocess(
    queue_name: str,
    task: TaskMessage,
    raw_msg: RawMessage,
    queue: TaskQueue,
    exe: str,
    active_procs: dict[str, asyncio.Process],
) -> None:
    log_dir = Path("logs") / queue_name
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{task.task_id}.log"

    task_json = task.model_dump_json()
    log.info("Spawning subprocess for %s → %s", task.task_id, log_file)

    try:
        with open(log_file, "w") as fh:
            proc = await asyncio.create_subprocess_exec(
                exe, "run-task", queue_name,
                stdin=asyncio.subprocess.PIPE,
                stdout=fh,
                stderr=fh,
            )
            active_procs[task.task_id] = proc
            log.info("Task %s running as pid %d", task.task_id, proc.pid)

            proc.stdin.write(task_json.encode())
            await proc.stdin.drain()
            proc.stdin.close()

            final_raw = await _wait_with_renewal(proc, task.task_id, raw_msg, queue)

    except Exception as exc:
        log.error("Subprocess management failed for %s: %s", task.task_id, exc)
        return
    finally:
        active_procs.pop(task.task_id, None)

    if proc.returncode == 0:
        try:
            await queue.delete_message(final_raw)
            log.info("Task %s done — message deleted", task.task_id)
        except Exception as exc:
            log.error("Could not delete message for %s: %s", task.task_id, exc)
    else:
        log.error(
            "Task %s failed (exit %d) — logs: %s — deleting message (no retry)",
            task.task_id, proc.returncode, log_file,
        )
        try:
            await queue.delete_message(final_raw)
        except Exception as exc:
            log.warning("Could not delete failed message for %s: %s", task.task_id, exc)


async def _wait_with_renewal(proc: asyncio.Process, task_id: str, raw_msg: RawMessage, queue: TaskQueue) -> RawMessage:
    """Wait for subprocess, renewing queue message visibility every _RENEWAL_INTERVAL seconds.

    Returns the latest RawMessage (with updated pop_receipt) for deletion.
    """
    current = raw_msg

    while True:
        try:
            await asyncio.wait_for(asyncio.shield(proc.wait()), timeout=_RENEWAL_INTERVAL)
            return current
        except asyncio.TimeoutError:
            try:
                current = await queue.extend_visibility(current, _VISIBILITY_TIMEOUT)
                log.debug("Renewed visibility for %s", task_id)
            except Exception as exc:
                err_str = str(exc)
                if "MessageNotFound" in err_str:
                    log.debug("Message for %s already deleted — task completed before renewal", task_id)
                    return current
                log.warning("Could not renew visibility for %s: %s — message may be re-queued", task_id, exc)


async def _sweep_stale_claims(config: Config) -> None:
    """Periodically reclaim in-progress issues whose updated_at has gone stale. GitHub backend only."""
    if config.storage_backend != "github":
        return
    from datetime import UTC, datetime
    from agentharness.github_client import GitHubClient
    from agentharness.github_labels import STATE_IN_PROGRESS

    client = GitHubClient.from_config(config)
    try:
        while True:
            await asyncio.sleep(_SWEEP_INTERVAL)
            try:
                issues = await client.search_issues(
                    f"is:open+label:{STATE_IN_PROGRESS}+repo:{client.owner}/{client.repo}"
                )
                now = datetime.now(UTC)
                for issue in issues:
                    updated_at_str = issue.get("updated_at") or ""
                    try:
                        updated_at = datetime.fromisoformat(updated_at_str.replace("Z", "+00:00"))
                    except ValueError:
                        continue
                    if (now - updated_at).total_seconds() > _STALE_CLAIM_TIMEOUT:
                        await _reclaim_issue(client, issue)
            except Exception as exc:
                log.warning("Sweeper error: %s", exc)
    finally:
        await client.close()


async def _sync_state_cache(config: Config) -> None:
    """Periodically write all feature states to a local JSON cache. GitHub backend only."""
    if config.storage_backend != "github":
        return
    import json
    from agentharness.github_state import GitHubStateManager

    while True:
        try:
            mgr = GitHubStateManager.from_config(config)
            features = await mgr.list_features()
            states = []
            for feature_id, _ in features:
                try:
                    state = await mgr.get(feature_id)
                    states.append(state.model_dump(mode="json"))
                except Exception as exc:
                    log.warning("State cache: could not load %s: %s", feature_id, exc)
            STATE_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            STATE_CACHE_PATH.write_text(json.dumps(states))
            log.debug("State cache written: %d features", len(states))
        except Exception as exc:
            log.warning("State cache sync failed: %s", exc)
        await asyncio.sleep(_STATE_CACHE_INTERVAL)


async def _reclaim_issue(client, issue: dict) -> None:
    """Remove stale claim labels and requeue the issue."""
    from agentharness.github_labels import STATE_IN_PROGRESS, STATE_QUEUED, is_claimed_by_label
    number = issue["number"]
    labels_to_remove = [
        lbl["name"] for lbl in issue.get("labels", [])
        if is_claimed_by_label(lbl["name"]) or lbl["name"] == STATE_IN_PROGRESS
    ]
    for label in labels_to_remove:
        try:
            await client.remove_label(number, label)
        except Exception:
            pass
    await client.add_labels(number, [STATE_QUEUED])
    await client.create_comment(number, "⚠️ Reclaimed: stale heartbeat (observer restart or crash)")
    log.info("Reclaimed stale issue #%d", number)
