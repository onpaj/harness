# Architecture Review: TUI Feature State Change Dialog

## Architectural Fit Assessment

The feature aligns cleanly with the existing architecture. AgentHarness already exposes the three primitives this dialog needs:

1. **Atomic state mutation** — `StateBackend.update(feature_id, mutator)` (`storage_protocol.py:43-47`) is the single contract used throughout the system; both Azure and GitHub backends implement it. The dialog must not bypass it.
2. **State→queue routing** — `STATE_TO_QUEUE` (`dispatcher.py:83-95`, recently centralized per commit `192bc11`) is already the authoritative mapping. Reuse it.
3. **TaskMessage construction per phase** — `build_phase_task(state, target_status, config)` (`dispatcher.py:463-544`) already encapsulates the per-phase TaskMessage build logic for analyst/architect/designer/planner/developer/dev_revision/reviewing. This is exactly what the dialog needs to avoid duplicating dispatcher logic.

The integration points are: a Textual `ModalScreen` registered against the existing `PipelineMonitor` BINDINGS, plus a headless service module that orchestrates `StateBackend.update()` and queue enqueue. **OQ-2 is closed:** `STATE_TO_QUEUE` lives in `dispatcher.py` and the dialog imports from there — no new `state_routing.py` extraction needed unless a circular import surfaces (none expected since the TUI already imports from dispatcher).

**OQ-3 is closed by reading the model:** `FeatureState.with_tasks_cleared()` (`models.py:155`) and `with_event(event_name, **kwargs)` (`models.py:114`) already exist. **No new immutable helpers required.** The spec's proposed `with_tasks_replaced([])` and `with_event_appended({...})` are not idiomatic to this codebase — the existing API uses a flat `HistoryEvent(event, phase, task_id, details, …)` shape, not arbitrary JSON dicts. The dialog must conform.

## Proposed Architecture

### Component Overview

```
┌────────────────────────────────────────────────────────────────┐
│ PipelineMonitor (tui.py)                                       │
│   BINDINGS: ("s", "open_state_change", "Change state")         │
│   action_open_state_change():                                  │
│     - guard: feature selected, status != done                  │
│     - push_screen(StateChangeModal(state), on_result)          │
└──────────────────────────┬─────────────────────────────────────┘
                           │ pushes
                           ▼
┌────────────────────────────────────────────────────────────────┐
│ StateChangeModal (tui_state_change.py)            [UI only]    │
│   - reads FeatureState passed in (no I/O)                      │
│   - _options_for(state) → [(status, mode, label), …]           │
│   - dismiss(StateChangeResult(target_status, mode))            │
└──────────────────────────┬─────────────────────────────────────┘
                           │ result via callback
                           ▼
┌────────────────────────────────────────────────────────────────┐
│ apply_state_change (state_change.py)         [headless I/O]    │
│   1. state_mgr.update(feature_id, mutator)                     │
│        → mutator: with_status / with_tasks_cleared /           │
│          with_event("manual_state_change", details=…)          │
│   2. queue_for_state(persisted.status) → name | None           │
│   3. build_phase_task(persisted, status, config) → TaskMessage │
│   4. queue_factory(name).send_task(task) with 1 retry          │
│   5. raise StateChangeError on enqueue failure                 │
└────────────────────────┬───────────────────────────────────────┘
                         │ uses
                         ▼
┌────────────────────────────────────────────────────────────────┐
│ Existing primitives                                            │
│   • StateBackend.update()      (atomic, lease/optimistic-lock) │
│   • dispatcher.STATE_TO_QUEUE  (single source of truth)        │
│   • dispatcher.build_phase_task (per-phase TaskMessage build)  │
│   • storage.create_task_queue  (factory, queue per call)       │
└────────────────────────────────────────────────────────────────┘
```

### Key Design Decisions

#### Decision 1: Three-layer split (UI / service / dispatcher helpers)
**Options considered:**
- (a) All logic inside `StateChangeModal` — rejected: untestable without Textual, leaks I/O into UI.
- (b) Two-layer (Modal + state_change service) duplicating TaskMessage construction — rejected: drift from dispatcher.
- (c) Three-layer reusing `dispatcher.build_phase_task` and `STATE_TO_QUEUE` — **chosen**.

**Chosen approach:** UI module produces a small `StateChangeResult` dataclass; a headless service (`state_change.py`) consumes that result and orchestrates `state_mgr.update` + queue send by reusing dispatcher's existing helpers.

**Rationale:** Test coverage stays in pure-Python layers. The dispatcher remains the single source of truth for "how to enqueue phase X" — no risk of forward-state logic and rollback logic diverging.

#### Decision 2: `StateChangeResult` carries `mode` separately from `target_status`
**Options considered:**
- (a) Service derives mode by comparing `target_status` to `current_status` — rejected: ambiguity for `failed` (could be a target or a sentinel).
- (b) Modal emits `mode: Literal["restart","rollback","fail"]` alongside the status — **chosen**.

**Rationale:** The mode is determined in the UI by *which row* the user picked (current row → restart, earlier → rollback, `failed` row → fail). Encoding it explicitly avoids re-deriving operator intent in the service and makes the audit log unambiguous.

#### Decision 3: Event log entry uses existing `with_event(event_name, details=…)` API
**Options considered:**
- (a) Add a new `with_event_appended(dict)` for arbitrary JSON event payloads (per spec) — rejected: deviates from `HistoryEvent` schema and breaks `EventLogPanel.update_events` formatting.
- (b) Use `with_event("manual_state_change", details=json.dumps({…}))` — **chosen**.

**Rationale:** Keeps the model's event schema flat and stable. The `details` field is already a free-form string consumed by the UI; embedding JSON there preserves machine-readability without a model migration.

#### Decision 4: Enqueue happens **after** the state commit, with a single retry
**Options considered:**
- (a) Two-phase commit across state and queue — rejected: neither backend supports it; complexity not justified.
- (b) Roll back state on enqueue failure — rejected: a partial rollback can itself fail, leaving worse state.
- (c) Best-effort enqueue with one retry; on failure raise a typed `StateChangeError` carrying `persisted_status` so the UI can offer a "retry enqueue only" path — **chosen**.

**Rationale:** State persistence is the load-bearing invariant; queue messages are recoverable by re-running the dialog with the same target ("restart current state"). The typed exception lets the TUI render an actionable message.

#### Decision 5: `failed` features can open the dialog (closes OQ-1)
**Chosen approach:** Only `done` is excluded. `failed` is included because recovery from `failed` is the primary use case. The `_options_for()` function uses `CANONICAL_STATE_ORDER` and gates inclusion by membership; `failed` is rendered as the always-present last row, not as a state in the list itself.

**Rationale:** Treating `failed` specially here would violate the brief's stated goal of "roll back any stuck or failed feature."

## Implementation Guidance

### Directory / Module Structure

| File | Responsibility |
|------|----------------|
| `agentharness/state_change.py` | `apply_state_change()`, `StateChangeResult`, `StateChangeError`, `CLEAR_TASKS_STATES`, `StateChangeMode` literal. **No Textual imports.** |
| `agentharness/tui_state_change.py` | `StateChangeModal(ModalScreen)`, `_options_for()`, `CANONICAL_STATE_ORDER`. **No I/O, no storage imports.** |
| `agentharness/tui.py` | One new `Binding("s", "open_state_change", "Change state")`; `action_open_state_change()` glues modal → `apply_state_change`. |
| `agentharness/dispatcher.py` | Unchanged — reused for `STATE_TO_QUEUE`, `queue_for_state()`, `build_phase_task()`. |
| `agentharness/models.py` | Unchanged — `with_status`, `with_tasks_cleared`, `with_event` already cover all needs. |
| `tests/test_state_change.py` | Service-level tests with fake `StateBackend` + fake `TaskQueue`. |
| `tests/test_tui_state_change.py` | `_options_for()` table-driven tests; no Textual runtime needed. |

### Interfaces and Contracts

```python
# state_change.py
StateChangeMode = Literal["restart", "rollback", "fail"]

@dataclass(frozen=True)
class StateChangeResult:
    target_status: FeatureStatus
    mode: StateChangeMode

class StateChangeError(Exception):
    def __init__(self, message: str, persisted_status: FeatureStatus): ...

QueueFactory = Callable[[str], TaskQueue]   # name → freshly-opened queue

async def apply_state_change(
    feature_id: str,
    result: StateChangeResult,
    *,
    state_mgr: StateBackend,
    queue_factory: QueueFactory,
    config: Config,
) -> None: ...

CLEAR_TASKS_STATES: frozenset[FeatureStatus]   # brainstorming…planning
```

**Mutator contract** (must be deterministic and rebuild from snapshot — Azure backend may invoke under lease retry):
- `mode == "fail"` → `with_status(failed) + with_event("manual_state_change", details=json)`.
- `mode == "restart"` → `with_event(...)` only; status unchanged; tasks unchanged.
- `mode == "rollback"` → `with_status(target)`, then `with_tasks_cleared()` iff `target ∈ CLEAR_TASKS_STATES`, then `with_event(...)`.

**`details` JSON schema** (string field on `HistoryEvent`):
```json
{"from":"developing","to":"planning","mode":"rollback","tasks_cleared":true,"actor":"tui"}
```

**Modal contract:**
- `__init__(feature_state: FeatureState)` — pure UI; reads everything off the snapshot.
- Dismisses with `StateChangeResult | None` (None = cancel).
- `_options_for(state)` is a `@staticmethod` and **the unit-test surface**.

### Data Flow

**Rollback `developing → planning`:**
1. User presses `S` → `action_open_state_change` → `push_screen(StateChangeModal(state))`.
2. Modal builds rows from `_options_for`, user picks `planning` row → dismiss `StateChangeResult(planning, "rollback")`.
3. `_do_apply_state_change` opens a fresh `state_mgr` and calls `apply_state_change`.
4. `state_mgr.update` runs mutator: `with_status(planning).with_tasks_cleared().with_event(...)`. Atomic via blob lease (Azure) or optimistic update (GitHub).
5. `queue_for_state(planning) → "planner-queue"`. `build_phase_task` returns the planner TaskMessage.
6. `queue_factory("planner-queue").send_task(task)`; on failure retries once, else raises `StateChangeError`.
7. TUI shows toast and triggers `_refresh_data`.

**Restart `developing` (current):**
- Same flow; mutator only appends event. `build_phase_task(state, developing, config)` returns the existing in-progress or next-pending dev TaskMessage from `state.tasks[*].queued_message` — already covered by dispatcher logic. Closes **OQ-4**.

**Mark `failed`:**
- Mutator sets status to `failed`; `queue_for_state(failed) → None`; service returns without enqueue.

## Risks and Mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| Mutator runs multiple times under lease retry, duplicating audit events | High | Mutator must rebuild new state from the snapshot argument every call — never close over a cached `prev_status` outside the closure. Each retry receives the current snapshot, so the produced state is idempotent w.r.t. the input. |
| `build_phase_task` for `developing/dev_revision/reviewing` requires existing TaskEntry data; rolling back to `developing` after tasks have been cleared would fail | Medium | Tasks are only cleared when the **target** is `≤ planning` — never when target is `developing/reviewing/dev_revision`. The service's CLEAR_TASKS_STATES set encodes this invariant. Add an assertion in `apply_state_change` to fail loud if the invariant is violated. |
| State persisted but enqueue fails → operator sees stale TUI | Medium | One automatic retry; on second failure raise `StateChangeError(persisted_status=…)`. UI displays "State updated but re-queue failed — press S to retry" and refreshes the cached state so the next `S` shows the new status. |
| Concurrent state change conflict | Low | `StateBackend.update` already retries on lease/optimistic conflict; if it ultimately raises, surface as `notify(severity="error")` and keep the dialog/state cache consistent on next refresh. |
| `S` keybinding collides with future shortcuts | Low | Verified currently unbound; document in `BINDINGS` with `show=True` so it appears in the footer. |
| TUI blocks during state commit + enqueue (≤2s p95) | Low | All I/O runs in `self.run_worker(coro, exclusive=False)` — Textual schedules off the render loop. The 2s refresh tick is unaffected. |
| `failed` re-rollback creates impossible TaskMessage (no in-progress dev task) | Medium | When rolling back from `failed` to `developing/reviewing/dev_revision`, `build_phase_task` will raise `ValueError` (already in dispatcher). Catch this in `apply_state_change` and convert to `StateChangeError` with a clear operator message; suggest rolling back further (to `planning` or earlier). |
| Event log JSON in `details` is not human-readable in the existing `EventLogPanel` | Low | Acceptable: the panel already displays `details` as italic dim text; JSON is short enough to read. Future enhancement: pretty-print `manual_state_change` events specifically. |

## Specification Amendments

1. **Replace `with_tasks_replaced([])` and `with_event_appended({...})` with existing helpers.** The model already provides `with_tasks_cleared()` and `with_event(event_name, **kwargs)`. **Do not add new model helpers.** The spec's OQ-3 is resolved: no model changes required.
2. **Event payload shape changes.** The spec proposes a nested JSON event entry (`{"kind": "manual_state_change", "from": …, "to": …, "action": …}`). This conflicts with the existing `HistoryEvent` schema (`event: str`, `phase`, `task_id`, `details: str`, `worker_id`). **Encode the structured payload as a JSON-serialized string in `details`**, with `event="manual_state_change"`. Acceptance criteria for FR-3/FR-4/FR-5/FR-6 should be reworded accordingly.
3. **Rename action enum: `restart | rollback | fail`** (the spec's `action_label` field is correct; `event_kind` is dropped because `event` is always `"manual_state_change"`).
4. **`StateChangeAction` dataclass is unnecessary.** The dispatch logic is small enough to live inline in `apply_state_change` as branches on `result.mode`. Replace with a single literal `StateChangeMode = Literal["restart","rollback","fail"]` and the existing `StateChangeResult(target_status, mode)`.
5. **Drop spec FR-7's "first non-completed TaskEntry" custom logic.** Reuse `dispatcher.build_phase_task`, which already implements the correct per-state TaskMessage construction. Closes OQ-4.
6. **Drop spec FR-3's "no queue for brainstorming" branch error UX.** It is unreachable: the modal's `CANONICAL_STATE_ORDER` lists `brainstorming/brainstormed`, but selecting them from a feature in `analyzing+` is a valid rollback target — the service simply skips enqueue when `queue_for_state(target) is None` and returns success. The status message is unnecessary.
7. **OQ-5 (preview impact) deferred.** Out of scope for r1. The modal's per-row label can include `(rollback)` / `(current — restart)` / `(mark failed)` suffixes — sufficient transparency without computing task counts.
8. **OQ-6 (success feedback) resolved.** Use Textual `app.notify()` from `_do_apply_state_change` after success; on `StateChangeError` use `notify(severity="error")`.

## Prerequisites

None blocking — all infrastructure already exists:

- `STATE_TO_QUEUE` and `build_phase_task()` are in `dispatcher.py` (commit `192bc11`).
- `FeatureState.with_tasks_cleared()` and `with_event()` are in `models.py`.
- `StateBackend.update()` atomicity contract is honored by both Azure and GitHub backends.
- `create_task_queue(config, name)` factory is available in `storage.py`.
- `S` is unbound in current `PipelineMonitor.BINDINGS`.

**Implementation order suggested:**
1. `state_change.py` + `tests/test_state_change.py` (TDD-friendly, no UI).
2. `tui_state_change.py` + `tests/test_tui_state_change.py` (pure `_options_for()` table tests).
3. Wire `action_open_state_change` into `tui.py`, including `done` exclusion and `notify` surfaces.
4. Manual smoke test against both Azure and GitHub backends: rollback `developing → planning`, restart current, mark `failed`, recover from `failed → developing`.