# Feature Brief: Optional Git Worktree Isolation per Feature

## Problem Statement
Parallel developer tasks within a single feature pipeline share the same working directory, creating race conditions where concurrent agents overwrite each other's file changes. This causes non-deterministic failures and corrupted implementations.

## Goals
- Allow each feature pipeline to run in an isolated git worktree
- Make worktree usage opt-in via `config.json` so existing setups are unaffected

## Functional Requirements
- Add a `use_worktrees` boolean flag to `.pipeline/config.json` (default: `false`)
- When `use_worktrees: true`, create a new git worktree for each feature at pipeline start
- Worktree path: e.g. `.worktrees/{feature_id}/`
- All agent subprocesses for that feature run with the worktree as their working directory
- On successful pipeline completion (`done` state), automatically delete the worktree
- On failure, leave the worktree in place for manual inspection and debugging

## Non-Functional Requirements
- Worktree creation must not block the worker loop
- Worktree path must be stored in `state.json` so all workers can resolve it
- Must be safe when `use_worktrees: false` — no behaviour change in that mode

## Technical Constraints
- Uses `git worktree add` / `git worktree remove` via subprocess
- Worktree path stored as `worktree_path` field on `FeatureState` in `models.py`
- Worker reads `use_worktrees` from config at startup
- Agent subprocesses already launched via `agent_runner.py` — CWD override goes there

## Out of Scope
- Per-task worktrees (feature-level only)
- Merging worktree changes back into main branch (user's responsibility)
- UI for worktree management

## Success Criteria
- With `use_worktrees: true`, parallel developer tasks write to isolated directories with no cross-task conflicts
- Worktree is removed automatically when feature reaches `done`
- Worktree persists on `failed` state for inspection
- Existing pipelines with `use_worktrees: false` (or omitted) behave identically to today

## Additional Context
The `worker.py` creates tasks and launches agents; `dispatcher.py` drives state transitions. The `state_manager.py` handles atomic `state.json` updates via Azure blob lease — `worktree_path` should be set once at feature creation and never mutated after.
