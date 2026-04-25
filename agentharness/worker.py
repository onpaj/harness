"""Async worker loop — consumes a queue, runs agents, dispatches next steps."""

from __future__ import annotations

import asyncio
import logging
import os
import socket
from datetime import UTC, datetime
from pathlib import Path

from azure.storage.blob.aio import BlobServiceClient

from agentharness.agent_runner import AgentExecutionError, run_agent
from agentharness.config import Config
from agentharness.context_files import ContextFileResult, resolve_context_files
from agentharness.dispatcher import dispatch_after_completion
from agentharness.models import (
    FeatureStatus,
    PhaseInfo,
    PhaseStatus,
    TaskMessage,
    TaskStatus,
)
from agentharness.prompt_builder import artifact_label, build_prompt, load_agent_definition
from agentharness.state_manager import StateManager
from agentharness.storage import ArtifactStore, PipelineQueue

log = logging.getLogger(__name__)

WORKER_ID = f"{socket.gethostname()}-{os.getpid()}"


class Worker:
    """Processes tasks from a single Azure Storage Queue."""

    def __init__(
        self,
        queue_name: str,
        queue: PipelineQueue,
        artifact_store: ArtifactStore,
        state_manager: StateManager,
        all_queues: dict[str, PipelineQueue],
        config: Config,
    ) -> None:
        self._queue_name = queue_name
        self._queue = queue
        self._store = artifact_store
        self._state = state_manager
        self._all_queues = all_queues
        self._config = config
        self._context_cache: dict[str, ContextFileResult] = {}

    async def run(self) -> None:
        agent_path = self._config.agent_path_for_queue(self._queue_name)
        agent_def = load_agent_definition(agent_path)
        log.info("Worker %s started on %s (model: %s)", WORKER_ID, self._queue_name, agent_def.model)

        while True:
            result = await self._queue.receive_task(
                visibility_timeout=agent_def.visibility_timeout
            )
            if result is None:
                await asyncio.sleep(self._config.defaults.poll_interval_seconds)
                continue

            task, raw_msg = result
            try:
                await self._process_task(task, agent_def)
                await self._queue.delete_message(raw_msg)
            except Exception as exc:
                log.error("Task %s failed: %s", task.task_id, exc, exc_info=True)
                if raw_msg.dequeue_count >= self._config.defaults.dead_letter_threshold:
                    await self._move_to_dead_letter(raw_msg, task)
                    await self._mark_feature_failed(task, str(exc))
                # Otherwise: message returns to queue after visibility timeout

    async def _process_task(self, task: TaskMessage, agent_def) -> None:
        log.info("[%s] Starting task %s", WORKER_ID, task.task_id)

        # Guard against stale queue messages from previous pipeline runs
        current_state = await self._state.get(task.feature_id)
        if current_state.status.value != agent_def.phase:
            log.warning(
                "[%s] Discarding stale task %s: feature is in %r but this worker handles %r",
                WORKER_ID, task.task_id, current_state.status.value, agent_def.phase,
            )
            return

        # Prepare per-task log file
        log_dir = Path("logs")
        log_dir.mkdir(parents=True, exist_ok=True)
        task_log_file = log_dir / f"{task.task_id}.log"

        # Mark phase/task as in_progress in state (includes log_file path)
        await self._state.update(
            task.feature_id,
            lambda s: _mark_task_started(s, task, WORKER_ID, str(task_log_file)),
        )

        # Prepare work dir
        work_dir = None
        if task.work_dir:
            work_dir = Path(task.work_dir)
            work_dir.mkdir(parents=True, exist_ok=True)

        # Download input artifacts and write to work dir
        artifact_contents: dict[str, str] = {}
        for blob_path in task.input_artifacts:
            try:
                content = await self._store.download(blob_path)
                label = artifact_label(blob_path)
                artifact_contents[label] = content
                if work_dir:
                    (work_dir / label).write_text(content)
            except Exception as exc:
                log.warning("Could not download artifact %s: %s", blob_path, exc)

        # Resolve context files (read-once; cached for retries of the same task)
        context_result = self._resolve_context_files_cached(task.task_id)

        # Build prompt and run agent
        prompt = build_prompt(agent_def, task, artifact_contents, context_result)
        output = await run_agent(agent_def, prompt, work_dir=work_dir, log_file=task_log_file)

        # Upload output artifact
        await self._store.upload(task.output_artifact, output)
        log.info("[%s] Task %s complete, output at %s", WORKER_ID, task.task_id, task.output_artifact)

        # Update state atomically (mark complete + dispatch)
        updated_state = await self._state.update(
            task.feature_id,
            lambda s: _mark_task_completed(s, task),
        )

        # Dispatch next step
        next_state = await dispatch_after_completion(
            updated_state, task, output, self._config, self._all_queues
        )
        if next_state is not None:
            await self._state.update(task.feature_id, lambda _: next_state)

        # Task completed successfully — release cached context for this task
        self._context_cache.pop(task.task_id, None)

    def _resolve_context_files_cached(self, task_id: str) -> ContextFileResult | None:
        """Return the ContextFileResult for this task, reading files only on first call."""
        queue_config = self._config.queues.get(self._queue_name)
        if not queue_config or not queue_config.context_files:
            return None

        if task_id in self._context_cache:
            log.debug("[%s] Reusing cached context files for task %s", WORKER_ID, task_id)
            return self._context_cache[task_id]

        agent_name = Path(queue_config.agent).stem
        result = resolve_context_files(
            queue_config.context_files,
            agent_name,
            self._config.config_dir,
        )
        for warning in result.warnings:
            log.warning("[%s] %s", WORKER_ID, warning)

        self._context_cache[task_id] = result
        return result

    async def _move_to_dead_letter(self, raw_msg, task: TaskMessage) -> None:
        dead_letter_name = f"{self._queue_name}-poison"
        log.error(
            "Moving task %s to dead-letter queue %s", task.task_id, dead_letter_name
        )
        conn_str = self._config.storage.connection_string
        await self._queue.move_to_dead_letter(raw_msg, dead_letter_name, conn_str)

    async def _mark_feature_failed(self, task: TaskMessage, reason: str) -> None:
        try:
            await self._state.update(
                task.feature_id,
                lambda s: s.with_status(FeatureStatus.failed).with_event(
                    "feature_failed", task_id=task.task_id, details=reason[:200]
                ),
            )
        except Exception as exc:
            log.error("Could not mark feature %s as failed: %s", task.feature_id, exc)


def _mark_task_started(state, task: TaskMessage, worker_id: str, log_file: str | None = None):
    phase = state.status.value
    updated = (
        state
        .with_task_update(
            task.task_id,
            status=TaskStatus.in_progress,
            worker_id=worker_id,
            started_at=datetime.now(UTC),
            log_file=log_file,
        )
        .with_phase(phase, PhaseInfo(status=PhaseStatus.in_progress))
    )
    return updated.with_event("task_started", phase=phase, task_id=task.task_id, worker_id=worker_id)


def _mark_task_completed(state, task: TaskMessage):
    phase = state.status.value
    updated = (
        state
        .with_task_update(
            task.task_id,
            status=TaskStatus.completed,
            completed_at=datetime.now(UTC),
            output_artifact=task.output_artifact,
        )
        .with_phase(phase, PhaseInfo(status=PhaseStatus.completed))
    )
    return updated.with_event("task_completed", phase=phase, task_id=task.task_id)


async def start_workers(queue_name: str, config: Config, concurrency: int = 1) -> None:
    """Create and run worker(s) for a queue, managing shared Azure clients."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
        datefmt="%H:%M:%S",
        force=True,
    )
    logging.getLogger("azure").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    conn_str = config.storage.connection_string
    blob_service = BlobServiceClient.from_connection_string(conn_str)
    store = ArtifactStore(blob_service, config.storage.container)
    state_mgr = StateManager(blob_service, config.storage.container)

    # Ensure infrastructure exists
    await store.ensure_container_exists()

    all_queues: dict[str, PipelineQueue] = {}
    for q_name in config.queue_names():
        q = PipelineQueue.from_connection_string(conn_str, q_name)
        await q.ensure_exists()
        all_queues[q_name] = q

    workers = [
        Worker(queue_name, all_queues[queue_name], store, state_mgr, all_queues, config)
        for _ in range(concurrency)
    ]

    try:
        await asyncio.gather(*[w.run() for w in workers])
    finally:
        for q in all_queues.values():
            await q.close()
        await store.close()
