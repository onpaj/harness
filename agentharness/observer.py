"""Observer: polls all queues and spawns a subprocess per task message."""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from pathlib import Path

from agentharness.config import Config
from agentharness.models import TaskMessage
from agentharness.storage import ArtifactStore, PipelineQueue
from agentharness.storage_protocol import RawMessage

log = logging.getLogger(__name__)

_RENEWAL_INTERVAL = 60      # seconds between visibility renewals
_VISIBILITY_TIMEOUT = 150   # seconds of visibility granted per renewal


async def observe(config: Config) -> None:
    """Poll all queues and spawn a subprocess per message."""
    conn_str = config.storage.connection_string

    from azure.storage.blob.aio import BlobServiceClient
    blob_service = BlobServiceClient.from_connection_string(conn_str)
    store = ArtifactStore(blob_service, config.storage.container)
    await store.ensure_container_exists()

    queues: dict[str, PipelineQueue] = {}
    for q_name in config.queue_names():
        q = PipelineQueue.from_connection_string(conn_str, q_name)
        await q.ensure_exists()
        queues[q_name] = q

    log.info("Observer started — watching %d queues: %s", len(queues), ", ".join(queues))
    exe = str(Path(sys.executable).parent / "agentharness")

    active_procs: dict[str, asyncio.Process] = {}

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
        await asyncio.gather(*[
            _poll_queue(q_name, q, config, exe, active_procs)
            for q_name, q in queues.items()
        ])
    except asyncio.CancelledError:
        pass
    finally:
        for q in queues.values():
            await q.close()
        await blob_service.close()


async def _poll_queue(
    queue_name: str,
    queue: PipelineQueue,
    config: Config,
    exe: str,
    active_procs: dict[str, asyncio.Process],
) -> None:
    log.info("Polling %s", queue_name)
    while True:
        result = await queue.receive_task(visibility_timeout=_VISIBILITY_TIMEOUT)
        if result is None:
            await asyncio.sleep(config.defaults.poll_interval_seconds)
            continue
        task, raw_msg = result
        log.info("Received task %s from %s", task.task_id, queue_name)
        asyncio.create_task(
            _run_subprocess(queue_name, task, raw_msg, queue, exe, active_procs),
            name=f"task-{task.task_id}",
        )


async def _run_subprocess(
    queue_name: str,
    task: TaskMessage,
    raw_msg: RawMessage,
    queue: PipelineQueue,
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


async def _wait_with_renewal(proc: asyncio.Process, task_id: str, raw_msg: RawMessage, queue: PipelineQueue) -> RawMessage:
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
