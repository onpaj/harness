# Specification: TUI Feature State Change Dialog

## Summary
Add an interactive modal dialog to the AgentHarness TUI that allows operators to manually roll back, restart, or fail a feature's state via the `S` keyboard shortcut. The dialog automatically updates feature state atomically and re-enqueues the feature to the correct pipeline queue, eliminating the need for direct storage manipulation.

## Background
Operators currently have no in-TUI mechanism for recovering stuck or failed features. The only recourse is manual blob/issue editing — which requires direct knowledge of the state schema, atomicity primitives (blob leases, GitHub label semantics), and queue message formats. This is error-prone and inaccessible to operators without deep system knowledge.

This feature provides a safe, atomic, UI-driven way to:
- Restart a stuck phase (e.g., re-run a hung analyst)
- Roll back to an earlier phase (e.g., re-plan after a bad task split)
- Manually mark a feature as `failed` (e.g., when an unrecoverable error is detected)

The change is constrained to backward state transitions only — no forward skipping — to preserve the linear pipeline invariant that each phase's outputs are produced by its agent.

## Functional Requirements

### FR-1: Keybinding to Open Dialog
Pressing the `S` key in the TUI while a feature is selected in the feature list opens a modal dialog scoped to that feature. If no feature is selected, the keypress is a no-op (or shows a transient hint).

**Acceptance criteria:**
- `S` is registered as a Textual `Binding` on the main TUI screen
- Pressing `S` with a selected feature pushes a `StateChangeModal` screen
- Pressing `S` with no selected feature does not open the modal and does not crash
- The shortcut is documented in the TUI footer/help

### FR-2: Modal Dialog Layout
The dialog is a `ModalScreen` that displays:
- The selected feature's ID and current state at the top
- A vertically scrollable list of selectable state options
- The list contains all canonical states from `brainstorming` up to and including the feature's current state, plus a final `failed` row
- Visual marker (highlight or label) on the row matching the current state, indicating "(current — restart)"
- Keyboard navigation: arrow keys to move, Enter to confirm, Escape to cancel

**Acceptance criteria:**
- Dialog renders without blocking the TUI's 2-second auto-refresh loop
- Escape closes the modal with no side effects
- The list ordering matches the canonical state order: `brainstorming`, `brainstormed`, `analyzing`, `architecting`, `designing`, `planning`, `developing`, `dev_revision`, `reviewing`, `done`, then `failed`
- Only states ≤ the current state index are shown (excluding `done`); `failed` is always appended
- The modal centers on the screen with appropriate padding and a clear title

### FR-3: Restart Current State
Selecting the row matching the feature's current state re-enqueues the feature to that phase's queue without changing the state value. An event is logged with reason `"manual_state_change"` and metadata `{from: <state>, to: <state>, mode: "restart"}`.

**Acceptance criteria:**
- A `TaskMessage` for the feature is enqueued onto the queue mapped from the current state (see State → Queue mapping)
- The state value remains unchanged
- An event is appended to `state.events` via `state_mgr.update()`
- The TUI refreshes to show the updated state/event log within one refresh cycle

### FR-4: Roll Back to Earlier State
Selecting an earlier state transitions the feature backward:
1. The feature's status is updated to the selected state via `FeatureState.with_status()`
2. If the target state is `planning` or earlier (i.e., `planning`, `designing`, `architecting`, `analyzing`, `brainstormed`, `brainstorming`), all developer task entries (`state.tasks`) are cleared
3. A `TaskMessage` is enqueued onto the phase's queue (per State → Queue mapping); states with no queue mapping (`brainstorming`, `brainstormed`) skip the requeue step
4. An event is logged with reason `"manual_state_change"` and metadata `{from: <old>, to: <new>, mode: "rollback", tasks_cleared: <bool>}`

**Acceptance criteria:**
- Rolling back from `developing` to `planning` results in `state.tasks == []` and a message on `planner-queue`
- Rolling back from `reviewing` to `developing` does NOT clear tasks (target is later than `planning`); enqueues `developer-queue` for the next pending task or current developer task
- All updates happen inside a single `state_mgr.update()` call (atomic via lease/optimistic locking)
- No orphaned queue messages remain pointing to cleared task IDs (see FR-7)

### FR-5: Mark as Failed
Selecting the `failed` row sets the feature's state to `failed` with no requeue.

**Acceptance criteria:**
- State is updated to `failed` via `state_mgr.update()`
- No `TaskMessage` is created or enqueued
- Event logged with reason `"manual_state_change"` and metadata `{from: <state>, to: "failed", mode: "fail"}`
- The feature appears as `failed` in the TUI on next refresh

### FR-6: Atomic State Update
All state mutations use `state_mgr.update()` to guarantee atomicity across both Azure (blob lease) and GitHub (issue optimistic-locking) backends.

**Acceptance criteria:**
- A single `state_mgr.update()` call performs status change, task clearing (when applicable), and event append
- Concurrent updates from another writer either succeed in serial or surface a clear error to the user
- The update closure is idempotent enough that retries on lease contention do not duplicate events (the closure rebuilds the new state from the latest snapshot each retry)

### FR-7: Queue Message Hygiene
Rollback that clears tasks must not leave orphaned queue messages from prior developer/review tasks pointing to now-removed `TaskEntry` records.

**Acceptance criteria:**
- After rollback, any in-flight developer or review queue messages whose `task_id` is no longer in `state.tasks` are treated as no-ops by the observer/run_task path
- If feasible, document existing observer behavior that already handles missing tasks gracefully; otherwise add a defensive check in `run_task.py` that drops messages whose `task_id` does not match any current `TaskEntry`
- Note in Open Questions if a sweep of queue messages is needed (Azure queues do not support targeted message deletion without pop receipts)

### FR-8: Error Handling and User Feedback
The dialog surfaces errors clearly without crashing the TUI.

**Acceptance criteria:**
- Backend errors (lease contention, network) display a notification within the modal or via Textual `notify()` and leave the modal open for retry
- A successful change closes the modal and shows a confirmation toast (`State changed: {from} → {to}`)
- Cancellation via Escape produces no notification and no side effects

### FR-9: Disallowed Transitions
The dialog refuses to act on features in disallowed states.

**Acceptance criteria:**
- Features with state `done` either do not show the dialog at all on `S` press (with a notification "State change unavailable for completed features") or show a disabled/empty list
- Forward jumps are impossible by construction because the list is bounded by the current state index

## Non-Functional Requirements

### NFR-1: Performance
- The modal opens within 100 ms of the keypress (it does not perform I/O on open — it reads the already-cached `FeatureState`)
- State change confirmation completes within 2 seconds under normal latency (one `state_mgr.update()` + one queue enqueue)
- The TUI's auto-refresh loop continues running while the modal is open; the modal must not hold blocking calls on the event loop

### NFR-2: Security
- No new auth surface; the dialog inherits the operator's existing access to the storage backend
- No secrets or tokens are exposed via the dialog UI
- Manual state changes are auditable via the appended event log entry, including the `"manual_state_change"` reason and `from`/`to`/`mode` metadata

### NFR-3: Reliability
- Atomicity guarantees match `state_mgr.update()`: blob lease (Azure) or optimistic locking via issue label/body update (GitHub)
- The operation is safe to retry; a partial failure (state updated but enqueue failed) must be either fully recovered or surfaced for manual retry — see Open Questions

### NFR-4: Usability
- Keyboard-only operation (no mouse required)
- Dialog labels are unambiguous: each row shows the state name and a hint (`(current — restart)`, `(rollback)`, `(mark failed)`)
- Footer in the modal lists keys: ↑/↓ navigate, Enter confirm, Esc cancel

## Data Model

No schema changes. Existing entities and the new event payload:

### `FeatureState` (existing — `agentharness/models.py`)
- `status: FeatureStatus` — mutated via `with_status(new_status)`
- `tasks: list[TaskEntry]` — cleared via `with_tasks_added([])` or a new `with_tasks_cleared()` helper if cleaner (immutable copy with `tasks=[]`)
- `events: list[FeatureEvent]` — appended via `with_event_added(event)`

### New event entry (existing `FeatureEvent` shape)
```json
{
  "timestamp": "<iso8601>",
  "reason": "manual_state_change",
  "metadata": {
    "from": "<previous_status>",
    "to": "<new_status>",
    "mode": "restart" | "rollback" | "fail",
    "tasks_cleared": true | false,
    "actor": "tui"
  }
}
```

If `FeatureState` does not already expose a `with_tasks_cleared()` helper, add one (immutable: returns a copy with `tasks=[]`). Confirm whether `with_tasks_added([])` already produces this behavior — if so, reuse; otherwise add the helper.

### State → Queue mapping (constant)
A single source-of-truth dict in `agentharness/dispatcher.py` (or a new `agentharness/state_queue_map.py` if it does not already exist as a constant):

```python
STATE_TO_QUEUE = {
    "analyzing": "analyst-queue",
    "architecting": "architect-queue",
    "designing": "designer-queue",
    "planning": "planner-queue",
    "developing": "developer-queue",
    "reviewing": "review-queue",
    "dev_revision": "developer-queue",
    "brainstorming": None,
    "brainstormed": None,
}
```

The dialog imports this mapping; if a similar constant exists in `dispatcher.py`, reuse it rather than duplicating.

## API / Interface Design

### New Textual modal: `StateChangeModal`
Location: `agentharness/tui.py` (or a new `agentharness/tui_modals.py` if `tui.py` exceeds the 800-line limit after the addition).

```python
class StateChangeModal(ModalScreen[StateChangeResult | None]):
    BINDINGS = [
        ("escape", "dismiss(None)", "Cancel"),
        ("up", "cursor_up", "Up"),
        ("down", "cursor_down", "Down"),
        ("enter", "confirm", "Confirm"),
    ]

    def __init__(self, feature_state: FeatureState): ...
    def compose(self) -> ComposeResult: ...  # ListView of state options
    def action_confirm(self) -> None: ...   # dismiss with selected target
```

`StateChangeResult` is a small dataclass `{target_status: str, mode: Literal["restart","rollback","fail"]}`.

### Main TUI screen changes
- Add binding `("s", "open_state_change", "Change state")`
- Action handler `action_open_state_change()`:
  1. Get currently selected feature's `FeatureState`
  2. If state is `done`, show notification and return
  3. Push `StateChangeModal(feature_state)` and `await self.push_screen_wait(...)`
  4. On result, call `apply_state_change(feature_id, result)`

### New service function: `apply_state_change`
Location: `agentharness/tui.py` or a new `agentharness/state_change.py` (preferred — keeps tui.py focused on UI).

```python
async def apply_state_change(
    feature_id: str,
    target_status: str,
    mode: Literal["restart", "rollback", "fail"],
    *,
    state_mgr: StateBackend,
    queue_factory: Callable[[str], TaskQueue],
) -> None:
    """Atomically transition a feature's state and re-enqueue if applicable."""
```

Logic:
1. Inside `state_mgr.update(feature_id, mutator)`:
   - If `mode == "fail"`: set status to `failed`, append event
   - Elif `mode == "restart"`: keep status, append event
   - Elif `mode == "rollback"`: set status to target, clear tasks if target is in `{brainstorming, brainstormed, analyzing, architecting, designing, planning}`, append event
2. After the update commits, if the resulting status is in `STATE_TO_QUEUE` and maps to a non-`None` queue, construct a `TaskMessage` and enqueue it on the mapped queue. (Skip enqueue for `failed` and `brainstorming`/`brainstormed`.)
3. Surface errors to the caller for UI display.

### TaskMessage construction
For each requeue scenario, the function constructs a `TaskMessage` matching the agent's expected payload. For developer queue requeue (e.g., rollback to `developing` from `dev_revision`/`reviewing`), the message references the next pending or in-progress task entry. For phase agents (analyst/architect/designer/planner/reviewer), the message contains the feature ID and any phase-specific fields. Existing `dispatcher.py` task-message construction helpers should be reused; if they are not exposed, refactor minimally to expose them.

## Dependencies
- **Existing infrastructure** (no new external dependencies):
  - `Textual` — `ModalScreen`, `ListView`, `Binding`
  - `agentharness.state_manager.StateManager.update()` for atomicity
  - `agentharness.storage.create_task_queue()` for backend-agnostic enqueue
  - `agentharness.models.FeatureState` and immutable mutation helpers
  - `agentharness.dispatcher` for `TaskMessage` construction (reuse existing helpers)
- **Internal dependencies:**
  - The state→queue mapping must align with `dispatcher._LINEAR_TRANSITIONS` and `.pipeline/config.json` queue names
- **No new packages** required

## Out of Scope
- Forward state jumps (e.g., from `planning` to `developing` without running the developer)
- Bulk state changes across multiple features in one action
- Editing individual `TaskEntry` records (status, content, retry count) from the TUI
- Changing the state of `done` features (treated as terminal)
- Cancelling or deleting in-flight queue messages by message ID — the design relies on observer/run_task being defensive about missing `TaskEntry` records (see FR-7)
- A web UI for the same operation
- Audit log export or filtering by `manual_state_change` events
- Undo/redo of manual state changes (an undo would itself be a new manual change)

## Open Questions

1. **Does `FeatureState` already have a `with_tasks_cleared()` helper, or should it be added?** The brief says "use `with_tasks_added([])`" — confirm this produces an empty task list (it likely *appends* an empty list). If so, add a dedicated `with_tasks_cleared()` for clarity. _Assumption: add a small new helper._

2. **Orphaned queue messages after rollback (FR-7).** When rolling back from `developing` to `planning`, the developer queue may already contain messages for tasks that are about to be cleared. We cannot delete them by ID in either backend without the receipt. Two options:
   - Rely on `run_task.py` to detect "task not found in state" and silently drop
   - Add a `dropped_orphan_task` event for observability
   _Assumption: option (b) — drop with an event. Confirm with team._

3. **Atomicity boundary.** The state update and the queue enqueue cannot be done in a single transaction across two systems. If state update succeeds but enqueue fails, the feature is left in the new state with no work scheduled. Should we:
   - Retry enqueue on failure with a small backoff
   - Surface error and require operator to retry from the dialog
   - Add a periodic reconciliation pass in the observer that detects "feature in active state with no queue message"
   _Assumption: retry once, then surface error to operator. The observer's existing stale-claim sweep partially mitigates this._

4. **Restart of `dev_revision`.** When restarting `dev_revision`, which task should be re-enqueued — the most recent task with status `in_progress`, or all `pending`? _Assumption: re-enqueue the single in-progress developer task; pending tasks remain queued for serial dispatch._

5. **Restart of `reviewing`.** When restarting `reviewing`, which task does the reviewer process? _Assumption: the most recent `in_progress` developer task (i.e., the one awaiting review)._

6. **Rolling back from `done`.** The brief excludes `done` from the dialog. Confirm we never want to allow a "redo" from `done` — even with a manual override. _Assumption: hard exclude, per brief._

7. **Confirmation step.** Should destructive actions (clearing tasks, marking failed) require a second confirmation keypress (e.g., "Y" to confirm)? _Assumption: no — the modal selection itself is an explicit, deliberate action; Escape provides cancellation._

8. **`brainstormed` state.** The mapping says `brainstormed` has no queue. Is `brainstormed` actually a valid status in the current `FeatureStatus` enum, or only `brainstorming`? _Assumption: use only states that exist in the enum; if `brainstormed` is not present, omit it._