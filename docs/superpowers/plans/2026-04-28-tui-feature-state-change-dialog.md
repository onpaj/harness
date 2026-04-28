# TUI Feature State Change Dialog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Textual modal dialog (triggered by `S`) that lets operators atomically restart, roll back, or fail any in-flight feature without touching storage by hand.

**Architecture:** Three layers — (1) a UI-only `StateChangeModal` (no I/O) that emits a `StateChangeResult`, (2) a headless `apply_state_change` service that orchestrates `StateBackend.update()` + `build_phase_task()` + queue send, and (3) a thin `tui.py` glue handler. The dispatcher's existing `STATE_TO_QUEUE` and `build_phase_task()` are reused so rollback never duplicates forward-state logic.

**Tech Stack:** Python 3.12+, Textual (`ModalScreen`, `ListView`, `Binding`), Pydantic models, `pytest-asyncio`, existing `StateBackend`/`TaskQueue` Protocols.

---

## File Structure

| Path | Status | Responsibility |
|------|--------|----------------|
| `agentharness/state_change.py` | NEW | `StateChangeMode`, `StateChangeResult`, `StateChangeError`, `CLEAR_TASKS_STATES`, `apply_state_change()`. Headless — no Textual imports. |
| `agentharness/tui_state_change.py` | NEW | `StateChangeModal(ModalScreen)`, `CANONICAL_STATE_ORDER`, `_options_for()`. UI only — no storage imports. |
| `agentharness/tui.py` | MODIFY | Add `Binding("s", "open_state_change", "Change state")`, `action_open_state_change`, `_do_apply_state_change` worker. |
| `tests/test_state_change.py` | NEW | All `apply_state_change` paths: fail, restart, rollback (clear/keep tasks), no-queue, mutator idempotency, enqueue retry. |
| `tests/test_tui_state_change.py` | NEW | Table-driven tests for `_options_for()`. No Textual runtime. |

**Prerequisites — already in the codebase, do not re-implement:**
- `agentharness/dispatcher.py`: `STATE_TO_QUEUE`, `queue_for_state()`, `build_phase_task()` (commits `7863ae5`, `e1f59e5`).
- `agentharness/models.py`: `FeatureState.with_status()`, `with_event()`, `with_tasks_cleared()`, `with_tasks_added()` (commit `e3a8498`).
- `agentharness/storage_protocol.py`: `StateBackend.update(feature_id, mutator)` returning the persisted snapshot, `TaskQueue.send_task(task)`.
- `agentharness/storage.py`: `create_state_manager(config)`, `create_task_queue(config, name)` factories.

If any of those are missing, **stop** and surface the gap before continuing.

---

## Task 1: Verify prerequisites with a smoke import

Confirm the helpers we depend on actually exist before writing new code. This is a 30-second pre-flight check, not a placeholder.

**Files:**
- Read: `agentharness/models.py`
- Read: `agentharness/dispatcher.py`
- Read: `agentharness/storage_protocol.py`

- [ ] **Step 1: Verify model helpers exist**

Run: `python -c "from agentharness.models import FeatureState, FeatureStatus; s = FeatureState(feature_id='x'); s.with_status(FeatureStatus.planning).with_tasks_cleared().with_event('e', details='d')"`
Expected: exits 0 with no output. If it fails, the prerequisite from commit `e3a8498` is not present — stop and report.

- [ ] **Step 2: Verify dispatcher helpers exist**

Run: `python -c "from agentharness.dispatcher import STATE_TO_QUEUE, queue_for_state, build_phase_task; from agentharness.models import FeatureStatus; assert queue_for_state(FeatureStatus.planning) == 'planner-queue'; assert queue_for_state(FeatureStatus.failed) is None"`
Expected: exits 0 with no output. If it fails, prerequisites from `7863ae5`/`e1f59e5` are not present — stop and report.

- [ ] **Step 3: Verify storage protocol shape**

Run: `python -c "from agentharness.storage_protocol import StateBackend, TaskQueue; assert hasattr(StateBackend, 'update'); assert hasattr(TaskQueue, 'send_task')"`
Expected: exits 0 with no output.

- [ ] **Step 4: Run the existing test suite (baseline green)**

Run: `pytest tests/ -q`
Expected: all existing tests pass. Note any pre-existing failures so we don't blame them on our changes later.

---

## Task 2: Skeleton of `state_change.py` — types and constants

Write the type surface first so test files can import. No business logic yet.

**Files:**
- Create: `agentharness/state_change.py`
- Test: `tests/test_state_change.py`

- [ ] **Step 1: Write the failing test for the constant set**

Create `tests/test_state_change.py` with this content:

```python
"""Unit tests for state_change.apply_state_change."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from agentharness.models import (
    FeatureState,
    FeatureStatus,
    TaskEntry,
    TaskMessage,
    TaskStatus,
)
from agentharness.state_change import (
    CLEAR_TASKS_STATES,
    StateChangeError,
    StateChangeMode,
    StateChangeResult,
    apply_state_change,
)


class TestConstants:
    def test_clear_tasks_states_covers_brainstorming_through_planning(self):
        assert CLEAR_TASKS_STATES == frozenset({
            FeatureStatus.brainstorming,
            FeatureStatus.brainstormed,
            FeatureStatus.analyzing,
            FeatureStatus.architecting,
            FeatureStatus.designing,
            FeatureStatus.planning,
        })

    def test_clear_tasks_states_excludes_developing_and_later(self):
        for s in (FeatureStatus.developing, FeatureStatus.dev_revision,
                  FeatureStatus.reviewing, FeatureStatus.done, FeatureStatus.failed):
            assert s not in CLEAR_TASKS_STATES
```

- [ ] **Step 2: Run test to verify it fails with ImportError**

Run: `pytest tests/test_state_change.py::TestConstants -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'agentharness.state_change'`.

- [ ] **Step 3: Create the minimal module to make imports succeed**

Create `agentharness/state_change.py`:

```python
"""Headless service for operator-driven feature state changes.

Used by the TUI's `S` shortcut (and any future CLI/web surface). Owns the
single atomic mutation through `StateBackend.update()` plus the follow-up
queue enqueue. No Textual or UI imports — fully unit-testable.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Callable, Literal

from agentharness.config import Config
from agentharness.dispatcher import build_phase_task, queue_for_state
from agentharness.models import FeatureState, FeatureStatus
from agentharness.storage_protocol import StateBackend, TaskQueue

log = logging.getLogger(__name__)

StateChangeMode = Literal["restart", "rollback", "fail"]

CLEAR_TASKS_STATES: frozenset[FeatureStatus] = frozenset({
    FeatureStatus.brainstorming,
    FeatureStatus.brainstormed,
    FeatureStatus.analyzing,
    FeatureStatus.architecting,
    FeatureStatus.designing,
    FeatureStatus.planning,
})

_ENQUEUE_RETRY_DELAY_SECONDS = 1.0


@dataclass(frozen=True)
class StateChangeResult:
    target_status: FeatureStatus
    mode: StateChangeMode


class StateChangeError(Exception):
    def __init__(self, message: str, persisted_status: FeatureStatus) -> None:
        super().__init__(message)
        self.persisted_status = persisted_status


QueueFactory = Callable[[str], TaskQueue]


async def apply_state_change(
    feature_id: str,
    result: StateChangeResult,
    *,
    state_mgr: StateBackend,
    queue_factory: QueueFactory,
    config: Config,
) -> None:
    """Stub — implemented in later tasks."""
    raise NotImplementedError
```

- [ ] **Step 4: Run test to verify the constant test passes**

Run: `pytest tests/test_state_change.py::TestConstants -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add agentharness/state_change.py tests/test_state_change.py
git commit -m "feat(state-change): scaffold state_change module with types and constants"
```

---

## Task 3: Implement `apply_state_change` — `fail` mode

The simplest path: status → `failed`, no enqueue, append audit event.

**Files:**
- Modify: `agentharness/state_change.py`
- Modify: `tests/test_state_change.py`

- [ ] **Step 1: Add the fail-mode tests and shared helpers**

Append to `tests/test_state_change.py`:

```python
def _make_state_mgr(initial: FeatureState):
    """AsyncMock that simulates StateBackend.update via a mutator closure."""
    state = {"value": initial}

    async def fake_update(feature_id, mutator):
        state["value"] = mutator(state["value"])
        return state["value"]

    async def fake_get(feature_id):
        return state["value"]

    mgr = AsyncMock()
    mgr.update.side_effect = fake_update
    mgr.get.side_effect = fake_get
    mgr._state_ref = state
    return mgr


def _make_queue_factory():
    queues: dict[str, AsyncMock] = {}

    def factory(name: str):
        if name not in queues:
            q = AsyncMock()
            q.send_task = AsyncMock()
            q.close = AsyncMock()
            queues[name] = q
        return queues[name]

    factory.queues = queues  # type: ignore[attr-defined]
    return factory


def _config():
    cfg = MagicMock()
    from pathlib import Path
    agent_paths = {
        "analyst-queue":   Path(".agents/analyst.md"),
        "architect-queue": Path(".agents/architect.md"),
        "designer-queue":  Path(".agents/designer.md"),
        "planner-queue":   Path(".agents/planner.md"),
        "developer-queue": Path(".agents/developer.md"),
        "review-queue":    Path(".agents/reviewer.md"),
    }
    cfg.agent_path_for_queue.side_effect = lambda q: agent_paths[q]
    return cfg


@pytest.mark.asyncio
class TestApplyStateChangeFail:
    async def test_sets_status_to_failed_and_does_not_enqueue(self):
        initial = FeatureState(feature_id="feat-x", status=FeatureStatus.developing)
        mgr = _make_state_mgr(initial)
        factory = _make_queue_factory()

        await apply_state_change(
            "feat-x",
            StateChangeResult(target_status=FeatureStatus.failed, mode="fail"),
            state_mgr=mgr, queue_factory=factory, config=_config(),
        )

        persisted = mgr._state_ref["value"]
        assert persisted.status == FeatureStatus.failed
        assert factory.queues == {}

    async def test_appends_history_event_with_metadata(self):
        initial = FeatureState(feature_id="feat-x", status=FeatureStatus.developing)
        mgr = _make_state_mgr(initial)

        await apply_state_change(
            "feat-x",
            StateChangeResult(target_status=FeatureStatus.failed, mode="fail"),
            state_mgr=mgr, queue_factory=_make_queue_factory(), config=_config(),
        )

        evt = mgr._state_ref["value"].history[-1]
        assert evt.event == "manual_state_change"
        details = json.loads(evt.details)
        assert details["from"] == "developing"
        assert details["to"] == "failed"
        assert details["mode"] == "fail"
        assert details["actor"] == "tui"
```

- [ ] **Step 2: Run tests — expect failures (NotImplementedError)**

Run: `pytest tests/test_state_change.py::TestApplyStateChangeFail -q`
Expected: FAIL with `NotImplementedError`.

- [ ] **Step 3: Implement `apply_state_change` with fail/restart/rollback branches**

Replace the body of `apply_state_change` in `agentharness/state_change.py` with:

```python
async def apply_state_change(
    feature_id: str,
    result: StateChangeResult,
    *,
    state_mgr: StateBackend,
    queue_factory: QueueFactory,
    config: Config,
) -> None:
    """Atomically transition a feature and enqueue the follow-up phase task.

    Contract:
      - One state_mgr.update() call. The closure may run multiple times under
        lease contention; it always rebuilds the new state from the fresh
        snapshot, so retries do not duplicate the audit event.
      - Skips enqueue when the target maps to None (failed / brainstorming /
        brainstormed / done). Restart of a status that maps to a queue still
        enqueues (e.g. restart developing → developer-queue).
      - On enqueue failure: retries once with 1s backoff; if it still fails,
        raises StateChangeError carrying the persisted status.
    """

    def mutator(snapshot: FeatureState) -> FeatureState:
        prev_status = snapshot.status
        will_clear = (
            result.mode == "rollback"
            and result.target_status in CLEAR_TASKS_STATES
        )
        details = json.dumps({
            "from":          prev_status.value,
            "to":            result.target_status.value,
            "mode":          result.mode,
            "tasks_cleared": will_clear,
            "actor":         "tui",
        })

        if result.mode == "fail":
            return snapshot.with_status(FeatureStatus.failed).with_event(
                "manual_state_change", details=details
            )
        if result.mode == "restart":
            return snapshot.with_event("manual_state_change", details=details)
        # rollback
        new_state = snapshot.with_status(result.target_status)
        if will_clear:
            new_state = new_state.with_tasks_cleared()
        return new_state.with_event("manual_state_change", details=details)

    persisted: FeatureState = await state_mgr.update(feature_id, mutator)

    queue_name = queue_for_state(persisted.status)
    if queue_name is None:
        log.info(
            "apply_state_change: status %s has no queue — skipping enqueue",
            persisted.status.value,
        )
        return

    task = build_phase_task(persisted, persisted.status, config)
    queue = queue_factory(queue_name)
    last_exc: Exception | None = None
    try:
        for attempt in range(2):
            if attempt > 0:
                await asyncio.sleep(_ENQUEUE_RETRY_DELAY_SECONDS)
            try:
                await queue.send_task(task)
                log.info(
                    "apply_state_change: enqueued %s on %s",
                    task.task_id, queue_name,
                )
                return
            except Exception as exc:
                last_exc = exc
                log.warning(
                    "apply_state_change: enqueue attempt %d/2 failed: %s",
                    attempt + 1, exc,
                )
        raise StateChangeError(
            f"State persisted but enqueue on {queue_name!r} failed after 2 attempts: {last_exc}",
            persisted_status=persisted.status,
        )
    finally:
        try:
            await queue.close()
        except Exception:
            pass
```

- [ ] **Step 4: Run the fail tests — they should pass**

Run: `pytest tests/test_state_change.py::TestApplyStateChangeFail -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add agentharness/state_change.py tests/test_state_change.py
git commit -m "feat(state-change): implement apply_state_change with fail mode + audit event"
```

---

## Task 4: Tests for `restart` mode

Restart leaves status untouched, appends an audit event, and re-enqueues the existing phase queue.

**Files:**
- Modify: `tests/test_state_change.py`

- [ ] **Step 1: Append the restart tests**

Append to `tests/test_state_change.py`:

```python
@pytest.mark.asyncio
class TestApplyStateChangeRestart:
    async def test_keeps_status_unchanged_and_enqueues(self):
        existing = TaskMessage(
            feature_id="feat-x",
            task_id="feat-x-dev-auth-r1",
            input_artifacts=[],
            output_artifact="artifacts/feat-x/impl/auth.r1.md",
            agent_role="developer",
            context="auth",
        )
        entry = TaskEntry(
            task_id=existing.task_id,
            phase="developing",
            status=TaskStatus.in_progress,
            queued_message=existing.model_dump(),
        )
        initial = FeatureState(
            feature_id="feat-x", status=FeatureStatus.developing
        ).with_tasks_added([entry])
        mgr = _make_state_mgr(initial)
        factory = _make_queue_factory()

        await apply_state_change(
            "feat-x",
            StateChangeResult(target_status=FeatureStatus.developing, mode="restart"),
            state_mgr=mgr, queue_factory=factory, config=_config(),
        )

        persisted = mgr._state_ref["value"]
        assert persisted.status == FeatureStatus.developing
        assert "developer-queue" in factory.queues
        factory.queues["developer-queue"].send_task.assert_awaited_once()
```

- [ ] **Step 2: Run the test — should pass without code changes**

Run: `pytest tests/test_state_change.py::TestApplyStateChangeRestart -q`
Expected: PASS.

(The implementation from Task 3 already covers restart. We add the test to lock the contract.)

- [ ] **Step 3: Commit**

```bash
git add tests/test_state_change.py
git commit -m "test(state-change): cover restart mode preserves status and enqueues"
```

---

## Task 5: Tests for `rollback` mode (clear and preserve variants)

Rollback to ≤ planning clears `tasks`; rollback to developing/reviewing/dev_revision preserves them.

**Files:**
- Modify: `tests/test_state_change.py`

- [ ] **Step 1: Append the rollback tests**

```python
@pytest.mark.asyncio
class TestApplyStateChangeRollback:
    async def test_rollback_to_planning_clears_tasks(self):
        entry = TaskEntry(task_id="feat-x-dev-a", phase="developing",
                          status=TaskStatus.in_progress)
        initial = FeatureState(
            feature_id="feat-x", status=FeatureStatus.developing
        ).with_tasks_added([entry])
        mgr = _make_state_mgr(initial)
        factory = _make_queue_factory()

        await apply_state_change(
            "feat-x",
            StateChangeResult(target_status=FeatureStatus.planning, mode="rollback"),
            state_mgr=mgr, queue_factory=factory, config=_config(),
        )

        persisted = mgr._state_ref["value"]
        assert persisted.status == FeatureStatus.planning
        assert persisted.tasks == []
        assert "planner-queue" in factory.queues

    async def test_rollback_to_reviewing_does_not_clear_tasks(self):
        existing = TaskMessage(
            feature_id="feat-x",
            task_id="feat-x-dev-auth-r1",
            input_artifacts=[],
            output_artifact="artifacts/feat-x/impl/auth.r1.md",
            agent_role="developer",
            context="auth",
        )
        entry = TaskEntry(
            task_id=existing.task_id,
            phase="developing",
            status=TaskStatus.in_progress,
            queued_message=existing.model_dump(),
        )
        initial = FeatureState(
            feature_id="feat-x", status=FeatureStatus.dev_revision
        ).with_tasks_added([entry])
        mgr = _make_state_mgr(initial)
        factory = _make_queue_factory()

        await apply_state_change(
            "feat-x",
            StateChangeResult(target_status=FeatureStatus.reviewing, mode="rollback"),
            state_mgr=mgr, queue_factory=factory, config=_config(),
        )

        persisted = mgr._state_ref["value"]
        assert persisted.status == FeatureStatus.reviewing
        assert len(persisted.tasks) == 1
        assert "review-queue" in factory.queues

    async def test_rollback_to_brainstorming_does_not_enqueue(self):
        initial = FeatureState(feature_id="feat-x", status=FeatureStatus.analyzing)
        mgr = _make_state_mgr(initial)
        factory = _make_queue_factory()

        await apply_state_change(
            "feat-x",
            StateChangeResult(target_status=FeatureStatus.brainstorming, mode="rollback"),
            state_mgr=mgr, queue_factory=factory, config=_config(),
        )

        persisted = mgr._state_ref["value"]
        assert persisted.status == FeatureStatus.brainstorming
        assert factory.queues == {}

    async def test_rollback_records_tasks_cleared_in_event_details(self):
        entry = TaskEntry(task_id="feat-x-dev-a", phase="developing")
        initial = FeatureState(
            feature_id="feat-x", status=FeatureStatus.developing
        ).with_tasks_added([entry])
        mgr = _make_state_mgr(initial)

        await apply_state_change(
            "feat-x",
            StateChangeResult(target_status=FeatureStatus.planning, mode="rollback"),
            state_mgr=mgr, queue_factory=_make_queue_factory(), config=_config(),
        )

        evt = mgr._state_ref["value"].history[-1]
        details = json.loads(evt.details)
        assert details["tasks_cleared"] is True
        assert details["mode"] == "rollback"
```

- [ ] **Step 2: Run the rollback tests**

Run: `pytest tests/test_state_change.py::TestApplyStateChangeRollback -q`
Expected: PASS (4 tests).

- [ ] **Step 3: Commit**

```bash
git add tests/test_state_change.py
git commit -m "test(state-change): cover rollback (clear/preserve tasks, no-queue, event audit)"
```

---

## Task 6: Test mutator idempotency under lease retry

Azure's `StateManager.update` may invoke the mutator multiple times under blob-lease contention. Each invocation must produce the same shape from the snapshot it receives — never a cumulative one.

**Files:**
- Modify: `tests/test_state_change.py`

- [ ] **Step 1: Append the idempotency test**

```python
@pytest.mark.asyncio
class TestApplyStateChangeIdempotencyUnderRetry:
    async def test_closure_appends_only_one_event_when_invoked_twice(self):
        """Simulate lease contention: update calls mutator twice, keeps last."""
        initial = FeatureState(feature_id="feat-x", status=FeatureStatus.developing)
        state_holder = {"value": initial}

        async def retry_update(feature_id, mutator):
            mutator(state_holder["value"])  # discarded (lease lost)
            state_holder["value"] = mutator(state_holder["value"])
            return state_holder["value"]

        mgr = AsyncMock()
        mgr.update.side_effect = retry_update

        await apply_state_change(
            "feat-x",
            StateChangeResult(target_status=FeatureStatus.failed, mode="fail"),
            state_mgr=mgr, queue_factory=_make_queue_factory(), config=_config(),
        )

        events = [e for e in state_holder["value"].history
                  if e.event == "manual_state_change"]
        assert len(events) == 1
```

- [ ] **Step 2: Run the test**

Run: `pytest tests/test_state_change.py::TestApplyStateChangeIdempotencyUnderRetry -q`
Expected: PASS.

(The closure already rebuilds from the snapshot argument — the test locks that contract.)

- [ ] **Step 3: Commit**

```bash
git add tests/test_state_change.py
git commit -m "test(state-change): lock mutator idempotency under lease retry"
```

---

## Task 7: Test enqueue retry + `StateChangeError`

Verify two attempts on enqueue, and that the typed exception carries the persisted status.

**Files:**
- Modify: `tests/test_state_change.py`

- [ ] **Step 1: Append the retry test**

```python
@pytest.mark.asyncio
class TestApplyStateChangeEnqueueRetry:
    async def test_retries_once_then_raises_state_change_error(self, monkeypatch):
        existing = TaskMessage(
            feature_id="feat-x",
            task_id="feat-x-dev-a-r1",
            input_artifacts=[],
            output_artifact="artifacts/feat-x/impl/a.r1.md",
            agent_role="developer",
            context="a",
        )
        entry = TaskEntry(
            task_id=existing.task_id, phase="developing",
            status=TaskStatus.in_progress, queued_message=existing.model_dump(),
        )
        initial = FeatureState(
            feature_id="feat-x", status=FeatureStatus.developing
        ).with_tasks_added([entry])
        mgr = _make_state_mgr(initial)

        bad_queue = AsyncMock()
        bad_queue.send_task = AsyncMock(side_effect=RuntimeError("queue down"))
        bad_queue.close = AsyncMock()

        def factory(name):
            return bad_queue

        import agentharness.state_change as sc
        monkeypatch.setattr(sc.asyncio, "sleep", AsyncMock())

        with pytest.raises(StateChangeError) as exc_info:
            await apply_state_change(
                "feat-x",
                StateChangeResult(target_status=FeatureStatus.developing, mode="restart"),
                state_mgr=mgr, queue_factory=factory, config=_config(),
            )

        assert exc_info.value.persisted_status == FeatureStatus.developing
        assert bad_queue.send_task.await_count == 2
```

- [ ] **Step 2: Run the test**

Run: `pytest tests/test_state_change.py::TestApplyStateChangeEnqueueRetry -q`
Expected: PASS.

- [ ] **Step 3: Run the full state_change suite to lock all paths**

Run: `pytest tests/test_state_change.py -q`
Expected: PASS — 11 tests (2 constants + 2 fail + 1 restart + 4 rollback + 1 idempotency + 1 retry).

- [ ] **Step 4: Commit**

```bash
git add tests/test_state_change.py
git commit -m "test(state-change): assert two-attempt enqueue retry then StateChangeError"
```

---

## Task 8: `tui_state_change.py` — `_options_for()` pure function

Build the test surface for the modal first, before any Textual rendering.

**Files:**
- Create: `agentharness/tui_state_change.py`
- Create: `tests/test_tui_state_change.py`

- [ ] **Step 1: Write the failing tests for `_options_for`**

Create `tests/test_tui_state_change.py`:

```python
"""Pure-logic tests for StateChangeModal._options_for. Textual rendering is
covered by manual smoke testing — headless Textual pilot tests add CI weight
without much value for a static list."""
from __future__ import annotations

import pytest

from agentharness.models import FeatureState, FeatureStatus
from agentharness.tui_state_change import StateChangeModal


def _state(status: FeatureStatus) -> FeatureState:
    return FeatureState(feature_id="feat-x", status=status)


class TestOptionsFor:
    def test_includes_all_states_up_to_and_including_current(self):
        opts = StateChangeModal._options_for(_state(FeatureStatus.developing))
        statuses = [s for s, _, _ in opts if s != FeatureStatus.failed]
        assert statuses == [
            FeatureStatus.brainstorming,
            FeatureStatus.brainstormed,
            FeatureStatus.analyzing,
            FeatureStatus.architecting,
            FeatureStatus.designing,
            FeatureStatus.planning,
            FeatureStatus.developing,
        ]

    def test_appends_failed_at_end(self):
        opts = StateChangeModal._options_for(_state(FeatureStatus.developing))
        last_status, last_mode, _ = opts[-1]
        assert last_status == FeatureStatus.failed
        assert last_mode == "fail"

    def test_marks_current_state_as_restart(self):
        opts = StateChangeModal._options_for(_state(FeatureStatus.developing))
        current = next((s, m, lbl) for s, m, lbl in opts if s == FeatureStatus.developing)
        _, mode, label = current
        assert mode == "restart"
        assert "current" in label and "restart" in label

    def test_earlier_states_are_rollback(self):
        opts = StateChangeModal._options_for(_state(FeatureStatus.developing))
        for status, mode, label in opts:
            if status in (FeatureStatus.failed, FeatureStatus.developing):
                continue
            assert mode == "rollback"
            assert "rollback" in label

    def test_for_brainstorming_only_self_and_failed(self):
        opts = StateChangeModal._options_for(_state(FeatureStatus.brainstorming))
        assert [s for s, _, _ in opts] == [
            FeatureStatus.brainstorming, FeatureStatus.failed,
        ]

    def test_dev_revision_appears_in_order_for_dev_revision_state(self):
        opts = StateChangeModal._options_for(_state(FeatureStatus.dev_revision))
        statuses = [s for s, _, _ in opts]
        assert FeatureStatus.developing in statuses
        assert FeatureStatus.dev_revision in statuses
        idx = next(i for i, (s, _, _) in enumerate(opts)
                   if s == FeatureStatus.dev_revision)
        _, mode, _ = opts[idx]
        assert mode == "restart"

    def test_done_features_yield_only_failed_row(self):
        """Defensive: TUI guards on done before opening the modal, but the
        helper itself must not crash. It returns just the failed row."""
        opts = StateChangeModal._options_for(_state(FeatureStatus.done))
        assert all(s != FeatureStatus.done for s, _, _ in opts)
        assert opts[-1][0] == FeatureStatus.failed
```

- [ ] **Step 2: Run tests — expect ImportError**

Run: `pytest tests/test_tui_state_change.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'agentharness.tui_state_change'`.

- [ ] **Step 3: Create `tui_state_change.py` with the modal scaffolding and `_options_for`**

Create `agentharness/tui_state_change.py`:

```python
"""Textual modal for the operator-driven state-change dialog.

UI only: no I/O, no storage imports. Reads everything from the FeatureState
passed to __init__. Triggered by the `S` keybinding in PipelineMonitor.
"""
from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Label, ListItem, ListView

from agentharness.models import FeatureState, FeatureStatus
from agentharness.state_change import StateChangeMode, StateChangeResult


CANONICAL_STATE_ORDER: list[FeatureStatus] = [
    FeatureStatus.brainstorming,
    FeatureStatus.brainstormed,
    FeatureStatus.analyzing,
    FeatureStatus.architecting,
    FeatureStatus.designing,
    FeatureStatus.planning,
    FeatureStatus.developing,
    FeatureStatus.dev_revision,
    FeatureStatus.reviewing,
]


class StateChangeModal(ModalScreen["StateChangeResult | None"]):
    """Modal listing valid state-change targets for a single feature."""

    CSS = """
    StateChangeModal {
        align: center middle;
    }
    #dialog {
        width: 60;
        height: 22;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }
    #title {
        text-style: bold;
        margin-bottom: 1;
    }
    #footer {
        color: $text-muted;
        margin-top: 1;
    }
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "dismiss(None)", "Cancel"),
        Binding("enter", "confirm", "Confirm"),
    ]

    def __init__(self, feature_state: FeatureState) -> None:
        super().__init__()
        self._feature_state = feature_state
        self._options = self._options_for(feature_state)

    def compose(self) -> ComposeResult:
        with Container(id="dialog"):
            yield Label(
                f"Change State: {self._feature_state.feature_id}\n"
                f"Current state: {self._feature_state.status.value}",
                id="title",
            )
            yield ListView(
                *[ListItem(Label(label)) for _, _, label in self._options],
                id="options",
            )
            yield Label("↑/↓ navigate   Enter confirm   Esc cancel", id="footer")

    def action_confirm(self) -> None:
        list_view = self.query_one("#options", ListView)
        idx = list_view.index
        if idx is None or idx < 0 or idx >= len(self._options):
            return
        target_status, mode, _ = self._options[idx]
        self.dismiss(StateChangeResult(target_status=target_status, mode=mode))

    @staticmethod
    def _options_for(
        state: FeatureState,
    ) -> list[tuple[FeatureStatus, StateChangeMode, str]]:
        """Selectable rows for the given feature state.

        Returns [(status, mode, display_label)] where mode is one of
        'restart', 'rollback', 'fail'. The last row is always the
        `failed` action; states later than the current one are excluded.
        """
        current = state.status
        rows: list[tuple[FeatureStatus, StateChangeMode, str]] = []

        if current in CANONICAL_STATE_ORDER:
            current_idx = CANONICAL_STATE_ORDER.index(current)
            for status in CANONICAL_STATE_ORDER[: current_idx + 1]:
                if status == current:
                    label = f"{status.value:<20} (current — restart)"
                    rows.append((status, "restart", label))
                else:
                    label = f"{status.value:<20} (rollback)"
                    rows.append((status, "rollback", label))

        rows.append((
            FeatureStatus.failed,
            "fail",
            f"{'failed':<20} (mark failed)",
        ))
        return rows
```

- [ ] **Step 4: Run the tests — they should pass**

Run: `pytest tests/test_tui_state_change.py -q`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add agentharness/tui_state_change.py tests/test_tui_state_change.py
git commit -m "feat(tui): add StateChangeModal with pure _options_for() helper"
```

---

## Task 9: Wire `S` binding into `PipelineMonitor`

Add the binding, the action handler that opens the modal, and the worker that calls `apply_state_change`.

**Files:**
- Modify: `agentharness/tui.py`

- [ ] **Step 1: Add the imports near the top of `tui.py`**

In `agentharness/tui.py`, alongside the existing `from agentharness.dispatcher import STATE_TO_QUEUE` line, add (keep imports alphabetized within the agentharness group):

```python
from agentharness.state_change import (
    StateChangeError,
    StateChangeResult,
    apply_state_change,
)
from agentharness.storage import create_state_manager, create_task_queue
from agentharness.tui_state_change import StateChangeModal
```

If `create_state_manager` or `create_task_queue` is already imported from `agentharness.storage`, do not duplicate — extend the existing line.

- [ ] **Step 2: Append the new binding to `PipelineMonitor.BINDINGS`**

Find the `BINDINGS: ClassVar[list[Binding]] = [...]` block in `PipelineMonitor` and append (before the closing `]`):

```python
        Binding("s", "open_state_change", "Change state"),
```

- [ ] **Step 3: Add the action handler and the worker method to `PipelineMonitor`**

Place these methods inside `class PipelineMonitor(App)`, alongside the other `action_*` methods:

```python
    def action_open_state_change(self) -> None:
        feature_id = self.query_one(FeatureList).selected_feature_id()
        if not feature_id:
            self.notify("No feature selected.", severity="warning")
            return
        state = next((s for s in self._states if s.feature_id == feature_id), None)
        if state is None:
            self.notify("Selected feature has no cached state.", severity="warning")
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
```

- [ ] **Step 4: Smoke-import `tui` to catch syntax / import errors**

Run: `python -c "from agentharness.tui import PipelineMonitor; assert any(b.key == 's' for b in PipelineMonitor.BINDINGS)"`
Expected: exits 0 with no output.

- [ ] **Step 5: Run the full test suite to confirm no regressions**

Run: `pytest tests/ -q`
Expected: all tests pass (existing + new state_change + new tui_state_change).

- [ ] **Step 6: Commit**

```bash
git add agentharness/tui.py
git commit -m "feat(tui): wire S binding to open StateChangeModal and apply state change"
```

---

## Task 10: Manual smoke test against a live backend

The unit tests cover pure logic; this task verifies the dialog actually works end-to-end. **Do this before declaring the feature done.**

**Files:**
- Run: `agentharness watch`

- [ ] **Step 1: Bring up a feature in any non-terminal state**

If a `developing` feature already exists in your backend, skip ahead. Otherwise:

```bash
agentharness submit brief.md            # gets feature ID
agentharness implement <feature-id>     # kicks off pipeline
agentharness observe &                  # let the pipeline run a bit
```

Wait until at least one feature is in `analyzing`, `developing`, or `reviewing` (any non-`done` state).

- [ ] **Step 2: Open the TUI and exercise the dialog**

Run: `agentharness watch`

In the TUI:
- Press `S` with **no feature** selected → expect notify "No feature selected." (warning toast).
- Select a `done` feature (if any) → press `S` → expect notify "State change unavailable for completed features."
- Select a non-`done` feature → press `S` → modal opens listing every state up to current + `failed`.
- Press `Escape` → modal closes, no state change observable in feature list.

- [ ] **Step 3: Test rollback `developing → planning` (clears tasks, requeues planner)**

In the TUI, with a `developing` feature selected:
- Press `S` → choose `planning` row → Enter.
- Expect notify "State changed: developing → planning (rollback)".
- Feature row updates within ~2s; `developing` task entries gone.
- Inspect the queue (Azure: `/azure-storage` skill peek; GitHub: `gh issue list`) — a planner task is enqueued.

- [ ] **Step 4: Test restart current state (no status change, requeues current phase)**

Pick any non-`done` feature:
- Press `S` → choose the **current** row (marked `(current — restart)`) → Enter.
- Expect notify "State changed: <s> → <s> (restart)".
- Status unchanged; queue depth for the matching phase increments by one.

- [ ] **Step 5: Test mark failed**

Pick a feature you don't mind terminating:
- Press `S` → choose `failed` row → Enter.
- Confirmation dialog appears (`Mark ... as failed?`). Confirm.
- Expect notify "State changed: ... → failed (fail)".
- Feature row turns red; no new queue activity.

- [ ] **Step 6: Test recovery from `failed`**

Take the feature you just failed:
- Press `S` → choose any earlier state (e.g. `planning`) → Enter.
- Expect rollback to succeed; planner-queue gets a task.

- [ ] **Step 7: Repeat steps 3-6 against the other backend**

If your dev environment uses Azure, repeat under `STORAGE_BACKEND=github` (or vice-versa) by setting `.env` and re-running. Both backends must produce identical operator-visible behavior.

- [ ] **Step 8: Commit any incidental fixes**

If steps 2-7 surface bugs, fix them, then re-run the affected step until clean. Commit each fix as its own commit:

```bash
git add <files>
git commit -m "fix(tui): <what was wrong>"
```

If no fixes were needed, no commit is necessary.

---

## Self-review checklist

After all tasks pass, walk through this once:

1. **Spec coverage:**
   - FR-1 (S keybinding, footer, guards) → Task 9.
   - FR-2 (state list rendering, `dev_revision` mapping) → Task 8.
   - FR-3 (restart) → Tasks 3, 4.
   - FR-4 (rollback, conditional task clear) → Tasks 3, 5.
   - FR-5 (mark failed) → Tasks 3, 9 (confirm dialog).
   - FR-6 (atomic update + audit event) → Task 3 (mutator), Task 6 (idempotency).
   - FR-7 (state→queue mapping reuse) → Task 1 (verify), Task 3 (`queue_for_state` / `build_phase_task`).
   - FR-8 (TUI refresh) → Task 9 (`call_after_refresh(self._refresh_data)`).
   - FR-9 (cancel/idempotency) → Task 8 (`Escape` binding) + Task 9 (`on_result(None)` early return).
   - NFR-1 (worker-based I/O off render loop) → Task 9 (`self.run_worker`).
   - NFR-3 (enqueue retry, typed error) → Task 7.
   - NFR-4 (single SoT for `STATE_TO_QUEUE`) → Task 1 (verified) + Task 3 (imported).

2. **Placeholder scan:** every code step shows actual code; every test step shows actual assertions; no "TBD" / "similar to" / "appropriate handling" anywhere.

3. **Type consistency:**
   - `StateChangeResult(target_status, mode)` consistent across `state_change.py`, `tui_state_change.py`, `tui.py`, both test files.
   - `StateChangeError(message, persisted_status)` constructor signature consistent in `state_change.py` and TUI exception handler.
   - `apply_state_change(feature_id, result, *, state_mgr, queue_factory, config)` signature consistent across implementation and all callers.
   - `_options_for(state) -> list[tuple[FeatureStatus, StateChangeMode, str]]` matches both producer (`compose`) and consumer (`action_confirm`).
