# Design: TUI Feature State Change Dialog

## UX/UI Design

### Screen Layout

```
┌─────────────────────────────────────────────────────────────┐
│            Change State: feat-20260425-abc123               │
│            Current state: developing                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│   brainstorming          (rollback)                        │
│   brainstormed           (rollback)                        │
│   analyzing              (rollback)                        │
│   architecting           (rollback)                        │
│   designing              (rollback)                        │
│   planning               (rollback)                        │
│ ▶ developing             (current — restart)               │
│                                                             │
│   ──────────────────────────────────────────               │
│   failed                 (mark failed)                     │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│   ↑/↓ navigate   Enter confirm   Esc cancel                │
└─────────────────────────────────────────────────────────────┘
```

### Confirmation Dialog (fail mode only)

```
┌──────────────────────────────────────────────┐
│  Mark feat-20260425-abc123 as failed?        │
│                                              │
│  This cannot be undone automatically.        │
│                                              │
│           [Cancel]   [Confirm]               │
└──────────────────────────────────────────────┘
```

Uses the existing `ConfirmScreen(ModalScreen[bool])` at `tui.py:403`.

### State Row Rendering Rules

| Row type | Label suffix | Row enabled |
|----------|-------------|-------------|
| Earlier state | `(rollback)` | yes |
| Current state | `(current — restart)` | yes |
| Separator | — | no (non-selectable) |
| `failed` | `(mark failed)` | yes |

States shown: all `FeatureStatus` enum values from `brainstorming` up to and including the feature's current state index, then separator, then `failed`. States `done` and forward of current are excluded.

### Key Interactions

- `S` in main screen → open `StateChangeModal` (no-op if no selected feature; notify if feature is `done`)
- `↑`/`↓` → move cursor within `ListView`
- `Enter` → confirm selected row:
  - `restart`/`rollback` modes: dismiss modal immediately → call `apply_state_change` → show toast
  - `fail` mode: push `ConfirmScreen` → on `True` dismiss modal → call `apply_state_change` → show toast
- `Esc` → dismiss modal with `None`, no side effects
- On backend error: show `notify()` with error message, leave modal open for retry

### Toast Messages

| Outcome | Message |
|---------|---------|
| restart | `State changed: developing → developing (restart)` |
| rollback | `State changed: reviewing → planning (rollback)` |
| fail | `State changed: developing → failed` |
| enqueue failure | `State updated but re-queue failed — press S to retry` |
| done guard | `State change unavailable for completed features` |

---

## Component Design

### `agentharness/state_change.py` (new)

Pure Python, no Textual imports. Independently testable.

**Responsibilities:**
- Owns `StateChangeResult` dataclass and `StateChangeMode` literal
- Owns `StateChangeError` exception (raised when state updated but enqueue failed after one retry)
- Implements `apply_state_change()` — the sole entry point for all state mutation

**Interface:**

```python
StateChangeMode = Literal["restart", "rollback", "fail"]

@dataclass(frozen=True)
class StateChangeResult:
    target_status: FeatureStatus
    mode: StateChangeMode

class StateChangeError(Exception):
    persisted_status: FeatureStatus  # state was saved; enqueue failed

async def apply_state_change(
    feature_id: str,
    result: StateChangeResult,
    *,
    state_mgr: StateBackend,
    queue_factory: Callable[[str], TaskQueue],
    config: Config,
) -> None: ...
```

**Internal logic:**

```
state_mgr.update(feature_id, mutator)
  ├── fail:     s.with_status(failed).with_event(...)
  ├── restart:  s.with_event(...)                          # status unchanged
  └── rollback: s.with_status(target)
                  [.with_tasks_cleared() if target in CLEAR_TASKS_STATES]
                  .with_event(...)

→ queue_for_state(persisted.status)
  ├── None  → skip enqueue (failed / brainstorming / brainstormed / done)
  └── name  → build_phase_task(persisted, persisted.status, config)
                → queue_factory(name).send_task(task)
                  [on failure: sleep 1s, retry once, then raise StateChangeError]
```

`CLEAR_TASKS_STATES = {brainstorming, brainstormed, analyzing, architecting, designing, planning}`

The update closure always rebuilds from the fresh snapshot `s`; never captures outer mutable variables, preventing duplicate events on lease-contention retries.

---

### `agentharness/tui_state_change.py` (new)

Textual UI only. No direct storage I/O.

**Responsibilities:**
- Renders the `StateChangeModal` with state option rows
- Computes the options list from the passed `FeatureState` (pure, no I/O)
- Dismisses with `StateChangeResult | None`

**Interface:**

```python
class StateChangeModal(ModalScreen[StateChangeResult | None]):
    BINDINGS = [
        ("escape", "dismiss(None)", "Cancel"),
        ("enter",  "confirm",       "Confirm"),
    ]

    def __init__(self, feature_state: FeatureState) -> None: ...
    def compose(self) -> ComposeResult: ...
    def action_confirm(self) -> None: ...

    @staticmethod
    def _options_for(
        state: FeatureState,
    ) -> list[tuple[FeatureStatus, StateChangeMode, str]]:
        """Returns [(status, mode, label)] for all selectable rows."""
```

`compose()` must not perform I/O (NFR-1: < 100ms open time). All data comes from the `FeatureState` passed in `__init__`.

---

### `agentharness/dispatcher.py` (modified)

**Additions:**

```python
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
    """Constructs a phase-restart TaskMessage, reusing existing artifact/output helpers."""
```

**Removals/refactors:** The local `_PHASE_TO_QUEUE` dict in `tui.py` (line 54) and the inline copy inside `_resume_phase` are replaced with imports of `STATE_TO_QUEUE` / `queue_for_state`.

---

### `agentharness/models.py` (modified)

**Addition:**

```python
def with_tasks_cleared(self) -> FeatureState:
    return self.model_copy(update={"tasks": [], "updated_at": datetime.now(UTC)})
```

Note: `with_tasks_added([])` appends an empty list and does NOT clear. The new helper is required.

---

### `agentharness/tui.py` (modified — minimal)

**Additions only:**
- One new `Binding`: `("s", "open_state_change", "Change state")`
- One new action (~15 lines):

```python
async def action_open_state_change(self) -> None:
    feature_state = self._get_selected_feature_state()
    if feature_state is None:
        return
    if feature_state.status == FeatureStatus.done:
        self.notify("State change unavailable for completed features")
        return
    result = await self.push_screen_wait(StateChangeModal(feature_state))
    if result is None:
        return
    try:
        await apply_state_change(
            feature_state.feature_id, result,
            state_mgr=self._state_mgr,
            queue_factory=lambda name: create_task_queue(self._config, name),
            config=self._config,
        )
        self.notify(f"State changed: {feature_state.status} → {result.target_status}")
    except StateChangeError as e:
        self.notify(f"State updated but re-queue failed — press S to retry: {e}", severity="error")
```

---

### `agentharness/run_task.py` (modified)

**Addition at top of `run_task()`:**

```python
# Guard: task may have been cleared by a manual rollback
if task_msg.task_id and not any(t.task_id == task_msg.task_id for t in state.tasks):
    await state_mgr.update(feature_id, lambda s: s.with_event(
        "dropped_orphan_task", details=f'{{"task_id": "{task_msg.task_id}"}}'
    ))
    return
```

Applied only when the message carries a `task_id` (developer/review tasks). Phase-level messages (analyst, architect, etc.) do not have a `task_id` and skip this guard.

---

### Canonical State Order (for modal list construction)

```python
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
# done is excluded from the list (terminal, not selectable as rollback target)
# failed is always appended as a separate row after a separator
```

The modal computes `idx = CANONICAL_STATE_ORDER.index(current_status)` and shows `CANONICAL_STATE_ORDER[:idx+1]`, then `failed`.

---

## Data Schemas

### `StateChangeResult` (new dataclass)

```python
@dataclass(frozen=True)
class StateChangeResult:
    target_status: FeatureStatus
    mode: StateChangeMode          # "restart" | "rollback" | "fail"
```

### `StateChangeError` (new exception)

```python
class StateChangeError(Exception):
    def __init__(self, message: str, persisted_status: FeatureStatus) -> None:
        super().__init__(message)
        self.persisted_status = persisted_status
```

### History event payload (conforms to existing `HistoryEvent` schema)

```python
state.with_event(
    event="manual_state_change",
    details=json.dumps({
        "from":          str(previous_status),
        "to":            str(target_status),
        "mode":          mode,           # "restart" | "rollback" | "fail"
        "tasks_cleared": bool,
        "actor":         "tui",
    })
)
```

No schema changes to `state.json` or GitHub issue body format. `details` is an existing `str | None` field on `HistoryEvent`.

### `TaskMessage` construction (no new shape)

`build_phase_task(state, target_status, config)` returns the existing `TaskMessage` type. For phase agents (`analyst`, `architect`, `designer`, `planner`, `reviewer`) the message contains `feature_id` and phase artifact references, reusing the existing `_artifacts_for_phase` / `_output_name` helpers from `dispatcher.py`. For developer queue requeue (`developing`, `dev_revision`), the message references the most recent `in_progress` task entry's `queued_message`; if none is `in_progress`, the next `pending` task is used.

### `STATE_TO_QUEUE` mapping (authoritative)

| `FeatureStatus` | Queue name |
|-----------------|-----------|
| `brainstorming` | `None` |
| `brainstormed` | `None` |
| `analyzing` | `analyst-queue` |
| `architecting` | `architect-queue` |
| `designing` | `designer-queue` |
| `planning` | `planner-queue` |
| `developing` | `developer-queue` |
| `dev_revision` | `developer-queue` |
| `reviewing` | `review-queue` |
| `done` | `None` |
| `failed` | `None` |

This dict lives in `dispatcher.py` as `STATE_TO_QUEUE`. All former in-file copies (`tui._PHASE_TO_QUEUE`, `_resume_phase` inline dict) are replaced with an import of this constant.