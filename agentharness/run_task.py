"""Single-task runner — reads TaskMessage JSON from stdin, processes it, exits.

Invoked by the observer as a subprocess. Writes all logs to stdout so the
observer can redirect them to a per-task log file.
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import sys
from datetime import UTC, datetime
from pathlib import Path

from azure.storage.blob.aio import BlobServiceClient

from agentharness.agent_runner import run_agent
from agentharness.config import Config
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


async def run_task(queue_name: str, task_json: str, config: Config) -> None:
    task = TaskMessage.model_validate_json(task_json)
    conn_str = config.storage.connection_string

    blob_service = BlobServiceClient.from_connection_string(conn_str)
    store = ArtifactStore(blob_service, config.storage.container)
    state_mgr = StateManager(blob_service, config.storage.container)

    all_queues: dict[str, PipelineQueue] = {}
    for q_name in config.queue_names():
        all_queues[q_name] = PipelineQueue.from_connection_string(conn_str, q_name)

    try:
        agent_path = config.agent_path_for_queue(queue_name)
        agent_def = load_agent_definition(agent_path)

        log.info("[%s] Starting task %s", WORKER_ID, task.task_id)

        await state_mgr.update(task.feature_id, lambda s: _mark_started(s, task))

        work_dir = None
        if task.work_dir:
            work_dir = Path(task.work_dir)
            work_dir.mkdir(parents=True, exist_ok=True)

        artifact_contents: dict[str, str] = {}
        for blob_path in task.input_artifacts:
            content = await _download_with_retry(store, blob_path)
            if content is None:
                log.warning("Skipping missing artifact %s", blob_path)
                continue
            label = artifact_label(blob_path)
            artifact_contents[label] = content
            if work_dir:
                (work_dir / label).write_text(content)

        prompt = build_prompt(agent_def, task, artifact_contents)
        output = await run_agent(agent_def, prompt, work_dir=work_dir)

        await store.upload(task.output_artifact, output)
        log.info("[%s] Task %s complete → %s", WORKER_ID, task.task_id, task.output_artifact)

        updated_state = await state_mgr.update(task.feature_id, lambda s: _mark_completed(s, task))

        next_state = await dispatch_after_completion(updated_state, task, output, config, all_queues)
        if next_state is not None:
            await state_mgr.update(task.feature_id, lambda _: next_state)

    finally:
        for q in all_queues.values():
            await q.close()
        await store.close()
        await blob_service.close()


def _mark_started(state, task: TaskMessage):
    phase = state.status.value
    return (
        state
        .with_task_update(task.task_id, status=TaskStatus.in_progress, worker_id=WORKER_ID, started_at=datetime.now(UTC), pid=os.getpid())
        .with_phase(phase, PhaseInfo(status=PhaseStatus.in_progress))
        .with_event("task_started", phase=phase, task_id=task.task_id, worker_id=WORKER_ID)
    )


def _mark_completed(state, task: TaskMessage):
    phase = state.status.value
    return (
        state
        .with_task_update(task.task_id, status=TaskStatus.completed, completed_at=datetime.now(UTC), output_artifact=task.output_artifact)
        .with_phase(phase, PhaseInfo(status=PhaseStatus.completed))
        .with_event("task_completed", phase=phase, task_id=task.task_id)
    )


_ARTIFACT_RETRY_DELAYS = [2, 5, 10]  # seconds between attempts


async def _download_with_retry(store: ArtifactStore, blob_path: str) -> str | None:
    for attempt, delay in enumerate([0] + _ARTIFACT_RETRY_DELAYS, start=1):
        if delay:
            await asyncio.sleep(delay)
        try:
            return await store.download(blob_path)
        except Exception as exc:
            if attempt <= len(_ARTIFACT_RETRY_DELAYS):
                log.warning(
                    "Artifact %s not yet available (attempt %d), retrying in %ds: %s",
                    blob_path, attempt, _ARTIFACT_RETRY_DELAYS[attempt - 1], exc,
                )
            else:
                log.warning("Could not download artifact %s after %d attempts: %s", blob_path, attempt, exc)
    return None


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
        force=True,
    )
    logging.getLogger("azure").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
