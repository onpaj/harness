```markdown
# Architecture Review: TUI Feature State Change Dialog

## Architectural Fit Assessment

The feature aligns well with existing patterns: `tui.py` already contains a `ConfirmScreen(ModalScreen[bool])` pattern (`tui.py:403`), an `action_resume_task` workflow that re-enqueues a phase (`tui.py:614-749`), and an `_observer_pid`/`action_toggle_observer` operator-control pattern. The new `S` shortcut slots into the existing `BINDINGS` list at `tui.py:501-511` and uses the same `state_mgr.update(...)` + `queue.send_task(...)` two-step flow that `_resume_phase` already performs.

However, the existing `action_resume_task` flow is **the cautionary tale this feature must avoid replicating**. It hard-codes `BlobServiceClient.from_connection_string(...)` (`tui.py:642`), bypassing `create_state_manager`/`create_task_queue` factories — so it silently breaks under `STORAGE_BACKEND=github` (the active backend per `.pipeline/config.json:2`). It also re-defines `_PHASE_TO_QUEUE` locally (`tui.py:632-639`) and reconstructs `TaskMessage` payloads inline (`tui.py:689-695`), duplicating logic from `dispatcher._dispatch_linear` (`dispatcher.py:128-135`). The state-change feature must use the pluggable factories and reuse dispatcher helpers.

Three integration points require attention:
1. **`FeatureState` shape mismatch with spec.** Spec references `state.events` and `with_event_added()`; the real model (`models.py:107,114`) has `state.history: list[HistoryEvent]` with `state.with_event(event: str, **kwargs)` where the canonical field is `event` (not `reason`) and structured kwargs are `phase`, `task_id`, `worker_id`, `details`. The spec is wrong. The new event must conform to the existing schema.
2. **Missing `with_tasks_cleared()` helper.** `with_tasks_added([])` (`models.py:149`) **appends** an empty list — it does not clear. The spec's open question 1 must be resolved as "yes, add a new helper."
3. **No canonical state→queue mapping exists.** `dispatcher._LINEAR_TRANSITIONS` (`dispatcher.py:74`) only covers `analyzing/architecting/designing` and stores `(next_status, next_queue)`, not `current_status → queue`. `tui._PHASE_TO_QUEUE` (`tui.py:54`) is the closest match but is private and lacks `dev_revision`. The mapping must be extracted to a single source of truth.

## Proposed Architecture

### Component Overview

```
┌──────────────────────────── PipelineMonitor (App) ─────────────────────────────┐
│   BINDINGS  ──  ("s", "open_state_change", "Change state")                      │
│      │                                                                          │
│      ▼                                                                          │
│   action_open_state_change()                                                    │
│      • read selected FeatureState from self._states                             │
│      • guard: status == done → notify + return                                  │
│      • push_screen(StateChangeModal(state), callback)                           │
└────────────────────────────────────┬────────────────────────────────────────────┘
                                     │ dismiss(StateChangeResult | None)
                                     ▼
┌──────────────────── StateChangeModal (ModalScreen[StateChangeResult|None]) ────┐
│   ListView of state options (computed from current state index + "failed")     │
│   Bindings: ↑/↓ move, Enter confirm, Esc cancel                                │
│   Pure UI — no I/O. Reads only the FeatureState passed in.                     │
└────────────────────────────────────┬────────────────────────────────────────────┘
                                     │ StateChangeResult{target_status, mode}
                                     ▼
┌──────────────────────────── state_change.apply_state_change() ─────────────────┐
│   1. state_mgr.update(feature_id, mutator)                                     │
│        mutator: rebuild target state from latest snapshot each call            │
│          - mode="fail":     status=failed                                       │
│          - mode="restart":  status unchanged                                    │
│          - mode="rollback": status=target, optionally tasks=[]                  │
│        + with_event("manual_state_change", details=…)                          │
│   2. enqueue_for_state(persisted_state, queues, config)                        │
│        - skip for failed / brainstorming / brainstormed                         │
│        - reuses dispatcher._build_phase_task() helper (NEW, extracted)         │
│   3. on enqueue failure: retry once, then surface error                        │
└─────────────────────────────────────────────────────────────────────────────────┘
                                     │
            ┌────────────────────────┼─────────────────────────┐
            ▼                        ▼                         ▼
   create_state_manager       create_task_queue        agentharness.dispatcher
       (factory)                  (factory)            (TaskMessage builders)
```

### Key Design Decisions

#### Decision 1: Place the modal and service in a new module, not in `tui.py`
**Options considered:**
- (A) Add modal + apply function inside `tui.py`.
- (B) New module `agentharness/tui_state_change.py` containing both `StateChangeModal` and `apply_state_change`.
- (C) Split: modal in `tui_state_change.py`, headless service in `state_change.py`.

**Chosen approach:** (C).

**Rationale:** `tui.py` is already 910 lines (exceeds the 800-line ceiling in the project's coding standards). The headless service must be testable without Textual — splitting it makes unit testing trivial (no `App` fixtures, no Textual event loop). The modal stays UI-only. This also lets future surfaces (CLI command, web UI) reuse `apply_state_change` without importing Textual.

#### Decision 2: Single source of truth for state→queue mapping in `dispatcher.py`
**Options considered:**
- (A) New `agentharness/state_queue_map.py`.
- (B) Add `STATE_TO_QUEUE` dict and `queue_for_state()` helper to `dispatcher.py`; refactor `tui._PHASE_TO_QUEUE` and `tui._resume_phase`'s local copy to import it.
- (C) Inline the mapping in `state_change.py`.

**Chosen approach:** (B).

**Rationale:** `dispatcher.py` already owns pipeline routing; adding a sibling constant keeps related logic together. Three call sites (`tui._PHASE_TO_QUEUE`, `tui._resume_phase` local copy, new dialog) currently duplicate this knowledge — consolidating prevents drift. A new module for one dict is over-engineering.

#### Decision 3: Reuse dispatcher TaskMessage construction, do not re-implement
**Options considered:**
- (A) Re-implement the per-phase `TaskMessage` builders inside `state_change.py` (matches what `_resume_phase` already does).
- (B) Extract `_build_phase_task(state, target_phase)` from `dispatcher._dispatch_linear`/`_dispatch_fan_out` and call it from both dispatcher and `state_change`.
- (C) Call the dispatcher's existing private helpers.

**Chosen approach:** (B).

**Rationale:** `_resume_phase` already duplicates `_phase_inputs`/`_phase_outputs`/`_phase_agents` dicts that exist in `dispatcher._artifacts_for_phase` and `_output_name`. Extracting a `build_phase_task()` helper kills both the existing duplication and the new one. (A) compounds the technical debt; (C) couples external code to private APIs.

#### Decision 4: `with_event(reason="manual_state_change", ...)` — encode the contract in the existing `HistoryEvent`
**Options considered:**
- (A) Add a new `FeatureEvent` model as the spec proposes.
- (B) Use the existing `HistoryEvent`/`with_event` API; encode the metadata `{from, to, mode, tasks_cleared, actor}` into the existing `details: str | None` field as a JSON-encoded string or a structured one-line summary.
- (C) Add a `metadata: dict | None` field to `HistoryEvent`.

**Chosen approach:** (B) for the first revision, with (C) noted as a follow-up.

**Rationale:** The spec is wrong about the model shape — there is no `FeatureEvent` or `state.events`; there is `HistoryEvent` and `state.history`. Adding a new event type forks the audit log. Storing structured metadata as JSON in `details` is grep-able, sufficient for FR-1 audit, and avoids a schema migration on `state.json` blobs and GitHub issue bodies. If a future feature (audit export, FR-8 in a follow-up) needs structured metadata, add `HistoryEvent.metadata: dict | None` then — not now (YAGNI).

#### Decision 5: Closure-driven atomicity; enqueue-on-failure surfaces to operator (no automatic retry beyond once)
**Options considered:**
- (A) State update + enqueue inside one `state_mgr.update()` closure.
- (B) State update first, enqueue after; on enqueue failure retry once with backoff, then surface error and require operator retry.
- (C) Add a reconciliation pass to the observer.

**Chosen approach:** (B).

**Rationale:** (A) is impossible — the closure may run multiple times under lease contention, which would cause duplicate queue messages. (C) is out-of-scope and changes pipeline semantics. (B) matches the existing `_resume_phase` ordering and `dispatcher._dispatch_linear` (which also performs `send_task` then `update`). The closure must rebuild the new state from each fresh snapshot (idempotency under retry).

#### Decision 6: Orphaned queue messages — observer must be defensive; do not attempt deletion
**Options considered:**
- (A) Track and delete in-flight messages by pop receipt before rollback.
- (B) Make `run_task.py` defensively no-op when `task_id` is not in current `state.tasks`.
- (C) Sweep abandoned messages periodically.

**Chosen approach:** (B), with an audit event on drop.

**Rationale:** Pop receipts aren't accessible from the dialog (they belong to the receiving worker). `run_task._mark_started` already calls `with_task_update(task_id, ...)` (`run_task.py:111`), which is a silent no-op if the task is missing — but downstream `_dispatch_serial_next` assumes the task exists. Adding an explicit `if not any(t.task_id == task.task_id for t in state.tasks): emit "dropped_orphan_task" event; return` guard at the top of `run_task.run_task()` is small, observable, and works for both backends.

## Implementation Guidance

### Directory / Module Structure

```
agentharness/
  state_change.py            ← NEW. Pure-Python, no Textual imports.
                                 - apply_state_change(feature_id, target_status, mode, *, state_mgr, queue_factory) -> None
                                 - StateChangeResult dataclass (frozen)
                                 - StateChangeMode = Literal["restart", "rollback", "fail"]

  tui_state_change.py        ← NEW. Imports from state_change + agentharness.models.
                                 - StateChangeModal(ModalScreen[StateChangeResult | None])
                                 - State row label rendering (current/rollback/fail)

  dispatcher.py              ← MODIFY.
                                 - Add STATE_TO_QUEUE: dict[FeatureStatus, str | None]
                                 - Add queue_for_state(status) -> str | None
                                 - Extract build_phase_task(state, target_phase, config) -> TaskMessage
                                   reusing _artifacts_for_phase / _output_name

  models.py                  ← MODIFY.
                                 - Add FeatureState.with_tasks_cleared() -> FeatureState
                                   (returns model_copy(update={"tasks": [], "updated_at": ...}))

  tui.py                     ← MODIFY.
                                 - Add ("s", "open_state_change", "Change state") to BINDINGS
                                 - Add action_open_state_change()
                                 - Replace local _PHASE_TO_QUEUE with import from dispatcher
                                 - Refactor _resume_phase to use build_phase_task (incidental cleanup;
                                   keep scope tight if it grows the diff too much — note as follow-up)

  run_task.py                ← MODIFY.
                                 - Top of run_task(): refresh feature_state, if task.task_id present in
                                   message but not in state.tasks AND task is a developer/review task,
                                   log + emit "dropped_orphan_task" event + return (do not enqueue downstream).

tests/
  test_state_change.py       ← NEW. Tests for apply_state_change against fake state_mgr + queue_factory.
                                 - restart on each enqueueable state
                                 - rollback to planning clears tasks; rollback to reviewing does not
                                 - fail mode does not enqueue
                                 - brainstorming/brainstormed targets do not enqueue
                                 - retry-once on enqueue failure, then raises
  test_tui_state_change.py   ← NEW. Snapshot/list-rendering tests for StateChangeModal.
                                 - Pilot harness: open modal, navigate, confirm, verify dismissed value
  test_dispatcher.py         ← MODIFY. Add tests for STATE_TO_QUEUE coverage and build_phase_task.
  test_models.py             ← MODIFY (or add). Test with_tasks_cleared.
```

### Interfaces and Contracts

```python
# agentharness/state_change.py

from dataclasses import dataclass
from typing import Callable, Literal
from agentharness.models import FeatureStatus
from agentharness.storage_protocol import StateBackend, TaskQueue

StateChangeMode = Literal["restart", "rollback", "fail"]

@dataclass(frozen=True)
class StateChangeResult:
    target_status: FeatureStatus
    mode: StateChangeMode

class StateChangeError(Exception):
    """Raised when the state was updated but the enqueue ultimately failed.
    Operator must retry from the dialog."""

QueueFactory = Callable[[str], TaskQueue]  # queue_name -> TaskQueue

async def apply_state_change(
    feature_id: str,
    result: StateChangeResult,
    *,
    state_mgr: StateBackend,
    queue_factory: QueueFactory,
    config,  # agentharness.config.Config — needed for build_phase_task
) -> None:
    """Atomically transition a feature and enqueue follow-up work.

    Contract:
      - Always performs at most one state_mgr.update() (closure may retry under
        lease contention; closure rebuilds output from the fresh snapshot).
      - Skips enqueue when target maps to None (failed/brainstorming/brainstormed).
      - On enqueue failure: retries once with 1s backoff, then raises StateChangeError
        with the persisted target state attached so the caller can show "state
        updated but enqueue failed — retry?".
    """
```

```python
# agentharness/dispatcher.py — additions

STATE_TO_QUEUE: dict[FeatureStatus, str | None] = {
    FeatureStatus.brainstorming: None,
    FeatureStatus.brainstormed:  None,
    FeatureStatus.analyzing:     "analyst-queue",
    FeatureStatus.architecting:  "architect-queue",
    FeatureStatus.designing:     "designer-queue",
    FeatureStatus.planning:      "planner-queue",
    FeatureStatus.developing:    "developer-queue",
    FeatureStatus.reviewing:     "review-queue",
    FeatureStatus.dev_revision:  "developer-queue",
    FeatureStatus.done:          None,
    FeatureStatus.failed:        None,
}

def queue_for_state(status: FeatureStatus) -> str | None: ...

def build_phase_task(
    state: FeatureState,
    target_status: FeatureStatus,
    config: Config,
) -> TaskMessage:
    """Construct a phase-restart TaskMessage. Reuses _artifacts_for_phase / _output_name."""
```

```python
# agentharness/models.py — addition

def with_tasks_cleared(self) -> FeatureState:
    """Return new state with tasks=[] (immutable)."""
    return self.model_copy(update={"tasks": [], "updated_at": datetime.now(UTC)})
```

```python
# agentharness/tui_state_change.py — sketch

class StateChangeModal(ModalScreen[StateChangeResult | None]):
    BINDINGS = [
        ("escape", "dismiss(None)", "Cancel"),
        ("enter",  "confirm",       "Confirm"),
    ]
    def __init__(self, feature_state: FeatureState): ...
    def compose(self) -> ComposeResult: ...
    def action_confirm(self) -> None: ...

    @staticmethod
    def _options_for(state: FeatureState) -> list[tuple[FeatureStatus, StateChangeMode, str]]:
        """Return [(status, mode, label)] — earlier states + current (restart) + failed."""
```

### Data Flow

**Restart (current state) — happy path:**
1. User selects feature, presses `S` → modal opens with the cached `FeatureState` (no I/O, sub-100ms per NFR-1).
2. User confirms current row → modal dismisses with `StateChangeResult(target=current, mode="restart")`.
3. `apply_state_change` calls `state_mgr.update(feature_id, lambda s: s.with_event("manual_state_change", details='{"from": "...", "to": "...", "mode": "restart", "actor": "tui"}'))`.
4. After update commits, `queue_for_state(persisted.status)` returns `"developer-queue"` (e.g.) → `build_phase_task(persisted, persisted.status, config)` → `queue_factory("developer-queue").send_task(task)`.
5. UI shows toast `"State changed: developing → developing (restart)"`. Next 2s tick refreshes the event log.

**Rollback `reviewing` → `planning`:**
1. Modal returns `StateChangeResult(target=planning, mode="rollback")`.
2. Closure: `s.with_status(planning).with_tasks_cleared().with_event("manual_state_change", details='{...,"tasks_cleared": true}')`.
3. Enqueue: `queue_for_state(planning) == "planner-queue"` → `build_phase_task(persisted, planning, config)` → enqueue.
4. The previous in-flight developer/review queue messages (if any) are now orphans. When a worker eventually processes one, `run_task.run_task()` sees `task.task_id` is not in `state.tasks`, emits `dropped_orphan_task`, and returns without state changes.

**Mark failed:**
1. Modal returns `StateChangeResult(target=failed, mode="fail")`.
2. Closure: `s.with_status(failed).with_event(...)`.
3. `queue_for_state(failed) is None` → no enqueue.
4. `dispatcher.run_terminal_cleanup(persisted, state_mgr)` is **not** invoked (cleanup currently only runs from the dispatcher path; manual fails skip worktree-preservation logging — acceptable for v1, listed under Risks).

## Risks and Mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| Spec-defined `state.events` / `FeatureEvent` does not match real model (`state.history` / `HistoryEvent`); developers may add a new model and fork the audit log | High | Reuse `with_event(event="manual_state_change", details=<json>)`. State this explicitly in the impl plan. |
| `with_tasks_added([])` ≠ clear (the spec assumes it does) — using it would silently no-op the rollback | High | Add `with_tasks_cleared()` helper. Code review must flag any use of `with_tasks_added([])` as the clearing primitive. |
| Existing `tui._resume_phase` already bypasses backend factories — copying its pattern would re-introduce the GitHub-backend bug | High | Use `create_state_manager(config)` and `create_task_queue(config, name)` factories exclusively. Add a regression test that mocks both backends. |
| State updated but enqueue fails (network, queue down) → feature stuck in active state with no work scheduled | Medium | Retry enqueue once with 1s backoff. If still fails, raise `StateChangeError` carrying the persisted state; modal shows error and stays open for "retry enqueue" (calls only the enqueue half). |
| Orphaned queue messages from cleared tasks are picked up by workers and crash on missing `task_id` | Medium | Defensive guard in `run_task.run_task()`: if dev/review task's `task_id` not in `state.tasks`, emit `dropped_orphan_task` event and return early. |
| Lease retry duplicates the audit event (the closure would append a second event on retry) | Medium | The closure must always rebuild from the fresh snapshot. Specifically: the event is appended onto `s.history` of the snapshot, not onto a captured outer variable. Test by mocking `state_mgr.update` to invoke the closure twice and asserting only one event is in the final state. |
| Manually-failed feature does not run `run_terminal_cleanup` (worktree not removed/preserved-with-log) | Low | Acceptable for v1 — manual `fail` is operator-driven; the operator already knows the worktree exists. Document in CLAUDE.md as known behavior. Follow-up ticket if needed. |
| `dev_revision` restart semantics (open question 4) — which task to re-enqueue? | Low | Re-enqueue the most recent `in_progress` developer task by reusing its `queued_message` (same as `action_resume_task`). If none in-progress, restart re-runs the next `pending` task. Document in apply_state_change docstring. |
| `tui.py` already > 800 lines; adding the `S` action and import grows it further | Low | New code lives in `tui_state_change.py` and `state_change.py`. The only additions to `tui.py` are: 1 binding, 1 short action method (~10 lines). |
| Concurrent operator presses `S` twice quickly | Low | `state_mgr.update()` serializes via lease/optimistic-lock. Second update sees the post-first-change state; the modal recomputes options on each open. |

## Specification Amendments

1. **Replace `state.events` / `FeatureEvent` / `with_event_added()` references with the real API.** Use `state.history`, `HistoryEvent`, and `state.with_event(event="manual_state_change", details=<json-string>)`. The `metadata` payload (`from`, `to`, `mode`, `tasks_cleared`, `actor`) is JSON-serialized into `details`.
2. **Add `FeatureState.with_tasks_cleared()` to the data model section** (resolves Open Question 1 — `with_tasks_added([])` does not clear, it appends).
3. **Place mapping in `dispatcher.py` as `STATE_TO_QUEUE` keyed by `FeatureStatus`** (not strings). Expose `queue_for_state(status)`.
4. **Extract `build_phase_task(state, target_status, config)` from `dispatcher`.** Both `_dispatch_linear` and the new `apply_state_change` call it. The current spec says "if helpers are not exposed, refactor minimally"; mark this as required, not optional.
5. **`StateChangeModal` is in `agentharness/tui_state_change.py`, headless service in `agentharness/state_change.py`.** Do not put either in `tui.py` (already over the 800-line limit).
6. **Confirm `brainstormed` IS in the enum** (`models.py:14`). Open Question 8 resolves to: include `brainstormed`, but it has no queue and is not enqueueable on rollback.
7. **Resolve Open Question 2 (orphan messages):** add the defensive guard in `run_task.run_task()` and emit `dropped_orphan_task` event. This is in scope for this feature.
8. **Resolve Open Question 3 (atomicity boundary):** retry enqueue once, then raise `StateChangeError` carrying the persisted state. Modal stays open and offers "retry enqueue" (which calls only the enqueue half — state is already updated).
9. **Resolve Open Question 7 (extra confirmation):** none required for `restart`/`rollback`. **Add** a `ConfirmScreen` step for `mode="fail"` only — failing a feature is destructive enough to warrant a second keypress, and the existing `ConfirmScreen` (`tui.py:403`) is the project's established pattern for destructive ops.
10. **NFR-1 latency for `dialog opens within 100ms`** is achievable because the modal uses the already-cached `self._states` list — no I/O on `compose()`. Document this constraint: `StateChangeModal.__init__` must not perform I/O.

## Prerequisites

- **No infrastructure changes.** No new queues, no new labels, no schema migrations on `state.json` or GitHub issue bodies.
- **No new dependencies.** Reuses Textual, Pydantic, existing `StateBackend`/`TaskQueue` protocols.
- **Code prerequisites (must merge before or with feature implementation):**
  - `FeatureState.with_tasks_cleared()` helper in `agentharness/models.py`.
  - `STATE_TO_QUEUE` constant + `queue_for_state()` + `build_phase_task()` in `agentharness/dispatcher.py`.
  - Defensive orphan-task guard in `agentharness/run_task.py:run_task` (top-of-function check).
- **Test prerequisites:** `tests/` already has `test_dispatcher.py` patterns to extend; no new test infrastructure needed. Use Textual's `App.run_test()` pilot harness (already implied by Textual being in dependencies) for modal navigation tests.
- **Backend coverage:** Both `STORAGE_BACKEND=azure` and `STORAGE_BACKEND=github` must pass tests. The `apply_state_change` service depends only on the `StateBackend` and `TaskQueue` protocols, so a single suite using fakes covers both backends. The current production config is `github` (`.pipeline/config.json:2`), so this path must be exercised first.
```