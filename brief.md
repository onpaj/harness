# Feature Brief: TUI Feature State Change Dialog

## Problem Statement
Operators monitoring the AgentHarness TUI have no way to manually change a feature's state — for example, to roll back a stuck or failed feature to an earlier phase and restart it. Currently they must manipulate state storage directly, which is error-prone and requires deep system knowledge.

## Goals
- Allow any feature's state to be rolled back (or restarted) from within the TUI with a single keyboard shortcut
- Auto-requeue the feature to the appropriate pipeline queue after the state change, requiring no further manual steps

## Functional Requirements
- Pressing `S` in the TUI opens a modal dialog for the currently selected feature
- The dialog lists all states from `brainstorming` up to and including the feature's current state, plus `failed` at the bottom
- Selecting the **current state** restarts it: re-enqueues the same phase queue
- Selecting an **earlier state** rolls back: updates state, clears developer TaskEntry records if the target is `planning` or earlier, then re-enqueues the appropriate phase queue
- Selecting **`failed`** marks the feature as failed with no requeue
- State update is atomic via `state_mgr.update()` with an event logged (`"manual_state_change"`)
- On successful change the TUI refreshes immediately to reflect the new state

## State → Queue Mapping (for auto-requeue)
| State | Queue |
|-------|-------|
| `analyzing` | `analyst-queue` |
| `architecting` | `architect-queue` |
| `designing` | `designer-queue` |
| `planning` | `planner-queue` |
| `developing` | `developer-queue` |
| `reviewing` | `review-queue` |
| `dev_revision` | `developer-queue` |
| `brainstorming` / `brainstormed` | no requeue |

## Non-Functional Requirements
- State update must be atomic (blob lease / GitHub optimistic locking — same guarantees as existing `state_mgr.update()`)
- Dialog must not block the TUI refresh loop
- Rollback of TaskEntry records must not leave orphaned queue messages

## Technical Constraints
- TUI is built with the Textual framework (async-first); use `ModalScreen` for the dialog
- State management: `StateManager.update()` with immutable `FeatureState.with_status()` / `with_tasks_added([])` patterns
- Queue enqueue: construct `TaskMessage` and push via existing `TaskQueue` protocol
- Must work with both Azure and GitHub storage backends
- Shortcut `S` is currently unbound in the TUI

## Out of Scope
- Forward state jumps (only rollback to earlier states or restart current)
- Bulk state changes across multiple features
- Editing individual task entries from the TUI
- Changing state of `done` features

## Success Criteria
- `S` opens the modal on a selected feature; Escape closes it without changes
- Rolling back from `developing` to `planning` clears all TaskEntry records and re-enqueues planner-queue
- Restarting the current state re-enqueues the correct queue and the observer picks it up within one poll cycle
- Marking as `failed` sets state correctly with no queue message created
- Unit tests cover: state transition logic, task clearing, queue selection, `failed` path
