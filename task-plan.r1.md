# TUI Feature State Change Dialog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Textual modal dialog to the AgentHarness TUI (triggered by the `S` key) that lets operators atomically restart, roll back, or fail a feature's state and re-enqueue the appropriate pipeline work.

**Architecture:** The headless mutation logic lives in a new `agentharness/state_change.py` module so it is independently testable without Textual. The Textual modal lives in a new `agentharness/tui_state_change.py`. A new `STATE_TO_QUEUE` mapping plus `build_phase_task()` helper are added to `agentharness/dispatcher.py` to consolidate state→queue knowledge that is currently duplicated. `agentharness/run_task.py` gets a defensive guard to drop orphan messages whose `task_id` no longer exists in `state.tasks`. `agentharness/tui.py` only gains a single `Binding` and a small action handler; it does not grow into a god-object.

**Tech Stack:** Python 3.11+, Pydantic, Textual, pytest, pytest-asyncio. No new dependencies.

---

## File Structure

| File | Status | Responsibility |
|------|--------|----------------|
| `agentharness/models.py` | Modify | Add `FeatureState.with_tasks_cleared()` immutable helper |
| `agentharness/dispatcher.py` | Modify | Add `STATE_TO_QUEUE` mapping, `queue_for_state()`, and `build_phase_task()` |
| `agentharness/state_change.py` | **Create** | Headless service: `StateChangeMode`, `StateChangeResult`, `StateChangeError`, `apply_state_change()`. No Textual imports. |
| `agentharness/tui_state_change.py` | **Create** | `StateChangeModal(ModalScreen[StateChangeResult \| None])`. UI only. |
| `agentharness/run_task.py` | Modify | Defensive orphan-task guard at top of `run_task()` |
| `agentharness/tui.py` | Modify | New `S` binding, `action_open_state_change()`, replace local `_PHASE_TO_QUEUE` with import |
| `tests/test_models.py` | Modify | Add tests for `with_tasks_cleared()` |
| `tests/test_dispatcher.py` | Modify | Add tests for `STATE_TO_QUEUE`, `queue_for_state()`, `build_phase_task()` |
| `tests/test_state_change.py` | **Create** | Tests for `apply_state_change` against fake `state_mgr` + `queue_factory` |
| `tests/test_run_task.py` | Modify | Add orphan-task-guard test |
| `tests/test_tui_state_change.py` | **Create** | Pure-logic tests for `StateChangeModal._options_for()` (no Textual pilot — keeps CI fast) |

The plan is decomposed into independent tasks. Each task ends in a green test run and a commit. Task ordering is bottom-up: foundations first, then service, then UI, then wiring.

---

## Conventions used by every task

- **Run all tests** with: `.venv/bin/pytest tests/ -v` from repo root.
- **Run a single test file** with: `.venv/bin/pytest tests/test_<name>.py -v`.
- **Run one test** with: `.venv/bin/pytest tests/test_<name>.py::TestClass::test_method -v`.
- The repo uses `pytest-asyncio`. `@pytest.mark.asyncio` is required on async tests.
- Existing tests use `unittest.mock.AsyncMock` and `MagicMock` — follow the same pattern.
- Imports of `FeatureState`, `FeatureStatus`, etc. come from `agentharness.models`.
- The active backend per `.pipeline/config.json` is `github`. Tests must use mock/fake backends; never real Azure or GitHub I/O.
- Commit messages use Conventional Commits: `feat:`, `fix:`, `refactor:`, `test:`.

---

### Task 1: Add `FeatureState.with_tasks_cleared()` helper

**Why:** Spec requires clearing tasks on rollback to early phases. `with_tasks_added([])` (`models.py:149`) appends an empty list and does **not** clear — using it would silently no-op. We add a dedicated helper that returns an immutable copy with `tasks=[]`.

**Files:**
- Modify: `agentharness/models.py` (after line 153, alongside the other `with_*` helpers)
- Test: `tests/test_models.py` (append a new `TestWithTasksCleared` class)

- [ ] **Step 1: Write the failing test**

Append this class to `tests/test_models.py`:

```python
class TestWithTasksCleared:
    def _state_with_tasks(self) -> FeatureState:
        from agentharness.models import TaskEntry, TaskStatus
        return FeatureState(feature_id="feat-test").with_tasks_added([
            TaskEntry(task_id="feat-test-dev-a", phase="developing", status=TaskStatus.completed),
            TaskEntry(task_id="feat-test-dev-b", phase="developing", status=TaskStatus.queued),
        ])

    def test_returns_state_with_empty_tasks(self):
        state = self._state_with_tasks()
        cleared = state.with_tasks_cleared()
        assert cleared.tasks == []

    def test_original_instance_is_unchanged(self):
        state = self._state_with_tasks()
        state.with_tasks_cleared()
        assert len(state.tasks) == 2

    def test_other_fields_preserved(self):
        state = FeatureState(
            feature_id="feat-abc", status=FeatureStatus.developing
        ).with_tasks_added([
            __import__("agentharness.models", fromlist=["TaskEntry"]).TaskEntry(
                task_id="t1", phase="developing"
            )
        ])
        cleared = state.with_tasks_cleared()
        assert cleared.feature_id == "feat-abc"
        assert cleared.status == FeatureStatus.developing
        assert cleared.tasks == []

    def test_updated_at_changes(self):
        import time
        state = self._state_with_tasks()
        original_updated = state.updated_at
        time.sleep(0.001)
        cleared = state.with_tasks_cleared()
        assert cleared.updated_at >= original_updated

    def test_returns_empty_when_already_empty(self):
        state = FeatureState(feature_id="feat-empty")
        assert state.tasks == []
        cleared = state.with_tasks_cleared()
        assert cleared.tasks == []
```

- [ ] **Step 2: Run tests — verify they FAIL**

Run: `.venv/bin/pytest tests/test_models.py::TestWithTasksCleared -v`
Expected: 5 failures with `AttributeError: 'FeatureState' object has no attribute 'with_tasks_cleared'`.

- [ ] **Step 3: Implement the helper in `agentharness/models.py`**

Add this method to `FeatureState`, **immediately after** `with_tasks_added` (around line 153):

```python
    def with_tasks_cleared(self) -> FeatureState:
        """Return new state with tasks=[] (immutable copy). Used by manual rollback."""
        return self.model_copy(update={"tasks": [], "updated_at": datetime.now(UTC)})
```

- [ ] **Step 4: Run tests — verify they PASS**

Run: `.venv/bin/pytest tests/test_models.py::TestWithTasksCleared -v`
Expected: 5 passes.

Run the full models suite to ensure no regression:
`.venv/bin/pytest tests/test_models.py -v`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add agentharness/models.py tests/test_models.py
git commit -m "feat(models): add FeatureState.with_tasks_cleared() helper

with_tasks_added([]) appends, not clears. Add a dedicated immutable helper
for manual rollback flows that need to wipe the task list."
```

---

### Task 2: Add `STATE_TO_QUEUE` mapping and `queue_for_state()` helper to `dispatcher.py`

**Why:** State→queue knowledge is currently duplicated in `tui._PHASE_TO_QUEUE` (`tui.py:54`) and inside `_resume_phase` (`tui.py:632-639`), and is missing `dev_revision` and the terminal `done`/`failed` rows. We consolidate it in `dispatcher.py` (which already owns pipeline routing) and expose a small lookup helper.

**Files:**
- Modify: `agentharness/dispatcher.py` (add constant + helper after `_LINEAR_TRANSITIONS`)
- Test: `tests/test_dispatcher.py` (append `TestStateToQueue` class)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_dispatcher.py`:

```python
from agentharness.models import FeatureStatus


class TestStateToQueue:
    def test_mapping_covers_every_feature_status(self):
        from agentharness.dispatcher import STATE_TO_QUEUE
        for status in FeatureStatus:
            assert status in STATE_TO_QUEUE, f"Missing mapping for {status}"

    def test_active_phases_have_queues(self):
        from agentharness.dispatcher import STATE_TO_QUEUE
        assert STATE_TO_QUEUE[FeatureStatus.analyzing] == "analyst-queue"
        assert STATE_TO_QUEUE[FeatureStatus.architecting] == "architect-queue"
        assert STATE_TO_QUEUE[FeatureStatus.designing] == "designer-queue"
        assert STATE_TO_QUEUE[FeatureStatus.planning] == "planner-queue"
        assert STATE_TO_QUEUE[FeatureStatus.developing] == "developer-queue"
        assert STATE_TO_QUEUE[FeatureStatus.dev_revision] == "developer-queue"
        assert STATE_TO_QUEUE[FeatureStatus.reviewing] == "review-queue"

    def test_terminal_and_brainstorm_states_have_no_queue(self):
        from agentharness.dispatcher import STATE_TO_QUEUE
        assert STATE_TO_QUEUE[FeatureStatus.brainstorming] is None
        assert STATE_TO_QUEUE[FeatureStatus.brainstormed] is None
        assert STATE_TO_QUEUE[FeatureStatus.done] is None
        assert STATE_TO_QUEUE[FeatureStatus.failed] is None

    def test_queue_for_state_returns_mapped_queue(self):
        from agentharness.dispatcher import queue_for_state
        assert queue_for_state(FeatureStatus.developing) == "developer-queue"

    def test_queue_for_state_returns_none_for_terminal(self):
        from agentharness.dispatcher import queue_for_state
        assert queue_for_state(FeatureStatus.failed) is None
        assert queue_for_state(FeatureStatus.done) is None
```

- [ ] **Step 2: Run tests — verify they FAIL**

Run: `.venv/bin/pytest tests/test_dispatcher.py::TestStateToQueue -v`
Expected: ImportError or AttributeError because neither `STATE_TO_QUEUE` nor `queue_for_state` exist yet.

- [ ] **Step 3: Implement the constant and helper in `agentharness/dispatcher.py`**

Insert this block **immediately after** the existing `_LINEAR_TRANSITIONS` definition (around `dispatcher.py:78`, before `dispatch_after_completion`):

```python
# Authoritative state→queue mapping. Used by the dispatcher and by the
# manual state-change service (state_change.apply_state_change).
STATE_TO_QUEUE: dict[FeatureStatus, str | None] = {
    FeatureStatus.brainstorming: None,
    FeatureStatus.brainstormed:  None,
    FeatureStatus.analyzing:     "analyst-queue",
    FeatureStatus.architecting:  "architect-queue",
    FeatureStatus.designing:     "designer-queue",
    FeatureStatus.planning:      "planner-queue",
    FeatureStatus.developing:    "developer-queue",
    FeatureStatus.dev_revision:  "developer-queue",
    FeatureStatus.reviewing:     "review-queue",
    FeatureStatus.done:          None,
    FeatureStatus.failed:        None,
}


def queue_for_state(status: FeatureStatus) -> str | None:
    """Return the queue name to enqueue a task on for a given feature status, or None
    when the status is terminal or pre-pipeline (brainstorming/brainstormed/done/failed)."""
    return STATE_TO_QUEUE.get(status)
```

- [ ] **Step 4: Run tests — verify they PASS**

Run: `.venv/bin/pytest tests/test_dispatcher.py::TestStateToQueue -v`
Expected: 5 passes.

Run the full dispatcher suite to ensure no regression:
`.venv/bin/pytest tests/test_dispatcher.py -v`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add agentharness/dispatcher.py tests/test_dispatcher.py
git commit -m "feat(dispatcher): add STATE_TO_QUEUE mapping and queue_for_state()

Single source of truth for status→queue routing. Replaces duplication in
tui._PHASE_TO_QUEUE and tui._resume_phase. Used by the new manual
state-change service."
```

---

### Task 3: Add `build_phase_task()` helper to `dispatcher.py`

**Why:** The new `apply_state_change` service needs to construct a `TaskMessage` for any pipeline phase. Existing `_dispatch_linear` builds these inline (`dispatcher.py:128-135`) and `tui._resume_phase` re-implements the per-phase artifact dicts (`tui.py:660-687`). We extract a single helper that both call sites can use. For the developer/review queues we re-use the `TaskEntry.queued_message` already stored on the most recent in-progress dev task.

**Files:**
- Modify: `agentharness/dispatcher.py` (append a public `build_phase_task` helper; reuse `_artifacts_for_phase` and `_output_name`)
- Test: `tests/test_dispatcher.py` (append `TestBuildPhaseTask` class)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_dispatcher.py`:

```python
class TestBuildPhaseTask:
    def _config(self):
        # Mimic the queue→agent path mapping in .pipeline/config.json
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

    def test_phase_agent_task_for_analyzing(self):
        from agentharness.dispatcher import build_phase_task
        state = FeatureState(feature_id="feat-x", status=FeatureStatus.analyzing)
        task = build_phase_task(state, FeatureStatus.analyzing, self._config())
        assert task.feature_id == "feat-x"
        assert task.task_id == "feat-x-analyzing-1"
        assert task.agent_role == "analyst"
        assert task.input_artifacts == ["artifacts/feat-x/brief.md"]
        assert task.output_artifact == "artifacts/feat-x/spec.r1.md"

    def test_phase_agent_task_for_planning(self):
        from agentharness.dispatcher import build_phase_task
        state = FeatureState(feature_id="feat-x", status=FeatureStatus.planning)
        task = build_phase_task(state, FeatureStatus.planning, self._config())
        assert task.agent_role == "planner"
        assert task.task_id == "feat-x-planning-1"
        assert task.output_artifact == "artifacts/feat-x/task-plan.r1.md"

    def test_developer_target_uses_in_progress_queued_message(self):
        from agentharness.dispatcher import build_phase_task
        existing = TaskMessage(
            feature_id="feat-x",
            task_id="feat-x-dev-auth-r1",
            input_artifacts=["artifacts/feat-x/task-context/auth.md"],
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
        state = FeatureState(
            feature_id="feat-x", status=FeatureStatus.developing
        ).with_tasks_added([entry])
        task = build_phase_task(state, FeatureStatus.developing, self._config())
        assert task.task_id == existing.task_id
        assert task.agent_role == "developer"

    def test_developer_target_falls_back_to_pending_task(self):
        from agentharness.dispatcher import build_phase_task
        pending_msg = TaskMessage(
            feature_id="feat-x",
            task_id="feat-x-dev-api-r1",
            input_artifacts=[],
            output_artifact="artifacts/feat-x/impl/api.r1.md",
            agent_role="developer",
            context="api",
        )
        entry = TaskEntry(
            task_id=pending_msg.task_id,
            phase="developing",
            status=TaskStatus.pending,
            queued_message=pending_msg.model_dump(),
        )
        state = FeatureState(
            feature_id="feat-x", status=FeatureStatus.developing
        ).with_tasks_added([entry])
        task = build_phase_task(state, FeatureStatus.developing, self._config())
        assert task.task_id == pending_msg.task_id

    def test_developer_target_raises_when_no_task_available(self):
        from agentharness.dispatcher import build_phase_task
        state = FeatureState(feature_id="feat-x", status=FeatureStatus.developing)
        with pytest.raises(ValueError, match="No developer task"):
            build_phase_task(state, FeatureStatus.developing, self._config())

    def test_terminal_status_raises(self):
        from agentharness.dispatcher import build_phase_task
        state = FeatureState(feature_id="feat-x", status=FeatureStatus.failed)
        with pytest.raises(ValueError, match="no enqueueable task"):
            build_phase_task(state, FeatureStatus.failed, self._config())
```

- [ ] **Step 2: Run tests — verify they FAIL**

Run: `.venv/bin/pytest tests/test_dispatcher.py::TestBuildPhaseTask -v`
Expected: ImportError because `build_phase_task` is not yet defined.

- [ ] **Step 3: Implement the helper in `agentharness/dispatcher.py`**

Append this function at the bottom of `agentharness/dispatcher.py` (after `_open_feature_pr`):

```python
def build_phase_task(
    state: FeatureState,
    target_status: FeatureStatus,
    config: Config,
) -> TaskMessage:
    """Construct a TaskMessage for re-enqueuing work at the given target status.

    For phase-agent statuses (analyzing/architecting/designing/planning/reviewing),
    builds a fresh r1 phase task using `_artifacts_for_phase` + `_output_name`.

    For developer/dev_revision statuses, reuses the most recent in-progress dev
    task's `queued_message` (or falls back to the next pending task).

    Raises ValueError if no enqueueable task exists for the given status.
    """
    queue_name = STATE_TO_QUEUE.get(target_status)
    if queue_name is None:
        raise ValueError(
            f"build_phase_task: no enqueueable task for terminal/pre-pipeline status {target_status!r}"
        )

    feature_id = state.feature_id

    if target_status in (FeatureStatus.developing, FeatureStatus.dev_revision):
        in_progress = next(
            (t for t in state.tasks
             if t.phase == "developing" and t.status == TaskStatus.in_progress),
            None,
        )
        candidate = in_progress or state.next_pending_task("developing")
        if candidate is None or not candidate.queued_message:
            raise ValueError(
                f"No developer task available to enqueue for status {target_status!r}"
            )
        return TaskMessage.model_validate(candidate.queued_message)

    if target_status == FeatureStatus.reviewing:
        in_progress = next(
            (t for t in state.tasks
             if t.phase == "developing" and t.status == TaskStatus.in_progress),
            None,
        )
        if in_progress is None or not in_progress.queued_message:
            raise ValueError("No developer task awaiting review")
        dev_msg = TaskMessage.model_validate(in_progress.queued_message)
        task_name = _task_name_from_id(dev_msg.task_id, feature_id)
        revision = dev_msg.revision
        return TaskMessage(
            feature_id=feature_id,
            task_id=f"{feature_id}-review-{task_name}-r{revision}",
            input_artifacts=[
                phase_artifact_path(feature_id, "spec", 1),
                phase_artifact_path(feature_id, "arch-review", 1),
                dev_msg.output_artifact,
            ],
            output_artifact=task_review_artifact_path(feature_id, task_name, revision),
            agent_role="reviewer",
            context=task_name,
            revision=revision,
            work_dir=dev_msg.work_dir,
            state_issue_number=state.state_issue_number,
        )

    # Phase agents: analyzing / architecting / designing / planning
    phase = target_status.value
    revision = 1
    agent_path = config.agent_path_for_queue(queue_name)
    return TaskMessage(
        feature_id=feature_id,
        task_id=f"{feature_id}-{phase}-{revision}",
        input_artifacts=_artifacts_for_phase(feature_id, phase),
        output_artifact=phase_artifact_path(feature_id, _output_name(phase), revision),
        agent_role=agent_path.stem,
        state_issue_number=state.state_issue_number,
    )
```

- [ ] **Step 4: Run tests — verify they PASS**

Run: `.venv/bin/pytest tests/test_dispatcher.py::TestBuildPhaseTask -v`
Expected: 6 passes.

Run the full dispatcher suite:
`.venv/bin/pytest tests/test_dispatcher.py -v`
Expected: all green (existing tests unchanged).

- [ ] **Step 5: Commit**

```bash
git add agentharness/dispatcher.py tests/test_dispatcher.py
git commit -m "feat(dispatcher): add build_phase_task() helper

Centralizes TaskMessage construction for phase agents and developer-queue
re-enqueue. Used by the manual state-change service to avoid the inline
re-implementation that tui._resume_phase currently has."
```

---

### Task 4: Create `agentharness/state_change.py` headless service

**Why:** All mutation logic for the operator-driven state change lives here, with no Textual coupling so it can be unit-tested and reused by future surfaces (CLI command, web UI). The closure-driven atomicity is critical: `state_mgr.update()` may invoke its mutator multiple times under lease contention, so the closure must rebuild the new state from each fresh snapshot rather than capturing outer mutable variables.

**Files:**
- Create: `agentharness/state_change.py`
- Test: `tests/test_state_change.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_state_change.py`:

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
    StateChangeError,
    StateChangeMode,
    StateChangeResult,
    apply_state_change,
)


def _make_state_mgr(initial: FeatureState):
    """Return an AsyncMock that simulates StateBackend.update via a mutator closure."""
    state = {"value": initial}

    async def fake_update(feature_id, mutator):
        state["value"] = mutator(state["value"])
        return state["value"]

    async def fake_get(feature_id):
        return state["value"]

    mgr = AsyncMock()
    mgr.update.side_effect = fake_update
    mgr.get.side_effect = fake_get
    mgr._state_ref = state  # for tests to inspect
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
        assert factory.queues == {}  # no enqueue at all

    async def test_appends_history_event_with_metadata(self):
        initial = FeatureState(feature_id="feat-x", status=FeatureStatus.developing)
        mgr = _make_state_mgr(initial)

        await apply_state_change(
            "feat-x",
            StateChangeResult(target_status=FeatureStatus.failed, mode="fail"),
            state_mgr=mgr, queue_factory=_make_queue_factory(), config=_config(),
        )

        persisted = mgr._state_ref["value"]
        assert len(persisted.history) == 1
        evt = persisted.history[0]
        assert evt.event == "manual_state_change"
        details = json.loads(evt.details)
        assert details["from"] == "developing"
        assert details["to"] == "failed"
        assert details["mode"] == "fail"
        assert details["actor"] == "tui"


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


@pytest.mark.asyncio
class TestApplyStateChangeRollback:
    async def test_rollback_to_planning_clears_tasks(self):
        entry = TaskEntry(task_id="feat-x-dev-a", phase="developing", status=TaskStatus.in_progress)
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

        persisted = mgr._state_ref["value"]
        evt = persisted.history[-1]
        details = json.loads(evt.details)
        assert details["tasks_cleared"] is True
        assert details["mode"] == "rollback"


@pytest.mark.asyncio
class TestApplyStateChangeIdempotencyUnderRetry:
    async def test_closure_appends_only_one_event_when_invoked_twice(self):
        """Simulate lease contention: state_mgr.update calls the mutator twice."""
        initial = FeatureState(feature_id="feat-x", status=FeatureStatus.developing)
        state_holder = {"value": initial}

        async def retry_update(feature_id, mutator):
            # First attempt: discard result (simulate lease lost)
            mutator(state_holder["value"])
            # Second attempt: keep result
            state_holder["value"] = mutator(state_holder["value"])
            return state_holder["value"]

        mgr = AsyncMock()
        mgr.update.side_effect = retry_update

        await apply_state_change(
            "feat-x",
            StateChangeResult(target_status=FeatureStatus.failed, mode="fail"),
            state_mgr=mgr, queue_factory=_make_queue_factory(), config=_config(),
        )

        # One event in the persisted state — the closure rebuilt from snapshot each time
        events = [e for e in state_holder["value"].history if e.event == "manual_state_change"]
        assert len(events) == 1


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

        # Patch asyncio.sleep so the test runs fast
        import agentharness.state_change as sc
        monkeypatch.setattr(sc.asyncio, "sleep", AsyncMock())

        with pytest.raises(StateChangeError) as exc_info:
            await apply_state_change(
                "feat-x",
                StateChangeResult(target_status=FeatureStatus.developing, mode="restart"),
                state_mgr=mgr, queue_factory=factory, config=_config(),
            )

        assert exc_info.value.persisted_status == FeatureStatus.developing
        # Two attempts (one initial + one retry)
        assert bad_queue.send_task.await_count == 2
```

- [ ] **Step 2: Run tests — verify they FAIL**

Run: `.venv/bin/pytest tests/test_state_change.py -v`
Expected: ModuleNotFoundError — `agentharness.state_change` does not exist.

- [ ] **Step 3: Implement `agentharness/state_change.py`**

Create `agentharness/state_change.py`:

```python
"""Headless service for operator-driven feature state changes.

Used by the TUI's `S` shortcut (and by any future CLI/web surface). Owns the
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

# Rolling back to any of these statuses wipes the developer task list.
# (Anything later than `planning` keeps tasks intact.)
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
    """User selection from the StateChangeModal."""
    target_status: FeatureStatus
    mode: StateChangeMode


class StateChangeError(Exception):
    """Raised when the state was persisted but the follow-up enqueue failed.

    The operator must retry from the dialog. The persisted status is attached
    so the caller can offer "retry enqueue only" without re-mutating state.
    """

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
    """Atomically transition a feature and enqueue the follow-up phase task.

    Contract:
      - One state_mgr.update() call. The closure may run multiple times under
        lease contention; it always rebuilds the new state from the fresh
        snapshot, so retries do not duplicate the audit event.
      - Skips enqueue when the target maps to None (failed / brainstorming /
        brainstormed / done). Restarting an existing status that maps to a
        queue still enqueues (e.g. restart developing → developer-queue).
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

- [ ] **Step 4: Run tests — verify they PASS**

Run: `.venv/bin/pytest tests/test_state_change.py -v`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add agentharness/state_change.py tests/test_state_change.py
git commit -m "feat(state-change): add headless apply_state_change service

Atomic mutation via state_mgr.update closure (idempotent under lease retry)
plus a single follow-up enqueue with retry-once-then-raise semantics. Used
by the new TUI 'S' dialog and reusable from any non-Textual surface."
```

---

### Task 5: Add orphan-task guard to `run_task.py`

**Why:** When a manual rollback clears `state.tasks`, any in-flight developer/review queue messages still reference the cleared `task_id`. The observer cannot delete them by ID. We make `run_task.run_task()` defensively no-op for missing `task_id`s and emit a `dropped_orphan_task` audit event so the drop is observable in the event log. Phase agents (analyst/architect/designer/planner) do not have a per-task entry, so the guard runs only when the message is for a developer or review task.

**Files:**
- Modify: `agentharness/run_task.py` (add a guard inside `run_task` after we load `feature_state`, around line 42)
- Test: `tests/test_run_task.py` (append `TestOrphanTaskGuard` class)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_run_task.py`:

```python
@pytest.mark.asyncio
class TestOrphanTaskGuard:
    """When a developer/review task message arrives but its task_id is no longer
    in state.tasks (e.g. after a manual rollback), run_task must drop the message,
    emit a dropped_orphan_task audit event, and not run the agent."""

    async def test_drops_developer_message_when_task_id_missing(self):
        from agentharness.run_task import run_task as run_task_fn

        task_json = (
            '{"task_id": "feat-x-dev-old", "feature_id": "feat-x",'
            ' "input_artifacts": [], "output_artifact": "artifacts/feat-x/impl/old.r1.md",'
            ' "agent_role": "developer", "work_dir": null, "revision": 1}'
        )

        config = MagicMock()
        config.storage_backend = "azure"
        config.queue_names.return_value = []

        # State no longer contains the task_id from the message.
        mock_state_mgr = AsyncMock()
        mock_state = MagicMock()
        mock_state.worktree_path = None
        mock_state.branch_name = None
        mock_state.tasks = []  # rollback cleared everything
        mock_state_mgr.get = AsyncMock(return_value=mock_state)
        mock_state_mgr.update = AsyncMock(return_value=mock_state)

        mock_store = AsyncMock()
        mock_store.close = AsyncMock()

        with (
            patch("agentharness.run_task.create_artifact_store", return_value=mock_store),
            patch("agentharness.run_task.create_state_manager", return_value=mock_state_mgr),
            patch("agentharness.run_task.create_task_queue"),
            patch("agentharness.run_task.run_agent") as mock_run_agent,
            patch("agentharness.run_task.dispatch_after_completion") as mock_dispatch,
        ):
            await run_task_fn("developer-queue", task_json, config)

        # Agent must NOT have been invoked
        mock_run_agent.assert_not_called()
        mock_dispatch.assert_not_called()

        # An audit event must have been written
        update_calls = mock_state_mgr.update.await_args_list
        assert len(update_calls) >= 1
        # The closure should produce an event named dropped_orphan_task — invoke it
        # against a real FeatureState to confirm.
        from agentharness.models import FeatureState
        probe_state = FeatureState(feature_id="feat-x")
        produced = update_calls[0].args[1](probe_state)
        assert any(e.event == "dropped_orphan_task" for e in produced.history)

    async def test_runs_normally_when_task_id_is_present(self):
        """Sanity: presence of the task_id in state.tasks does not trigger the guard."""
        from agentharness.models import FeatureState, TaskEntry, TaskStatus
        from agentharness.run_task import run_task as run_task_fn

        existing_task_id = "feat-x-dev-here"
        task_json = (
            f'{{"task_id": "{existing_task_id}", "feature_id": "feat-x",'
            ' "input_artifacts": [], "output_artifact": "artifacts/feat-x/impl/here.r1.md",'
            ' "agent_role": "developer", "work_dir": null, "revision": 1}'
        )

        config = MagicMock()
        config.storage_backend = "azure"
        config.queue_names.return_value = []
        config.agent_path_for_queue.return_value = MagicMock()

        state = FeatureState(feature_id="feat-x").with_tasks_added([
            TaskEntry(task_id=existing_task_id, phase="developing", status=TaskStatus.queued)
        ])

        mock_state_mgr = AsyncMock()
        mock_state_mgr.get = AsyncMock(return_value=state)
        mock_state_mgr.update = AsyncMock(return_value=state)

        mock_store = AsyncMock()
        mock_store.upload = AsyncMock()
        mock_store.close = AsyncMock()

        mock_agent_def = MagicMock()
        mock_agent_def.allowed_tools = []
        mock_agent_def.system_prompt = "x"
        mock_agent_def.context_files = []

        mock_run_result = MagicMock()
        mock_run_result.output = "## Status: DONE"
        mock_run_result.tokens = None

        with (
            patch("agentharness.run_task.create_artifact_store", return_value=mock_store),
            patch("agentharness.run_task.create_state_manager", return_value=mock_state_mgr),
            patch("agentharness.run_task.create_task_queue"),
            patch("agentharness.run_task.load_agent_definition", return_value=mock_agent_def),
            patch("agentharness.run_task.run_agent", return_value=mock_run_result) as mock_run_agent,
            patch("agentharness.run_task.dispatch_after_completion", return_value=None),
        ):
            await run_task_fn("developer-queue", task_json, config)

        # Agent should have been invoked (no orphan)
        mock_run_agent.assert_called_once()

    async def test_does_not_apply_guard_to_phase_agent_messages(self):
        """Phase-level messages (no task_id in state.tasks) must still execute —
        phase agents do not have TaskEntry rows. We only skip dev/review messages
        whose task_id starts with the feature_id followed by '-dev-' or '-review-'."""
        from agentharness.models import FeatureState
        from agentharness.run_task import run_task as run_task_fn

        # Message uses the analyst-phase task_id pattern (no -dev-/-review-)
        task_json = (
            '{"task_id": "feat-x-analyzing-1", "feature_id": "feat-x",'
            ' "input_artifacts": [], "output_artifact": "artifacts/feat-x/spec.r1.md",'
            ' "agent_role": "analyst", "work_dir": null, "revision": 1}'
        )

        config = MagicMock()
        config.storage_backend = "azure"
        config.queue_names.return_value = []
        config.agent_path_for_queue.return_value = MagicMock()

        state = FeatureState(feature_id="feat-x")  # no tasks; that is normal for phase work

        mock_state_mgr = AsyncMock()
        mock_state_mgr.get = AsyncMock(return_value=state)
        mock_state_mgr.update = AsyncMock(return_value=state)

        mock_store = AsyncMock()
        mock_store.upload = AsyncMock()
        mock_store.close = AsyncMock()

        mock_agent_def = MagicMock()
        mock_agent_def.allowed_tools = []
        mock_agent_def.system_prompt = "x"
        mock_agent_def.context_files = []

        mock_run_result = MagicMock()
        mock_run_result.output = "spec content"
        mock_run_result.tokens = None

        with (
            patch("agentharness.run_task.create_artifact_store", return_value=mock_store),
            patch("agentharness.run_task.create_state_manager", return_value=mock_state_mgr),
            patch("agentharness.run_task.create_task_queue"),
            patch("agentharness.run_task.load_agent_definition", return_value=mock_agent_def),
            patch("agentharness.run_task.run_agent", return_value=mock_run_result) as mock_run_agent,
            patch("agentharness.run_task.dispatch_after_completion", return_value=None),
        ):
            await run_task_fn("analyst-queue", task_json, config)

        mock_run_agent.assert_called_once()
```

- [ ] **Step 2: Run tests — verify they FAIL**

Run: `.venv/bin/pytest tests/test_run_task.py::TestOrphanTaskGuard -v`
Expected: failures — the guard does not exist; the orphan dev message will currently try to run the agent and crash on missing artifact downloads.

- [ ] **Step 3: Implement the guard in `agentharness/run_task.py`**

Modify `agentharness/run_task.py`. Locate the `run_task` function (starts at line 38). After the line `feature_state = await state_mgr.get(task.feature_id)` (line 42) and **before** `branch_name = ...` (line 43), insert:

```python
        # Defensive guard: if a developer/review task's id was wiped out by a
        # manual rollback, drop the message and emit an audit event rather than
        # crash mid-execution. Phase-level messages do not have TaskEntry rows
        # and must continue to execute (their task_id pattern is feature-{phase}-N).
        if _is_per_task_message(task.task_id, task.feature_id):
            current_ids = {t.task_id for t in feature_state.tasks}
            if task.task_id not in current_ids:
                log.warning(
                    "[%s] Dropping orphan task %s — no matching TaskEntry in state",
                    WORKER_ID, task.task_id,
                )
                await state_mgr.update(
                    task.feature_id,
                    lambda s: s.with_event(
                        "dropped_orphan_task",
                        task_id=task.task_id,
                        details=f'task_id {task.task_id!r} no longer in state.tasks',
                    ),
                )
                return
```

Then add this small helper near the bottom of the module (after `_parse_task_sections`, before `configure_logging`):

```python
def _is_per_task_message(task_id: str, feature_id: str) -> bool:
    """Return True for developer/review messages keyed to a TaskEntry.

    Phase-agent messages use the pattern '{feature_id}-{phase}-{N}'; per-task
    messages use '{feature_id}-dev-{name}[-r{N}]' or '{feature_id}-review-{name}-r{N}'.
    """
    prefix = f"{feature_id}-"
    if not task_id.startswith(prefix):
        return False
    suffix = task_id[len(prefix):]
    return suffix.startswith("dev-") or suffix.startswith("review-")
```

- [ ] **Step 4: Run tests — verify they PASS**

Run: `.venv/bin/pytest tests/test_run_task.py::TestOrphanTaskGuard -v`
Expected: 3 passes.

Run the full run_task suite to ensure no regression:
`.venv/bin/pytest tests/test_run_task.py -v`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add agentharness/run_task.py tests/test_run_task.py
git commit -m "feat(run_task): defensively drop orphan dev/review task messages

After a manual rollback, in-flight developer/review messages may reference
a task_id that no longer exists in state.tasks. Drop them with a
dropped_orphan_task audit event instead of crashing. Phase-agent messages
are unaffected."
```

---

### Task 6: Create `StateChangeModal` in `agentharness/tui_state_change.py`

**Why:** The Textual modal lives in its own module so `tui.py` does not grow further (already 910 lines). The modal's `_options_for()` method is pure (computes the row list from a `FeatureState`) and is easily unit-tested without spinning up a Textual pilot. The compose/keybinding wiring follows the existing `ConfirmScreen` pattern at `tui.py:403`.

**Files:**
- Create: `agentharness/tui_state_change.py`
- Test: `tests/test_tui_state_change.py` (new — pure logic only)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tui_state_change.py`:

```python
"""Pure-logic tests for StateChangeModal. We only test _options_for() here —
the Textual rendering itself is covered by manual smoke testing in the dev
loop, since headless Textual pilot tests add CI weight without much value
for a static list."""
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
            if status == FeatureStatus.failed:
                continue
            if status == FeatureStatus.developing:
                continue
            assert mode == "rollback"
            assert "rollback" in label

    def test_for_brainstorming_only_self_and_failed(self):
        opts = StateChangeModal._options_for(_state(FeatureStatus.brainstorming))
        assert [s for s, _, _ in opts] == [FeatureStatus.brainstorming, FeatureStatus.failed]

    def test_dev_revision_appears_in_order_for_dev_revision_state(self):
        opts = StateChangeModal._options_for(_state(FeatureStatus.dev_revision))
        statuses = [s for s, _, _ in opts]
        assert FeatureStatus.developing in statuses
        assert FeatureStatus.dev_revision in statuses
        # dev_revision is current → restart
        idx = next(i for i, (s, _, _) in enumerate(opts) if s == FeatureStatus.dev_revision)
        _, mode, _ = opts[idx]
        assert mode == "restart"

    def test_done_features_yield_only_failed_row(self):
        """Defensive: even though the TUI guards on done before opening the modal,
        the helper itself should not crash. It can return just the failed row."""
        opts = StateChangeModal._options_for(_state(FeatureStatus.done))
        # done is excluded from the list; we still allow marking failed manually
        assert all(s != FeatureStatus.done for s, _, _ in opts)
```

- [ ] **Step 2: Run tests — verify they FAIL**

Run: `.venv/bin/pytest tests/test_tui_state_change.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement `agentharness/tui_state_change.py`**

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


# Canonical pipeline order (excludes terminal `done`; `failed` is appended
# separately as an always-available action).
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
        """Compute the list of selectable rows for the given feature state.

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

- [ ] **Step 4: Run tests — verify they PASS**

Run: `.venv/bin/pytest tests/test_tui_state_change.py -v`
Expected: 7 passes.

- [ ] **Step 5: Commit**

```bash
git add agentharness/tui_state_change.py tests/test_tui_state_change.py
git commit -m "feat(tui): add StateChangeModal for the manual state-change dialog

Pure-UI modal lives in its own module to keep tui.py focused. The
_options_for helper is pure and unit-tested; the rendering is covered by
manual smoke testing in the dev loop."
```

---

### Task 7: Wire the `S` binding and `action_open_state_change` into `tui.py`

**Why:** The main TUI screen needs to bind `S`, find the selected feature, guard against `done`, push the modal, and call `apply_state_change` with the result. We use the pluggable factories `create_state_manager` / `create_task_queue` (the existing `_resume_phase` does **not** — copying its pattern would re-introduce a github-backend bug).

**Files:**
- Modify: `agentharness/tui.py` (add `Binding`, action method, import)

- [ ] **Step 1: Add the binding to the BINDINGS list**

Edit `agentharness/tui.py:501-511`. Append a new `Binding` line so the list reads:

```python
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh now"),
        Binding("l", "open_log", "Open log in less"),
        Binding("c", "clear_logs", "Clear worker logs"),
        Binding("p", "purge_queues", "Purge all queues"),
        Binding("i", "implement", "Implement selected feature"),
        Binding("o", "toggle_observer", "Observer on/off"),
        Binding("k", "kill_task", "Kill selected task"),
        Binding("t", "resume_task", "Resume selected task"),
        Binding("s", "open_state_change", "Change state"),
    ]
```

- [ ] **Step 2: Add the imports**

At the top of `tui.py`, in the existing imports block (around line 24-26), add:

```python
from agentharness.state_change import (
    StateChangeError,
    StateChangeResult,
    apply_state_change,
)
from agentharness.storage import create_state_manager, create_task_queue
from agentharness.tui_state_change import StateChangeModal
```

- [ ] **Step 3: Add the action method on `PipelineMonitor`**

Add this method to the `PipelineMonitor` class. Place it directly after `action_resume_task` (around `tui.py:614`, before `_do_resume_task`):

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

- [ ] **Step 4: Run all tests — confirm nothing broke**

Run: `.venv/bin/pytest tests/ -v`
Expected: all green. The new binding and action are not unit-tested (TUI wiring is covered by manual smoke testing) but the modules they import are.

- [ ] **Step 5: Manual smoke test**

The TUI cannot be exercised in CI. Run a manual smoke check:

```bash
# In a separate terminal, ensure the env is loaded with STORAGE_BACKEND=github
# (or azure if you have a connection string available).
.venv/bin/agentharness watch
```

Verify:
1. Pressing `S` with no feature selected prints "No feature selected.".
2. Pressing `S` on a feature with status `done` prints "State change unavailable for completed features.".
3. Pressing `S` on an active feature opens the modal showing the canonical states up to and including the current one, plus a `failed` row at the bottom.
4. Pressing `Esc` closes the modal with no toast and no state change.
5. Pressing `Enter` on the current state row shows `State changed: X → X (restart)` and the event log gets a `manual_state_change` entry within ~2s.
6. Selecting an earlier state shows `State changed: current → earlier (rollback)`. If the target was `planning` or earlier, the task list clears.
7. Selecting `failed` triggers a `ConfirmScreen` first; pressing Confirm marks the feature failed.

If any of these fail, fix and re-run before committing.

- [ ] **Step 6: Commit**

```bash
git add agentharness/tui.py
git commit -m "feat(tui): add 'S' binding to open the state-change dialog

Wires the headless apply_state_change service into the TUI through a new
StateChangeModal. Uses pluggable storage factories (create_state_manager /
create_task_queue) — does not duplicate the github-incompatible pattern
in _resume_phase. Failed mode goes through the existing ConfirmScreen for
a deliberate second keypress."
```

---

### Task 8: Replace the local `_PHASE_TO_QUEUE` in `tui.py` with `STATE_TO_QUEUE` import

**Why:** Once `STATE_TO_QUEUE` exists in dispatcher.py, the local `_PHASE_TO_QUEUE` dict at `tui.py:54` and the inline copy inside `_resume_phase` (`tui.py:632-639`) are duplicated state. We replace the module-level dict with a derived view; we leave the older `_resume_phase` inline copy alone — that legacy flow already has known issues (bypasses pluggable backends) and is out of scope for this feature. Mark it as a follow-up.

**Files:**
- Modify: `agentharness/tui.py`

- [ ] **Step 1: Replace the module-level constant**

Edit `agentharness/tui.py:54-61`. Replace the literal dict:

```python
_PHASE_TO_QUEUE = {
    "analyzing": "analyst-queue",
    "architecting": "architect-queue",
    "designing": "designer-queue",
    "planning": "planner-queue",
    "developing": "developer-queue",
    "reviewing": "review-queue",
}
```

with a derivation from `STATE_TO_QUEUE`. The two call sites (`TaskLogPanel.update_for_task` line 343, `_derive_depths_from_cache` line 892-901) read `_PHASE_TO_QUEUE` keyed by the phase **string** value, so we keep the keys as strings:

```python
from agentharness.dispatcher import STATE_TO_QUEUE

_PHASE_TO_QUEUE = {
    status.value: queue
    for status, queue in STATE_TO_QUEUE.items()
    if queue is not None and status.value in {
        "analyzing", "architecting", "designing",
        "planning", "developing", "reviewing",
    }
}
```

(We exclude `dev_revision` from this derived map because the existing `_derive_depths_from_cache` and `TaskLogPanel.update_for_task` use the *phase* field of `TaskEntry` — which is always `"developing"` for revision tasks — not the `FeatureStatus` value.)

- [ ] **Step 2: Run all tests**

Run: `.venv/bin/pytest tests/ -v`
Expected: all green.

- [ ] **Step 3: Manual smoke test**

Re-run `.venv/bin/agentharness watch` and verify:
- Queue depth indicators in the status bar still reflect active phases.
- Task log panel still resolves logs correctly when a phase row is selected.

If anything broke, the most likely cause is a dropped key in the comprehension. Restore by running `grep -n _PHASE_TO_QUEUE agentharness/tui.py` and ensuring all callers still have the keys they expect.

- [ ] **Step 4: Commit**

```bash
git add agentharness/tui.py
git commit -m "refactor(tui): derive _PHASE_TO_QUEUE from dispatcher.STATE_TO_QUEUE

Removes the second copy of the state→queue knowledge. The legacy
_resume_phase still has its own inline copy because that flow has known
backend-coupling issues outside this feature's scope; tracked as
follow-up."
```

---

## Final verification

After all 8 tasks are committed, run the full test suite once more:

```bash
.venv/bin/pytest tests/ -v
```

Expected: every test green. Coverage of the new code paths:

| File | Tests covering it |
|------|-------------------|
| `agentharness/models.py` (with_tasks_cleared) | `test_models.py::TestWithTasksCleared` |
| `agentharness/dispatcher.py` (STATE_TO_QUEUE / queue_for_state / build_phase_task) | `test_dispatcher.py::TestStateToQueue`, `TestBuildPhaseTask` |
| `agentharness/state_change.py` | `test_state_change.py` (5 classes) |
| `agentharness/run_task.py` (orphan guard) | `test_run_task.py::TestOrphanTaskGuard` |
| `agentharness/tui_state_change.py::_options_for` | `test_tui_state_change.py::TestOptionsFor` |
| `agentharness/tui.py` (binding, action) | Manual smoke test (Task 7 Step 5) |

Then run a final manual smoke test of the dialog (Task 7 Step 5 checklist) against the live `STORAGE_BACKEND=github` configuration to confirm end-to-end behavior.

---

## Out of scope (for follow-up work)

These are **not** addressed by this plan; opening separate tickets is appropriate if needed:

1. Refactoring `tui._resume_phase` to use the pluggable storage factories. It currently hard-codes `BlobServiceClient.from_connection_string(...)` and is broken under `STORAGE_BACKEND=github`. Touching it would expand this PR significantly and is unrelated to the new `S` flow.
2. Calling `run_terminal_cleanup` for manually-failed features. Today only the dispatcher path triggers cleanup; manual `fail` skips worktree-preservation logging. Acceptable for v1 — the operator already knows the worktree exists.
3. Adding a structured `metadata: dict | None` field to `HistoryEvent`. We currently JSON-encode the metadata into `details: str` to avoid a schema migration on `state.json` blobs and GitHub issue bodies. Revisit when audit-export features need structured access.
4. Forward state jumps. The dialog is intentionally one-directional (rollback or restart only).
