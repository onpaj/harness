"""Tests for per-queue concurrency limiting in the observer."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentharness.models import TaskMessage
from agentharness.observer import _poll_queue, _run_subprocess


def _make_task(task_id: str = "task-1") -> TaskMessage:
    return TaskMessage(
        feature_id="feat-test",
        task_id=task_id,
        input_artifacts=[],
        output_artifact="artifacts/feat-test/impl/task-1.r1.md",
        agent_role="developer",
    )


def _make_raw_msg() -> MagicMock:
    msg = MagicMock()
    msg.message_id = "msg-1"
    return msg


def _make_queue() -> MagicMock:
    q = MagicMock()
    q.delete_message = AsyncMock()
    q.extend_visibility = AsyncMock(return_value=_make_raw_msg())
    q.close = AsyncMock()
    return q


@pytest.mark.asyncio
async def test_run_subprocess_increments_queue_active() -> None:
    """queue_active[queue_name] is 1 while the subprocess runs."""
    task = _make_task()
    queue = _make_queue()
    active_procs: dict = {}
    queue_active: dict[str, int] = {}
    observed_counts: list[int] = []

    async def fake_exec(*args, **kwargs):
        proc = MagicMock()
        proc.pid = 1234
        proc.returncode = 0
        proc.stdin = MagicMock()
        proc.stdin.write = MagicMock()
        proc.stdin.drain = AsyncMock()
        proc.stdin.close = MagicMock()
        proc.wait = AsyncMock(return_value=0)
        observed_counts.append(queue_active.get("developer-queue", 0))
        return proc

    with (
        patch("asyncio.create_subprocess_exec", side_effect=fake_exec),
        patch("agentharness.observer._wait_with_renewal", new_callable=AsyncMock, return_value=_make_raw_msg()),
    ):
        await _run_subprocess("developer-queue", task, _make_raw_msg(), queue, "agentharness", active_procs, queue_active)

    assert observed_counts == [1]


@pytest.mark.asyncio
async def test_run_subprocess_decrements_queue_active_on_completion() -> None:
    """queue_active[queue_name] returns to 0 after subprocess finishes."""
    task = _make_task()
    queue = _make_queue()
    active_procs: dict = {}
    queue_active: dict[str, int] = {}

    async def fake_exec(*args, **kwargs):
        proc = MagicMock()
        proc.pid = 1234
        proc.returncode = 0
        proc.stdin = MagicMock()
        proc.stdin.write = MagicMock()
        proc.stdin.drain = AsyncMock()
        proc.stdin.close = MagicMock()
        proc.wait = AsyncMock(return_value=0)
        return proc

    with (
        patch("asyncio.create_subprocess_exec", side_effect=fake_exec),
        patch("agentharness.observer._wait_with_renewal", new_callable=AsyncMock, return_value=_make_raw_msg()),
    ):
        await _run_subprocess("developer-queue", task, _make_raw_msg(), queue, "agentharness", active_procs, queue_active)

    assert queue_active.get("developer-queue", 0) == 0


@pytest.mark.asyncio
async def test_run_subprocess_decrements_queue_active_on_exception() -> None:
    """queue_active[queue_name] returns to 0 even when subprocess spawning fails."""
    task = _make_task()
    queue = _make_queue()
    active_procs: dict = {}
    queue_active: dict[str, int] = {}

    with patch("asyncio.create_subprocess_exec", side_effect=OSError("spawn failed")):
        await _run_subprocess("developer-queue", task, _make_raw_msg(), queue, "agentharness", active_procs, queue_active)

    assert queue_active.get("developer-queue", 0) == 0


@pytest.mark.asyncio
async def test_poll_queue_skips_receive_when_at_capacity() -> None:
    """_poll_queue does not call receive_task when the queue is already at max_concurrent."""
    from agentharness.config import Config

    config = Config()
    queue = MagicMock()
    queue.receive_task = AsyncMock(return_value=None)
    active_procs: dict = {}
    queue_active: dict[str, int] = {"developer-queue": 1}  # already at limit

    sleep_calls = 0

    async def mock_sleep(delay: float) -> None:
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls >= 2:
            raise asyncio.CancelledError

    with patch("asyncio.sleep", side_effect=mock_sleep):
        with pytest.raises(asyncio.CancelledError):
            await _poll_queue("developer-queue", queue, config, "agentharness", active_procs, queue_active, 1.0, 1)

    queue.receive_task.assert_not_awaited()


@pytest.mark.asyncio
async def test_poll_queue_receives_when_under_capacity() -> None:
    """_poll_queue calls receive_task when the queue is below max_concurrent."""
    from agentharness.config import Config

    config = Config()
    queue = MagicMock()
    queue.receive_task = AsyncMock(return_value=None)
    active_procs: dict = {}
    queue_active: dict[str, int] = {}  # nothing active

    sleep_calls = 0

    async def mock_sleep(delay: float) -> None:
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls >= 1:
            raise asyncio.CancelledError

    with patch("asyncio.sleep", side_effect=mock_sleep):
        with pytest.raises(asyncio.CancelledError):
            await _poll_queue("developer-queue", queue, config, "agentharness", active_procs, queue_active, 1.0, 1)

    queue.receive_task.assert_awaited_once()
