# Specification: Raw GitHub Issue TUI Visibility + Auto-Conversion

## Summary
Make GitHub issues labeled with the configured `feature_marker` label appear in AgentHarness immediately as `brainstormed` features without manual conversion. When the user triggers implementation (via TUI `i` key or `agentharness implement`), silently convert the raw issue into a harness-managed feature and start the pipeline.

## Background
AgentHarness's GitHub backend uses GitHub Issues as both a feature registry and state store. The `GitHubStateManager.list_features()` method currently parses each issue's body for an `agentharness-state` JSON block and silently skips issues that lack one — even when they carry the `feature_marker` label. As a result, freshly labeled issues are invisible in the TUI until the user manually runs the `/convertforagent` skill, which embeds the state block.

This creates friction: the user has to remember the slash command, find the issue number, and run a command outside the TUI before the issue becomes actionable. The expected mental model is simpler: "label the issue, see it in the TUI, press `i` to start." This spec closes that gap by surfacing raw issues as synthetic features and folding the conversion step into the existing enqueue path so it becomes invisible to the user.

## Functional Requirements

### FR-1: Raw issues appear as synthetic `brainstormed` features
`GitHubStateManager.list_features()` must return a `FeatureState` entry for every open issue carrying the `feature_marker` label, including issues without an `agentharness-state` JSON block in their body.

For each such "raw" issue, build a synthetic `FeatureState`:
- `feature_id` = `feat-{slug(issue.title)}` using the same 40-character slug algorithm as `convertforagent`
- `status` = `FeatureStatus.brainstormed`
- `state_issue_number` = issue number
- `branch_name` = same as `feature_id`
- `created_at` / `updated_at` = corresponding issue timestamps
- `history`, `phases`, and `tasks` = empty (these distinguish raw from initialized features)

The existing deduplication rule (newest issue wins per `feature_id`) applies unchanged across both raw and initialized issues.

**Acceptance criteria:**
- An open issue with the `feature_marker` label and no `agentharness-state` block produces a `FeatureState` in `list_features()` output.
- The synthetic state has `status=brainstormed`, populated `state_issue_number`, populated `branch_name`, and empty `history`/`phases`/`tasks`.
- `feature_id` matches what `/convertforagent` would have produced for the same title.
- When two raw issues share a slug, only the newest is returned.
- When a raw and an initialized issue share a slug, the existing dedup rule still selects the newest.
- Raw issues render in the TUI as `◎  {short-id}  □□□□□  brainstormed` with no rendering errors from empty phases/tasks (existing `_phase_bar()` / `_task_summary()` handle empty inputs).

### FR-2: New `patch_existing_issue()` method on `GitHubStateManager`
Add a public async method that embeds harness state into an already-existing GitHub issue (analogous to `create()`, but it updates rather than creating).

```
async def patch_existing_issue(
    self,
    issue_number: int,
    state: FeatureState,
    brief_content: str = "",
) -> None
```

Behavior:
1. Ensure the `feat:brainstormed` label exists in the repository (create if missing).
2. Add the `feat:brainstormed` label to the target issue (the `feature_marker` label is already present and is left in place).
3. Build the new issue body by replacing any existing `agentharness-state` block, or appending one if absent. If `brief_content` is provided and the issue body does not already contain the brief, preserve/include it per existing body-construction conventions.
4. Call `self._client.update_issue(issue_number, body=new_body)`.

**Acceptance criteria:**
- Calling on an issue without any state block appends a valid `agentharness-state` block; subsequent `list_features()` returns the issue as initialized (non-empty `history` once written, populated `state_issue_number`, etc.).
- Calling on an issue that already has a state block replaces the block in place; the rest of the body is preserved.
- The `feat:brainstormed` label is present after the call, even if it did not exist in the repo before.
- The original `feature_marker` label is not removed.
- The method is idempotent: calling twice with the same `state` produces the same final body.

### FR-3: New `_convert_raw_issue()` helper in `brainstorm.py`
Add a private async function that performs the full equivalent of the `/convertforagent` skill in Python, without invoking any `gh` CLI subprocesses.

```
async def _convert_raw_issue(feature_id: str, config: Config) -> None
```

Behavior:
1. List open issues with the `feature_marker` label using the GitHub client.
2. Match the issue whose title-slug equals `feature_id`. If none match, raise `ValueError("no raw issue found for '{feature_id}'")`.
3. Build a `FeatureState(status=brainstormed, state_issue_number=<n>, branch_name=feature_id, ...)`.
4. Create the feature branch via the GitHub client, branched from the default branch SHA. If the branch already exists, skip creation without error.
5. Upload `artifacts/{feature_id}/brief.md` via `GitHubArtifactStore` using the issue body as the brief content.
6. Call `state_mgr.patch_existing_issue(issue_number, state, brief_content)`.

**Acceptance criteria:**
- After completion, `state_mgr.get(feature_id)` returns a non-`KeyError` result with `status=brainstormed` and a non-empty `branch_name`.
- The corresponding issue body contains an `agentharness-state` JSON block.
- The feature branch exists in the repo (created or pre-existing).
- `artifacts/{feature_id}/brief.md` exists in the feature branch.
- When no raw issue matches, the function raises `ValueError` with a message including the missing `feature_id`.
- When the feature branch already exists, no error is raised and conversion still completes.

### FR-4: `enqueue_planner()` auto-converts raw issues (GitHub backend only)
Modify `brainstorm.enqueue_planner()` so that, on the GitHub backend, it transparently performs raw-issue conversion when the feature does not yet have harness state.

```
async def enqueue_planner(feature_id: str, config: Config) -> None:
    state_mgr = create_state_manager(config)

    if config.storage_backend == "github":
        try:
            await state_mgr.get(feature_id)
        except KeyError:
            await _convert_raw_issue(feature_id, config)

    # ... existing enqueue logic continues unchanged
```

The Azure code path is untouched.

**Acceptance criteria:**
- Calling `enqueue_planner("feat-x", config)` on GitHub when `feat-x` is a raw issue: conversion runs, then enqueue proceeds; final state is `analyzing` with an analyst task queued.
- Calling `enqueue_planner("feat-x", config)` on GitHub when `feat-x` is already initialized: no conversion runs (no extra GitHub writes); enqueue proceeds normally.
- Calling on Azure backend: behavior is identical to the current implementation; no `_convert_raw_issue` reference is reached.
- If no raw issue exists for `feature_id` on GitHub, the `ValueError` from `_convert_raw_issue` propagates to the caller (TUI surfaces it; CLI exits non-zero).

### FR-5: TUI guard for raw features in `action_open_state_change`
The TUI's "open state change" action must not attempt to operate on a raw (unconverted) feature.

In `tui.py`'s `action_open_state_change`, before opening the state-change UI, check whether the selected feature's `state.history` is empty. If so, display the notification `"Convert to harness feature first (press i)"` and return early without opening the dialog.

**Acceptance criteria:**
- Selecting a raw feature and triggering the state-change action shows the notification and does not open the dialog.
- Selecting an initialized feature continues to open the state-change dialog as before.
- No exception is raised in either case.

### FR-6: TUI `i` key continues to work for both raw and initialized features
The existing `i` keybinding in the TUI calls `enqueue_planner`; combined with FR-4, pressing `i` on a raw feature must trigger conversion and then start the pipeline, with no additional UI prompts.

**Acceptance criteria:**
- Pressing `i` on a raw feature in the TUI: conversion runs silently, pipeline starts, the feature transitions out of `brainstormed`.
- Pressing `i` on an already-initialized feature: behavior unchanged from today.
- Errors during conversion (e.g., GitHub API failure, missing issue) are surfaced via the TUI's existing notification mechanism rather than crashing.

## Non-Functional Requirements

### NFR-1: Performance
- `list_features()` overhead: synthesizing a `FeatureState` for raw issues must add no extra GitHub API calls beyond what is already done to list labeled issues. The existing per-issue body parse is reused; raw issues simply skip the JSON-block parse instead of being discarded.
- A single TUI refresh cycle (already at 2s polling) must remain within the existing budget; the addition is in-memory state synthesis.
- `_convert_raw_issue()` is bounded to a small number of GitHub API calls: one list-issues, one branch-create (or 404-tolerated), one artifact upload (one or two REST calls depending on backend), and one issue-update — no looping or pagination beyond what the existing `list_features()` already performs.

### NFR-2: Security
- All GitHub interactions reuse the existing `GitHubClient` and the `GITHUB_TOKEN` already configured for the backend; no new credentials, scopes, or external services are introduced.
- The issue body is treated as user-provided content and embedded into `brief.md` verbatim, mirroring current `convertforagent` behavior. No additional sanitization is required because the brief is consumed by downstream agents that already treat artifact content as untrusted input.
- No secrets are written to issue bodies or artifacts.

### NFR-3: Reliability and idempotency
- `_convert_raw_issue()` is idempotent on its side effects: re-running for the same `feature_id` after a partial failure must not corrupt state. Specifically: existing branch is reused; existing artifact `brief.md` is overwritten with the latest issue body; `patch_existing_issue` replaces (not duplicates) the state block.
- If `_convert_raw_issue` fails partway, the issue's harness label set and body are left in a state where a retry can complete successfully without manual cleanup.
- `enqueue_planner` must remain safe to call multiple times on the same `feature_id` (existing requirement); the new pre-flight does not weaken this.

### NFR-4: Observability
- Conversion is silent in the user-facing UI but must produce log entries (matching the existing log style in `brainstorm.py` and `github_state.py`) so operators can audit when raw issues were auto-converted.
- The previously-emitted "skipped issue: no state block" warning in `list_features()` is replaced by either silence or an informational note that a synthetic state was produced (operator preference; default: silence to reduce noise on every refresh).

## Data Model

### `FeatureState` (existing, unchanged)
No fields are added or removed. Raw issues are represented by:

| Field | Value for raw issue |
|---|---|
| `feature_id` | `feat-{slug(issue.title)}` |
| `status` | `FeatureStatus.brainstormed` |
| `state_issue_number` | issue number |
| `branch_name` | same as `feature_id` |
| `created_at` | issue `created_at` |
| `updated_at` | issue `updated_at` |
| `history` | `[]` |
| `phases` | `[]` (or empty equivalent per existing model) |
| `tasks` | `[]` |

The empty `history` is the canonical signal that a feature is "raw" (i.e., the synthetic record is not a fully initialized feature). Code that needs to distinguish raw from initialized features should test `len(state.history) == 0`.

### Issue label set
- `feature_marker` (configured value, e.g., `agent`) — present on both raw and initialized issues.
- `feat:brainstormed` — added by `patch_existing_issue` on conversion; not required to be present for an issue to be discovered as raw (raw discovery keys off `feature_marker` only).

### Artifacts (existing layout, unchanged)
After conversion: `artifacts/{feature_id}/brief.md` exists on the feature branch with content drawn from the issue body.

## API / Interface Design

### Internal Python API additions

`agentharness/github_state.py`:
- New public method `GitHubStateManager.patch_existing_issue(issue_number: int, state: FeatureState, brief_content: str = "") -> None`.
- Modified behavior of `GitHubStateManager.list_features()`: returns synthetic states for raw issues (no signature change).

`agentharness/brainstorm.py`:
- New private function `_convert_raw_issue(feature_id: str, config: Config) -> None`.
- Modified behavior of `enqueue_planner(feature_id, config)`: GitHub-only pre-flight that calls `_convert_raw_issue` on `KeyError`. No signature change.

`agentharness/tui.py`:
- Modified behavior of `action_open_state_change`: early-return notification when selected feature has empty `history`. No signature change, no new key binding.

### User-visible flows

**Flow A — TUI auto-conversion via `i`:**
1. User adds `feature_marker` label to GitHub issue "Add user export endpoint".
2. TUI refresh (≤2s) shows: `◎  feat-add-user-export-endpoint  □□□□□  brainstormed`.
3. User selects the row and presses `i`.
4. Conversion runs silently; analyst task is queued; row transitions to `analyzing` on the next refresh.

**Flow B — CLI `agentharness implement`:**
1. User runs `agentharness implement feat-add-user-export-endpoint`.
2. Same conversion + enqueue path as Flow A; command exits 0 on success.

**Flow C — TUI state-change attempt on raw feature:**
1. User selects a raw feature and triggers state-change.
2. TUI shows notification "Convert to harness feature first (press i)".
3. Dialog does not open.

## Dependencies
- Existing `GitHubClient` (`agentharness/github_client.py`) — used for issue listing, branch creation, issue update.
- Existing `GitHubArtifactStore` (`agentharness/github_artifacts.py`) — used to upload `brief.md` to the feature branch.
- Existing `GitHubStateManager` (`agentharness/github_state.py`) — extended with the new method.
- Existing `convertforagent` slug algorithm — must be reused (extracted into a shared helper if it is currently duplicated; see Open Questions).
- Textual TUI framework — already in use; no new framework dependencies.
- No new third-party packages.

## Out of Scope
- Azure backend changes — auto-conversion is GitHub-only.
- `agentharness list` CLI command — already works because it goes through `state_mgr.list_features()`, which will return the new synthetic states automatically.
- The `/convertforagent` skill itself — remains available as a manual alternative; not deprecated by this change.
- Detecting and warning on duplicate title slugs across multiple raw issues — existing newest-wins dedup is sufficient for this iteration.
- Closed-issue handling — only open issues with the `feature_marker` label are considered raw features (matches existing behavior).
- Removing the `feature_marker` label after conversion — the label is left in place to match `convertforagent` behavior.
- New TUI status icons or visual treatments for raw vs. initialized features beyond the implicit empty `□□□□□` phase bar.

## Open Questions
None.

## Status: COMPLETE