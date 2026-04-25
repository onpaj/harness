"""Azure Blob Storage and Queue client wrappers."""

from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path

from azure.storage.blob.aio import BlobServiceClient
from azure.storage.queue.aio import QueueClient

from agentharness.config import Config
from agentharness.models import TaskMessage


class ArtifactStore:
    """Async wrapper for Azure Blob Storage artifact operations."""

    def __init__(self, blob_service: BlobServiceClient, container: str) -> None:
        self._service = blob_service
        self._container = container

    @classmethod
    def from_config(cls, config: Config) -> ArtifactStore:
        client = BlobServiceClient.from_connection_string(config.storage.connection_string)
        return cls(client, config.storage.container)

    async def upload(self, blob_path: str, content: str | bytes, verify_retries: int = 5, verify_delay: float = 0.5) -> None:
        if isinstance(content, str):
            content = content.encode()
        container = self._service.get_container_client(self._container)
        blob = container.get_blob_client(blob_path)
        await blob.upload_blob(content, overwrite=True)
        for _ in range(verify_retries):
            if await blob.exists():
                return
            await asyncio.sleep(verify_delay)
        raise RuntimeError(f"Blob not available after upload: {blob_path}")

    async def download(self, blob_path: str) -> str:
        container = self._service.get_container_client(self._container)
        blob = container.get_blob_client(blob_path)
        stream = await blob.download_blob()
        data = await stream.readall()
        return data.decode()

    async def exists(self, blob_path: str) -> bool:
        container = self._service.get_container_client(self._container)
        blob = container.get_blob_client(blob_path)
        return await blob.exists()

    async def ensure_container_exists(self) -> None:
        container = self._service.get_container_client(self._container)
        try:
            await container.create_container()
        except Exception:
            pass  # Already exists

    async def close(self) -> None:
        await self._service.close()


class PipelineQueue:
    """Async wrapper for a single Azure Storage Queue."""

    def __init__(self, queue_client: QueueClient) -> None:
        self._client = queue_client

    @classmethod
    def from_connection_string(cls, connection_string: str, queue_name: str) -> PipelineQueue:
        client = QueueClient.from_connection_string(connection_string, queue_name)
        return cls(client)

    async def send_task(self, task: TaskMessage, visibility_timeout: int = 0) -> None:
        payload = base64.b64encode(task.model_dump_json().encode()).decode()
        await self._client.send_message(payload, visibility_timeout=visibility_timeout)

    async def receive_task(self, visibility_timeout: int = 30) -> tuple[TaskMessage, object] | None:
        """Return (task, raw_message) or None if queue is empty."""
        messages = self._client.receive_messages(messages_per_page=1, visibility_timeout=visibility_timeout)
        async for msg in messages:
            try:
                payload = base64.b64decode(msg.content).decode()
                task = TaskMessage.model_validate_json(payload)
                return task, msg
            except Exception as exc:
                raise ValueError(f"Failed to parse queue message: {exc}") from exc
        return None

    async def delete_message(self, message: object) -> None:
        await self._client.delete_message(message)

    async def move_to_dead_letter(
        self, message: object, dead_letter_queue_name: str, connection_string: str
    ) -> None:
        dl_queue = QueueClient.from_connection_string(connection_string, dead_letter_queue_name)
        try:
            await dl_queue.create_queue()
        except Exception:
            pass
        await dl_queue.send_message(message.content)
        await self._client.delete_message(message)

    async def purge(self) -> None:
        await self._client.clear_messages()

    async def ensure_exists(self) -> None:
        try:
            await self._client.create_queue()
        except Exception:
            pass

    async def close(self) -> None:
        await self._client.close()


def artifact_path(feature_id: str, name: str) -> str:
    return f"artifacts/{feature_id}/{name}"


def impl_artifact_path(feature_id: str, task_name: str, revision: int) -> str:
    return f"artifacts/{feature_id}/impl/{task_name}.r{revision}.md"


def review_artifact_path(feature_id: str, revision: int) -> str:
    return f"artifacts/{feature_id}/review/review.r{revision}.md"


def phase_artifact_path(feature_id: str, phase_name: str, revision: int) -> str:
    return f"artifacts/{feature_id}/{phase_name}.r{revision}.md"


def state_blob_path(feature_id: str) -> str:
    return f"artifacts/{feature_id}/state.json"
