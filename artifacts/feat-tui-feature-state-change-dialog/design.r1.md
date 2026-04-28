# Design: TUI Feature State Change Dialog

## UX/UI Design

### Keyboard Binding

The `S` key is registered on `PipelineMonitor` with `show=True` so it appears in the footer. The binding is a no-op when no feature is selected or when the selected feature is in `done` state; no visual feedback is given for the no-op case (silent guard).

### Modal Layout (ASCII Wireframe)

```
┌─────────────────────────────────────────────────────────────┐
│  Change State — feat-20260425-abc123                        │
│  Current state: developing                                  │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌───────────────────────────────────────────────────────┐  │
│  │   brainstorming                         (rollback)    │  │
│  │   analyzing                             (rollback)    │  │
│  │   architecting                          (rollback)    │  │
│  │   designing                             (rollback)    │  │
│  │   planning                (rollback — clears 3 tasks) │  │
│  │ ▶ developing              (current — restart)         │  │
│  │   ─────────────────────────────────────────────────── │  │
│  │   failed                            (mark as failed)  │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                             │
│       Enter to confirm  ·  Escape to cancel                 │
└─────────────────────────────────────────────────────────────┘
```

**Row annotations:**
- States earlier than current: `(rollback)` suffix; if target ≤ `planning`, suffix becomes `(rollback — clears N tasks)` where N is `len(state.tasks)` (zero cost: already in memory).
- Current state: `(current — restart)` suffix. For `dev_revision`, the `developing` row carries this suffix.
- `failed` row: always present, separated by a horizontal rule `─────`, labelled `(mark as failed)`.
- Arrow-key navigation highlights rows via Textual's default `ListView` focus styling.

**Interaction flow:**

```
S keypress
    │
    ├─ no feature selected ──────────────────────────────► (no-op, silent)
    ├─ feature.status == done ──────────────────────────► (no-op, silent)
    └─ eligible feature
           │
           ▼
    StateChangeModal opens (async state re-fetch on mount)
           │
           ├─ Escape / click-outside ──────────────────► dismiss(None) → no-op
           └─ user selects row + Enter
                  │
                  ▼
           dismiss(StateChangeResult(target_status, mode))
                  │
                  ▼
           _do_apply_state_change (Textual worker)
                  │
                  ├─ success ──► app.notify("developing → planning") + _refresh_data()
                  └─ StateChangeError
                         ├─ state persisted, enqueue failed
                         │      └─► notify(error, "State updated — press S to retry enqueue")
                         │          + _refresh_data() [show new status]
                         └─ state commit failed
                                └─► notify(error, "Commit failed — please retry")
                                    [dialog stays open with refreshed state]
```

### Component Hierarchy

```
PipelineMonitor (Screen)
└── StateChangeModal (ModalScreen)
    └── Vertical
        ├── Label            # title: "Change State — {feature_id}"
        ├── Static           # subtitle: "Current state: {status}"
        ├── ListView         # one ListItem per eligible target
        │   └── ListItem × N # label + right-aligned mode annotation
        ├── Static           # "Enter to confirm · Escape to cancel"
        └── Static (hidden)  # inline error message (shown on commit failure)
```

---

## Component Design

### `agentharness/state_change.py` — headless service (no Textual imports)

**Responsibilities:**
- Owns `StateChangeMode`, `StateChangeResult`, `StateChangeError`, `CLEAR_TASKS_STATES`.
- Implements `apply_state_change()`: orchestrates `state_mgr.update()` → optional enqueue.
- Builds the mutator closure passed to `state_mgr.update()`.

**Public interface:**

```python
StateChangeMode = Literal["restart", "rollback", "fail"]

@dataclass(frozen=True)
class StateChangeResult:
    target_status: FeatureStatus
    mode: StateChangeMode

class StateChangeError(Exception):
    message: str
    persisted_status: FeatureStatus   # status as committed; None if commit failed

QueueFactory = Callable[[str], TaskQueue]

async def apply_state_change(
    feature_id: str,
    current_state: FeatureState,
    result: StateChangeResult,
    *,
    state_mgr: StateBackend,
    queue_factory: QueueFactory,
    config: Config,
) -> FeatureState: ...                 # returns persisted state snapshot

CLEAR_TASKS_STATES: frozenset[FeatureStatus]  # {brainstorming, brainstormed, analyzing,
                                               #  architecting, designing, planning}
```

**Mutator contract** (must be a deterministic pure function of its snapshot argument — safe under Azure lease retry):

| `mode` | Mutations applied to snapshot |
|--------|-------------------------------|
| `"fail"` | `with_status(failed)` → `with_event(...)` |
| `"restart"` | `with_event(...)` only; status and tasks unchanged |
| `"rollback"` | `with_status(target)` → `with_tasks_cleared()` iff `target ∈ CLEAR_TASKS_STATES` → `with_event(...)` |

**Error handling:**
- `state_mgr.update()` raises → `StateChangeError(persisted_status=None)` — commit failed.
- Enqueue fails on first try → retry once (same `queue_factory` call).
- Enqueue fails on second try → `StateChangeError(persisted_status=committed_status)` — state is updated, queue is not.

---

### `agentharness/tui_state_change.py` — Textual modal (no I/O, no storage imports)

**Responsibilities:**
- Renders the `StateChangeModal` using the `FeatureState` snapshot passed at construction.
- Computes eligible target list via `_options_for()` static method.
- Dismisses with `StateChangeResult | None`.

**Public interface:**

```python
@dataclass(frozen=True)
class RowOption:
    status: FeatureStatus
    mode: StateChangeMode
    label: str                # full display string including annotation

class StateChangeModal(ModalScreen[StateChangeResult | None]):
    def __init__(self, feature_state: FeatureState) -> None: ...

    @staticmethod
    def _options_for(state: FeatureState) -> list[RowOption]: ...
    # Pure function — primary unit-test surface.
    # Rows: CANONICAL_STATE_ORDER up to (and including) effective_current,
    # plus a "failed" sentinel row.
    # effective_current: dev_revision → developing (treated as same row).

CANONICAL_STATE_ORDER: list[FeatureStatus]
# [brainstorming, brainstormed, analyzing, architecting, designing,
#  planning, developing, reviewing, done]
# "done" included in the constant for completeness but never returned by _options_for.
```

---

### `agentharness/tui.py` — glue additions (minimal changes)

**New binding:**
```python
Binding("s", "open_state_change", "Change state", show=True)
```

**New methods:**

```python
async def action_open_state_change(self) -> None:
    feature = self._selected_feature()
    if feature is None or feature.status == FeatureStatus.DONE:
        return
    await self.push_screen(
        StateChangeModal(feature),
        self._on_state_change_result,
    )

async def _on_state_change_result(
    self, result: StateChangeResult | None
) -> None:
    if result is None:
        return
    self.run_worker(self._do_apply_state_change(result), exclusive=False)

async def _do_apply_state_change(self, result: StateChangeResult) -> None:
    # calls apply_state_change(...), handles StateChangeError,
    # calls self.app.notify(...), calls self._refresh_data()
```

All storage I/O runs inside `run_worker` — the 2-second TUI refresh loop is never blocked.

---

### `agentharness/dispatcher.py` — unchanged (reused)

Reused exports:

| Symbol | Usage |
|--------|-------|
| `STATE_TO_QUEUE: dict[FeatureStatus, str \| None]` | Queue name lookup in `apply_state_change` |
| `build_phase_task(state, target_status, config) → TaskMessage` | TaskMessage construction for enqueue |

No changes to this file.

---

### `agentharness/models.py` — unchanged (existing helpers sufficient)

Reused methods on `FeatureState`:

| Method | Used for |
|--------|---------|
| `with_status(status)` | Status mutation in mutator |
| `with_tasks_cleared()` | Task clearing on rollback to ≤ planning |
| `with_event(event_name, **kwargs)` | Audit log append in mutator |

No new methods added.

---

### Test modules

| File | Scope |
|------|-------|
| `tests/test_state_change.py` | `apply_state_change` — all six paths: restart, rollback-clear, rollback-keep, fail, no-queue (brainstorming), enqueue-failure-after-commit. Uses fake `StateBackend` and fake `TaskQueue`. |
| `tests/test_tui_state_change.py` | `StateChangeModal._options_for()` — table-driven, no Textual runtime. Cases: brainstorming, analyzing, developing, dev_revision, reviewing, failed. |

---

## Data Schemas

### `StateChangeResult` (dataclass, frozen)

```python
@dataclass(frozen=True)
class StateChangeResult:
    target_status: FeatureStatus   # enum value selected by operator
    mode: StateChangeMode          # "restart" | "rollback" | "fail"
```

### `StateChangeError`

```python
class StateChangeError(Exception):
    def __init__(
        self,
        message: str,
        persisted_status: FeatureStatus | None,
    ) -> None: ...
    # persisted_status: None  → commit never completed
    # persisted_status: value → commit succeeded, enqueue failed
```

### `RowOption` (dataclass, frozen)

```python
@dataclass(frozen=True)
class RowOption:
    status: FeatureStatus
    mode: StateChangeMode
    label: str    # e.g. "planning   (rollback — clears 5 tasks)"
```

### `CLEAR_TASKS_STATES` constant

```python
CLEAR_TASKS_STATES: frozenset[FeatureStatus] = frozenset({
    FeatureStatus.BRAINSTORMING,
    FeatureStatus.BRAINSTORMED,
    FeatureStatus.ANALYZING,
    FeatureStatus.ARCHITECTING,
    FeatureStatus.DESIGNING,
    FeatureStatus.PLANNING,
})
```

### `CANONICAL_STATE_ORDER` constant

```python
CANONICAL_STATE_ORDER: list[FeatureStatus] = [
    FeatureStatus.BRAINSTORMING,
    FeatureStatus.BRAINSTORMED,
    FeatureStatus.ANALYZING,
    FeatureStatus.ARCHITECTING,
    FeatureStatus.DESIGNING,
    FeatureStatus.PLANNING,
    FeatureStatus.DEVELOPING,
    FeatureStatus.REVIEWING,
    FeatureStatus.DONE,
]
```

`dev_revision` maps to `DEVELOPING` position for list-population. `DONE` is in the constant for completeness; `_options_for()` never returns a row for it.

### `HistoryEvent` — `details` JSON payload for `manual_state_change`

Encoded as a JSON-serialized string in the existing `HistoryEvent.details` field:

```json
{
  "from": "developing",
  "to": "planning",
  "mode": "rollback",
  "tasks_cleared": true,
  "actor": "tui"
}
```

Field types:

| Field | Type | Description |
|-------|------|-------------|
| `from` | `str` | `FeatureStatus.value` of state before mutation |
| `to` | `str` | `FeatureStatus.value` of state after mutation |
| `mode` | `"restart" \| "rollback" \| "fail"` | Operator intent |
| `tasks_cleared` | `bool` | Whether `with_tasks_cleared()` was applied |
| `actor` | `"tui"` | Constant; reserved for future non-TUI callers |

The event is written with `with_event("manual_state_change", details=json.dumps(payload))`, keeping the event name in `HistoryEvent.event` and the structured payload in `HistoryEvent.details`.

### `TaskMessage` shape for requeue (existing schema, no changes)

`build_phase_task(persisted_state, target_status, config) → TaskMessage` is called with the **post-commit** `FeatureState` snapshot so that task entry references reflect the committed state. The `TaskMessage` schema is unchanged.