# Specification: TUI Feature State Change Dialog

## Summary
Add a modal dialog to the AgentHarness TUI (triggered by pressing `S`) that lets operators roll back, restart, or fail any in-flight feature without manipulating storage directly. The dialog atomically updates feature state via the existing `StateManager.update()` contract and auto-requeues the appropriate pipeline queue, restoring the feature to a runnable condition in one keystroke.

## Background
AgentHarness features progress through a linear state machine (`brainstorming → analyzing → architecting → designing → planning → developing → reviewing → done`) with `dev_revision` and `failed` as branches. When a feature stalls — observer crash, agent infinite-loop, malformed artifact, or a bug surfaced by review — operators currently must:
1. Edit `state.json` (Azure backend) or the issue body and labels (GitHub backend) by hand.
2. Manually push a `TaskMessage` onto the correct queue.
3. Reason about which TaskEntry records to clear so the planner can re-fan-out cleanly.

Each step is fragile: a malformed JSON edit corrupts state, a missed queue message strands the feature, and orphaned TaskEntry rows confuse the dispatcher's serial-dispatch and review-loop logic. This feature exposes a safe, auditable, atomic operation through the TUI that operators already use for monitoring, eliminating the need for backend-specific knowledge during recovery.

## Functional Requirements

### FR-1: Keyboard Shortcut to Open Dialog
Pressing `S` while a feature row is highlighted in the TUI feature list opens the State Change modal dialog scoped to that feature. The shortcut is registered as a Textual `BINDING` on the main screen and is shown in the footer.

**Acceptance criteria:**
- Pressing `S` with no feature selected is a no-op (dialog does not open).
- Pressing `S` with a `done` feature selected is a no-op (dialog does not open; out of scope per brief).
- Pressing `S` with any non-`done` feature selected opens a `ModalScreen` showing the feature ID and current state in the title.
- The shortcut binding does not conflict with existing TUI bindings (`S` is currently unbound — verified during implementation).
- The footer displays "S — Change state" when a non-`done` feature is selected.

### FR-2: Dialog Renders Selectable State List
The dialog presents the user with a vertical list of states they can transition the feature to. The list contains every state from `brainstorming` up to and including the feature's current state, followed by `failed` at the bottom. The current state is visually marked (e.g., `(current — restart)` suffix).

**Acceptance criteria:**
- For a feature in `developing`, the list shows: `brainstorming`, `analyzing`, `architecting`, `designing`, `planning`, `developing (current — restart)`, `failed`.
- For a feature in `analyzing`, the list shows: `brainstorming`, `analyzing (current — restart)`, `failed`.
- `dev_revision` is treated as equivalent to `developing` for list-population purposes (i.e., a `dev_revision` feature shows the same options as a `developing` feature, with `developing` marked current).
- States *after* the feature's current state are never shown (no forward jumps).
- Arrow keys (`Up`/`Down`) navigate the list; `Enter` confirms; `Escape` cancels and closes the dialog with no state change.
- The currently-selected list item is visually highlighted via Textual's standard `ListView` focus styling.

### FR-3: Restart Current State
Selecting the feature's current state in the dialog re-enqueues the same phase queue without changing state values, after the dispatcher acknowledges the request via a logged event.

**Acceptance criteria:**
- State remains unchanged (`status` field of `FeatureState` is the same value before and after).
- A `TaskMessage` is pushed to the queue corresponding to the current state per the State→Queue mapping table (FR-7).
- An event with `kind: "manual_state_change"`, `from: <state>`, `to: <state>`, `action: "restart"` is appended to `FeatureState.events`.
- TaskEntry records are *not* cleared on restart.
- For `developing`, `reviewing`, or `dev_revision`, restart re-enqueues using the existing first incomplete TaskEntry (re-runs the in-flight task).
- If the current state is `brainstorming` or `brainstormed`, the dialog does not offer "restart" (no queue exists for these states); selecting them is a no-op with a status message "No queue available for brainstorming state".

### FR-4: Roll Back to Earlier State
Selecting any earlier state rolls the feature back: the state is updated, TaskEntry records are conditionally cleared, and the appropriate queue is re-enqueued.

**Acceptance criteria:**
- `FeatureState.status` is updated to the selected target state via `with_status(target)`.
- If the target state is `planning` or any earlier state (`brainstorming`, `analyzing`, `architecting`, `designing`), all TaskEntry records are cleared (`tasks` field is replaced with an empty list via `with_tasks_added([])` semantics — implementation must use a method that *replaces* tasks immutably; if no such method exists, add `with_tasks_replaced([])`).
- If the target state is `developing`, `reviewing`, or `dev_revision`, TaskEntry records are preserved (rollback within the developer/review loop does not destroy task plans).
- A `TaskMessage` is pushed to the queue corresponding to the target state per FR-7.
- An event with `kind: "manual_state_change"`, `from: <old_state>`, `to: <target_state>`, `action: "rollback"` is appended.
- Rolling back to `brainstorming` updates state but does not enqueue (no queue mapping); the feature must be re-implemented via `/implement` to resume.

### FR-5: Mark as Failed
Selecting `failed` marks the feature terminal-failed with no queue activity.

**Acceptance criteria:**
- `FeatureState.status` becomes `failed`.
- No `TaskMessage` is pushed to any queue.
- An event with `kind: "manual_state_change"`, `from: <old_state>`, `to: "failed"`, `action: "fail"` is appended.
- TaskEntry records are *not* cleared (operator may want to inspect them post-mortem).
- The feature is no longer eligible for state changes via this dialog (consistent with the `done` exclusion in FR-1, but `failed` features *can* still be rolled back to an earlier state — see Open Question OQ-1).

### FR-6: Atomic State Update with Event Logging
All state mutations performed by the dialog go through `StateManager.update()` to ensure atomicity across both backends. The state-change event is appended to `FeatureState.events` in the same atomic transaction as the status mutation.

**Acceptance criteria:**
- A single `state_mgr.update(feature_id, mutator)` call performs status update, optional task clearing, and event append in one atomic operation.
- Azure backend: blob lease is acquired, mutation applied, lease released — no partial writes visible to other readers.
- GitHub backend: issue body update uses optimistic locking; on conflict, the operation retries per existing `state_mgr` semantics.
- If `state_mgr.update()` raises an exception, no queue message is enqueued (queue push happens *after* successful state commit).
- The event entry includes a UTC ISO-8601 timestamp.

### FR-7: Auto-Requeue with State→Queue Mapping
After a successful state change requiring requeue, the dialog constructs a `TaskMessage` for the feature and pushes it to the queue determined by this mapping:

| Target state | Queue name | Notes |
|--------------|------------|-------|
| `analyzing` | `analyst-queue` | |
| `architecting` | `architect-queue` | |
| `designing` | `designer-queue` | |
| `planning` | `planner-queue` | |
| `developing` | `developer-queue` | TaskMessage references next pending task |
| `reviewing` | `review-queue` | TaskMessage references task awaiting review |
| `dev_revision` | `developer-queue` | TaskMessage references task with revision flag |
| `brainstorming` / `brainstormed` | (none) | No requeue |
| `failed` | (none) | No requeue |

The mapping is implemented as a single source of truth shared with `dispatcher.py` (existing `STATE_TO_QUEUE` constant — see Open Question OQ-2 for whether to extract to a shared module).

**Acceptance criteria:**
- The mapping is not duplicated; it is imported from a single module used by both `dispatcher.py` and the new TUI dialog code.
- For `developing`/`dev_revision`/`reviewing` targets where TaskEntry records are preserved, the requeued `TaskMessage` references the *first non-completed* task entry (or, if all are completed, the last task — operator intent is "redo the last in-flight task").
- For `developing`/`reviewing`/`dev_revision` targets where TaskEntry records have been cleared (which only happens if the target is actually `planning` or earlier — see FR-4), the requeue path is unreachable; this combination is a logic error and must raise an assertion.
- Queue push uses the existing `TaskQueue` protocol obtained via `create_task_queue(config, queue_name)`.
- Queue push happens *after* the atomic state commit; if queue push fails, the state is already updated — an event with `kind: "manual_state_change_requeue_failed"` is appended (best-effort, separate `state_mgr.update()` call) and the TUI displays an error message.

### FR-8: TUI Refresh After State Change
On successful state change the TUI feature list refreshes immediately, reflecting the new state without waiting for the next poll cycle.

**Acceptance criteria:**
- After dialog confirmation, the feature row in the main TUI shows the new state within one render frame (≤100ms).
- The dialog closes automatically on success.
- On failure, the dialog stays open and displays an inline error message; user can retry or press Escape to close.

### FR-9: Cancellation and Idempotency
The user can cancel the dialog at any point before confirmation with no side effects.

**Acceptance criteria:**
- Pressing `Escape` closes the dialog and triggers no state mutation, no queue push, and no event log entry.
- Clicking outside the modal (if mouse support is enabled in Textual) closes the dialog without changes — same semantics as Escape.
- Re-opening the dialog after cancellation shows the *current* state (re-fetched fresh — does not cache stale state from prior open).

## Non-Functional Requirements

### NFR-1: Performance
- Dialog open latency: ≤200ms from keystroke to first paint, including state re-fetch.
- State commit + queue push: ≤2s p95 for both Azure and GitHub backends under nominal network conditions (≤500ms p95 for state commit, ≤1.5s for queue push on GitHub due to issue creation).
- TUI refresh after dialog confirms: ≤100ms.
- Dialog operations must not block the TUI's 2-second auto-refresh loop — all storage I/O runs in async tasks via `asyncio.create_task` or Textual's `worker` decorator.

### NFR-2: Security
- The dialog requires no additional auth beyond what the operator already has to run `agentharness watch` (the existing storage credentials are reused).
- No user input is interpreted as code or shell commands; the only inputs are list-item selection and keyboard navigation.
- Event log entries do not contain credentials, tokens, or any secret material — only state names, feature ID, action type, and UTC timestamp.
- The shortcut is documented in the TUI footer and help screen so it cannot be triggered accidentally without operator awareness.

### NFR-3: Reliability
- State mutation is atomic — partial state on backend failure is impossible (backend's atomic-update contract is honored).
- If queue push fails after state commit, the operation is *not* rolled back (state stays at target); instead, a warning event is logged and the operator is shown an error suggesting they re-trigger the dialog with "restart current state" to retry the queue push.
- TaskEntry clearing is performed in the same atomic update as status change — no intermediate state where status is `planning` but tasks still reference a `developing` workflow.
- The dialog is resilient to concurrent state changes: if `state_mgr.update()` reports a lease/optimistic-lock conflict, the user sees an error "State changed concurrently — please retry" and the dialog stays open with refreshed state.

### NFR-4: Maintainability
- The State→Queue mapping is a single constant (DRY) shared with `dispatcher.py`.
- TUI dialog code lives in a new file `agentharness/tui_dialogs.py` (or equivalent) — it does *not* bloat `tui.py`.
- All state-change logic is unit-testable without spinning up Textual; the dialog's "decide what to do" function is a pure function over `(current_state, target_state, current_tasks)` returning a structured action descriptor (`StateChangeAction`).
- Test coverage ≥80% for the new logic, including all six action paths (restart, rollback-clear-tasks, rollback-keep-tasks, fail, no-queue, queue-failure-after-commit).

## Data Model

### Existing entities (used, not modified)
- `FeatureState` (`agentharness/models.py`) — already exposes `status`, `tasks`, `events`, `with_status()`, `with_tasks_added()`. May need a new immutable helper `with_tasks_replaced(new_tasks)` if not already present (see Open Question OQ-3).
- `TaskMessage` — constructed for the requeue payload.
- `TaskEntry` — referenced when deciding whether to clear.

### New additions
- **`StateChangeAction`** (new dataclass in `tui_dialogs.py` or `dispatcher.py`):
  ```
  StateChangeAction:
    target_state: FeatureStatus
    clear_tasks: bool
    queue_name: str | None         # None for failed / brainstorming
    action_label: str              # "restart" | "rollback" | "fail"
    event_kind: str                # always "manual_state_change"
  ```
  Emitted by a pure function `decide_state_change(current_state, target_state, has_tasks) -> StateChangeAction`.

- **Event entry shape** (added to `FeatureState.events`):
  ```json
  {
    "kind": "manual_state_change",
    "from": "developing",
    "to": "planning",
    "action": "rollback",
    "tasks_cleared": true,
    "ts": "2026-04-28T14:32:01Z"
  }
  ```

### State→Queue constant
A module-level dict `STATE_TO_QUEUE` keyed by `FeatureStatus` enum, values are queue-name strings (or `None`). Lives in `agentharness/dispatcher.py` if already present there; otherwise extract to `agentharness/state_routing.py` and import from both `dispatcher.py` and `tui_dialogs.py`.

## API / Interface Design

### TUI binding
In the main TUI screen class:
```python
BINDINGS = [
    ...,
    Binding("s", "open_state_dialog", "Change state", show=True),
]

async def action_open_state_dialog(self) -> None:
    feature = self.selected_feature
    if feature is None or feature.status == FeatureStatus.DONE:
        return
    await self.push_screen(StateChangeDialog(feature.id), self.on_state_change_result)
```

### Modal dialog (`StateChangeDialog`)
- Subclasses Textual `ModalScreen[StateChangeResult | None]`.
- Composes a `Vertical` container with: title (`Label`), feature ID/current state (`Static`), state list (`ListView` of `ListItem`), footer hint (`Static`: "Enter to confirm — Escape to cancel").
- On mount, fetches `FeatureState` via `state_mgr.read(feature_id)` to ensure freshness.
- Builds list items from `_eligible_targets(current_state)` — pure function, easy to test.
- On `Enter`: calls `await self._apply_state_change(target)` which:
  1. Computes `StateChangeAction = decide_state_change(...)`.
  2. Calls `state_mgr.update(feature_id, mutator)` where `mutator` applies status, optionally clears tasks, appends event.
  3. If `action.queue_name`, builds `TaskMessage` and pushes via `task_queue.send(...)`.
  4. Dismisses with `StateChangeResult(success=True, new_state=target)`.

### Pure function (the testable core)
```python
def decide_state_change(
    current: FeatureStatus,
    target: FeatureStatus,
    has_developer_tasks: bool,
) -> StateChangeAction: ...

def eligible_targets(current: FeatureStatus) -> list[FeatureStatus]: ...
```

### State manager mutator (closure)
```python
def _build_mutator(action: StateChangeAction, from_state: FeatureStatus):
    def mutator(state: FeatureState) -> FeatureState:
        new = state.with_status(action.target_state)
        if action.clear_tasks:
            new = new.with_tasks_replaced([])
        return new.with_event_appended({
            "kind": "manual_state_change",
            "from": from_state.value,
            "to": action.target_state.value,
            "action": action.action_label,
            "tasks_cleared": action.clear_tasks,
            "ts": utcnow_iso(),
        })
    return mutator
```

### Queue push
```python
queue = create_task_queue(config, action.queue_name)
msg = TaskMessage(feature_id=feature_id, agent_id=<derived>, ...)
await queue.send(msg)
```
The `agent_id` and any task-specific fields are derived from the target state and (where relevant) the existing TaskEntry records — same logic the dispatcher uses for forward transitions, factored into a helper to avoid duplication.

## Dependencies

- **Textual** — already a TUI dependency; uses `ModalScreen`, `ListView`, `ListItem`, `Binding`. No version bump expected.
- **`agentharness.state_manager.StateManager`** — existing; uses `update()` and `read()`. No interface change.
- **`agentharness.storage.create_task_queue`** — existing factory.
- **`agentharness.models.FeatureState`** — may need `with_tasks_replaced(...)` and `with_event_appended(...)` helpers if not already present (verify during implementation; if absent, add them as immutable methods returning new instances).
- **`agentharness.dispatcher.STATE_TO_QUEUE`** — existing constant per recent commit `192bc11`; reuse rather than redefine.

## Out of Scope

- Forward state jumps (e.g., skipping `analyzing` to go straight to `planning`) — only rollback to earlier states or restart current.
- Bulk state changes across multiple features.
- Editing or deleting individual TaskEntry records from the TUI.
- Changing state of `done` features (intentionally excluded — operator can re-implement via `/implement` if needed).
- Undo of a manual state change via a "revert" command — operator can simply open the dialog again.
- Audit trail beyond the event log already maintained in `FeatureState.events`.
- Permission/role gating — the TUI does not currently distinguish roles; same operator who can run `agentharness watch` can change state.
- A confirmation prompt ("Are you sure?") before applying — Escape-to-cancel and the explicit list-selection step are deemed sufficient to prevent accidental triggers.

## Open Questions

### OQ-1: Can a `failed` feature be rolled back via this dialog?
The brief excludes `done` from the dialog but is silent on `failed`. Operationally, recovery from `failed` is the *primary* use case (a feature failed → operator wants to restart). **Assumption:** `failed` features *can* open the dialog; the eligible-targets list is computed from the *last non-failed* state in the event log if available, otherwise from the current `failed` value (which would offer just `failed` and `brainstorming` through whatever state preceded the failure). Confirm with stakeholder before implementation. If rejected, treat `failed` like `done` and exclude from the dialog.

### OQ-2: Where does `STATE_TO_QUEUE` live?
Per commit `192bc11`, the dispatcher recently centralized this. **Assumption:** import from `dispatcher.py` directly. If circular-import concerns arise (TUI → dispatcher → TUI), extract to a new `agentharness/state_routing.py` module with no further dependencies.

### OQ-3: Does `FeatureState` already expose immutable task-replacement and event-append helpers?
Brief mentions `with_status()` and `with_tasks_added([])`. **Assumption:** `with_tasks_replaced()` and `with_event_appended()` may not exist; if absent, add them following the existing immutable-helper pattern. No test impact since they are pure functions over an immutable model.

### OQ-4: For `dev_revision` / `developing` / `reviewing` requeue, which task does the `TaskMessage` reference?
The brief says "auto-requeue the appropriate pipeline queue" but doesn't specify which task entry. **Assumption:** the *first non-completed* TaskEntry (matching the dispatcher's serial-dispatch behavior); if all tasks are completed, requeue using the *last* task. If neither is sensible, fall back to enqueueing a "resume from current state" message that the dispatcher interprets idempotently.

### OQ-5: Should the dialog show task counts / preview the impact?
For UX, showing "selecting `planning` will clear 7 task entries" is helpful but adds complexity. **Assumption:** include this as a single status line under the list — low-cost, high-value transparency. If implementation pressure is high, defer to a follow-up.

### OQ-6: What feedback does the operator get on success?
**Assumption:** the dialog dismisses, the TUI refreshes, and a transient toast/footer message says "State changed: developing → planning (planner-queue)". Textual's `notify()` API supports this. If `notify()` is not desired, fall back to a status line in the main TUI.