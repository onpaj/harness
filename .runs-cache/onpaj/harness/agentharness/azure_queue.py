"""Azure Storage Queue implementation of TaskQueue."""

from __future__ import annotations

import base64

from azure.storage.queue.aio import QueueClient

from agentharness.models import TaskMessage
from agentharness.storage_protocol import RawMessage


class AzureTaskQueue:
    """Async wrapper for a single Azure Storage Queue."""

    def __init__(self, queue_client: QueueClient) -> None:
        self._client = queue_client

    @classmethod
    def from_connection_string(cls, connection_string: str, queue_name: str) -> AzureTaskQueue:
        client = QueueClient.from_connection_string(connection_string, queue_name)
        return cls(client)

    async def send_task(self, task: TaskMessage, visibility_timeout: int = 0) -> None:
        payload = base64.b64encode(task.model_dump_json().encode()).decode()
        await self._client.send_message(payload, visibility_timeout=visibility_timeout)

    async def receive_task(self, visibility_timeout: int = 30) -> tuple[TaskMessage, RawMessage] | None:
        messages = self._client.receive_messages(messages_per_page=1, visibility_timeout=visibility_timeout)
        async for msg in messages:
            try:
                payload = base64.b64decode(msg.content).decode()
                task = TaskMessage.model_validate_json(payload)
                raw = RawMessage(
                    id=msg.id,
                    pop_receipt=msg.pop_receipt,
                    content=msg.content,
                    dequeue_count=msg.dequeue_count,
                )
                return task, raw
            except Exception as exc:
                raise ValueError(f"Failed to parse queue message: {exc}") from exc
        return None

    async def delete_message(self, raw: RawMessage) -> None:
        await self._client.delete_message(raw.id, pop_receipt=raw.pop_receipt)

    async def extend_visibility(self, raw: RawMessage, timeout: int) -> RawMessage:
        result = await self._client.update_message(
            raw.id,
            pop_receipt=raw.pop_receipt,
            visibility_timeout=timeout,
        )
        return RawMessage(
            id=raw.id,
            pop_receipt=result.pop_receipt,
            content=raw.content,
            dequeue_count=raw.dequeue_count,
        )

    async def move_to_dead_letter(
        self, raw: RawMessage, dead_letter_queue_name: str, connection_string: str
    ) -> None:
        dl_queue = QueueClient.from_connection_string(connection_string, dead_letter_queue_name)
        try:
            await dl_queue.create_queue()
        except Exception:
            pass
        await dl_queue.send_message(raw.content)
        await self.delete_message(raw)

    async def purge(self) -> None:
        await self._client.clear_messages()

    async def ensure_exists(self) -> None:
        try:
            await self._client.create_queue()
        except Exception:
            pass

    async def get_depth(self) -> int:
        props = await self._client.get_queue_properties()
        return props.get("approximate_message_count", 0)

    async def close(self) -> None:
        await self._client.close()
