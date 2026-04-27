"""GitHub Issues-as-queue implementation of the TaskQueue protocol.

Each task is represented as a GitHub Issue with labels for queue routing,
state, and worker claim. Workers claim issues by swapping state:queued →
state:in-progress and posting a heartbeat comment.
"""

from __future__ import annotations

import json
import os
import re
import socket
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentharness.github_labels import (
    CLAIMED_BY_PREFIX,
    FEATURE_MARKER,
    QUEUE_NAME_TO_LABEL,
    STATE_BLOCKED,
    STATE_COMPLETED,
    STATE_DEAD_LETTER,
    STATE_IN_PROGRESS,
    STATE_QUEUED,
    TASK_STATE_LABELS,
    claimed_by_label,
    is_claimed_by_label,
)
from agentharness.models import TaskMessage
from agentharness.storage_protocol import RawMessage

if TYPE_CHECKING:
    from agentharness.config import Config
    from agentharness.github_client import GitHubClient

# Fence tag used to embed TaskMessage JSON in issue bodies
_TASK_FENCE = "agentharness-task"
_RECLAIM_MARKER = "⚠️ Reclaimed"


def _default_worker_id() -> str:
    return f"{socket.gethostname()}-{os.getpid()}"


def _build_issue_body(task: TaskMessage) -> str:
    task_json = task.model_dump_json(indent=2)
    return (
        f"Task: {task.task_id}\n\n"
        f"```{_TASK_FENCE}\n{task_json}\n```"
    )


def _parse_task_from_body(body: str) -> TaskMessage:
    pattern = rf"```{_TASK_FENCE}\n(.*?)```"
    match = re.search(pattern, body, re.DOTALL)
    if not match:
        raise ValueError(f"No {_TASK_FENCE} fenced block found in issue body")
    return TaskMessage.model_validate_json(match.group(1).strip())


def _iso_utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _count_reclaims(comments: list[dict]) -> int:
    return sum(1 for c in comments if _RECLAIM_MARKER in c.get("body", ""))


class GitHubTaskQueue:
    """TaskQueue backed by GitHub Issues with label-based state transitions."""

    def __init__(
        self,
        client: GitHubClient,
        queue_name: str,
        worker_id: str,
    ) -> None:
        self._client = client
        self._queue_name = queue_name
        self._worker_id = worker_id
        self._queue_label = QUEUE_NAME_TO_LABEL.get(queue_name, f"queue:{queue_name}")

    @classmethod
    def from_config(cls, config: Config, queue_name: str) -> GitHubTaskQueue:
        from agentharness.github_client import GitHubClient

        client = GitHubClient.from_config(config)
        return cls(
            client=client,
            queue_name=queue_name,
            worker_id=_default_worker_id(),
        )

    # ------------------------------------------------------------------
    # Send
    # ------------------------------------------------------------------

    async def send_task(self, task: TaskMessage, visibility_timeout: int = 0) -> None:
        """Create a GitHub issue representing the enqueued task."""
        state_label = STATE_BLOCKED if visibility_timeout > 0 else STATE_QUEUED
        labels = [self._queue_label, state_label, FEATURE_MARKER]
        title = f"[{self._queue_name}] {task.task_id}"
        body = _build_issue_body(task)
        await self._client.create_issue(title=title, body=body, labels=labels)

    # ------------------------------------------------------------------
    # Receive
    # ------------------------------------------------------------------

    async def receive_task(
        self, visibility_timeout: int = 30
    ) -> tuple[TaskMessage, RawMessage] | None:
        """Claim the oldest queued issue and return (TaskMessage, RawMessage).

        Returns None if the queue has no available tasks.
        """
        query = (
            f"is:open label:{self._queue_label} label:{STATE_QUEUED} "
            f"repo:{self._client.owner}/{self._client.repo}"
        )
        issues = await self._client.search_issues(query, sort="created", order="asc")
        if not issues:
            return None

        issue = issues[0]
        number: int = issue["number"]
        raw_body: str = issue.get("body") or ""

        # Transition: state:queued → state:in-progress + claimed-by:{worker_id}
        await self._client.remove_label(number, STATE_QUEUED)
        await self._client.add_labels(
            number, [STATE_IN_PROGRESS, claimed_by_label(self._worker_id)]
        )

        # Post heartbeat comment
        timestamp = _iso_utc_now()
        heartbeat_body = (
            f"⏱ Heartbeat: {timestamp}\n\nWorker: {self._worker_id}"
        )
        comment = await self._client.create_comment(number, heartbeat_body)
        comment_id: int = comment["id"]

        # Count prior reclaims to approximate dequeue_count
        all_comments: list[dict] = issue.get("comments", [])
        reclaim_count = _count_reclaims(all_comments)

        task = _parse_task_from_body(raw_body)
        raw = RawMessage(
            id=str(number),
            pop_receipt=str(comment_id),
            content=raw_body,
            dequeue_count=reclaim_count,
        )
        return task, raw

    # ------------------------------------------------------------------
    # Extend visibility (heartbeat update)
    # ------------------------------------------------------------------

    async def extend_visibility(self, raw: RawMessage, timeout: int) -> RawMessage:
        """Update the heartbeat comment with a fresh timestamp."""
        comment_id = int(raw.pop_receipt)
        timestamp = _iso_utc_now()
        new_body = (
            f"⏱ Heartbeat: {timestamp}\n\nWorker: {self._worker_id}"
        )
        await self._client.update_comment(comment_id, new_body)
        return raw

    # ------------------------------------------------------------------
    # Delete (success path)
    # ------------------------------------------------------------------

    async def delete_message(self, raw: RawMessage) -> None:
        """Mark the issue completed and close it."""
        number = int(raw.id)
        issue = await self._client.get_issue(number)
        current_labels = [lbl["name"] for lbl in issue.get("labels", [])]

        # Remove in-progress + any claimed-by labels
        labels_to_remove = [
            lbl for lbl in current_labels
            if lbl == STATE_IN_PROGRESS or is_claimed_by_label(lbl)
        ]
        for lbl in labels_to_remove:
            await self._client.remove_label(number, lbl)

        await self._client.add_labels(number, [STATE_COMPLETED])
        await self._client.update_issue(number, state="closed")

    # ------------------------------------------------------------------
    # Dead letter
    # ------------------------------------------------------------------

    async def move_to_dead_letter(
        self,
        raw: RawMessage,
        dead_letter_queue_name: str,
        connection_string: str,
    ) -> None:
        """Move issue to dead-letter state and close it."""
        number = int(raw.id)
        issue = await self._client.get_issue(number)
        current_labels = [lbl["name"] for lbl in issue.get("labels", [])]

        labels_to_remove = [
            lbl for lbl in current_labels
            if lbl == STATE_IN_PROGRESS or is_claimed_by_label(lbl)
        ]
        for lbl in labels_to_remove:
            await self._client.remove_label(number, lbl)

        await self._client.add_labels(number, [STATE_DEAD_LETTER])
        await self._client.create_comment(
            number, "⚠️ Dead-lettered after max retries"
        )
        await self._client.update_issue(number, state="closed")

    # ------------------------------------------------------------------
    # Purge
    # ------------------------------------------------------------------

    async def purge(self) -> None:
        """Close all open issues with the queue label."""
        query = (
            f"is:open label:{self._queue_label} "
            f"repo:{self._client.owner}/{self._client.repo}"
        )
        issues = await self._client.search_issues(query)
        for issue in issues:
            await self._client.update_issue(issue["number"], state="closed")

    # ------------------------------------------------------------------
    # Ensure exists (idempotent label creation)
    # ------------------------------------------------------------------

    async def ensure_exists(self) -> None:
        """Ensure all labels used by this queue exist in the repository."""
        labels_needed = [
            self._queue_label,
            STATE_QUEUED,
            STATE_IN_PROGRESS,
            STATE_COMPLETED,
            STATE_DEAD_LETTER,
            STATE_BLOCKED,
            FEATURE_MARKER,
        ]
        for label in labels_needed:
            await self._client.ensure_label(label)

    # ------------------------------------------------------------------
    # Depth
    # ------------------------------------------------------------------

    async def get_depth(self) -> int:
        """Return the number of open queued issues for this queue."""
        query = (
            f"is:open label:{self._queue_label} label:{STATE_QUEUED} "
            f"repo:{self._client.owner}/{self._client.repo}"
        )
        issues = await self._client.search_issues(query)
        return len(issues)

    # ------------------------------------------------------------------
    # Close
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.close()
