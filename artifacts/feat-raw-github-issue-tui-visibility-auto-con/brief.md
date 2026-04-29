# Raw GitHub Issue TUI Visibility + Auto-Conversion

**Date:** 2026-04-29  
**Status:** approved

## Problem

When a user labels a GitHub issue with the `feature_marker` label (e.g. `agent`), AgentHarness currently ignores it — `list_features()` skips issues without a parseable `agentharness-state` JSON block. The user must manually run `/convertforagent <issue-number>` to make it visible in the TUI and pipeline.

## Goal

- Issues labeled with `feature_marker` appear in the TUI immediately as `brainstormed` — no manual conversion step.
- When the user presses `i` in the TUI (or runs `agentharness implement <feature-id>`), the issue is silently converted and the pipeline starts.

---

## Architecture

### 1. `GitHubStateManager.list_features()` — synthetic states for raw issues

**Current behaviour:** issues with feature_marker label but no `agentharness-state` JSON block are skipped with a warning log.

**New behaviour:** for each such issue, build a synthetic `FeatureState`:

```python
FeatureState(
    feature_id=f"feat-{slug(issue['title'])}",   # same 40-char slug algorithm as convertforagent
    status=FeatureStatus.brainstormed,
    state_issue_number=issue["number"],
    branch_name=f"feat-{slug(issue['title'])}",
    created_at=<issue.created_at>,
    updated_at=<issue.updated_at>,
    # history, phases, tasks all empty — distinguishes raw from initialized
)
```

Deduplication (newest issue per feature_id) is unchanged. No new fields added to `FeatureState`.

### 2. `GitHubStateManager.patch_existing_issue()` — new method

Patches an existing GitHub issue to embed state JSON — same logic as `create()` but updates rather than creates:

```python
async def patch_existing_issue(
    self,
    issue_number: int,
    state: FeatureState,
    brief_content: str = "",
) -> None:
    # 1. ensure feat:brainstormed label exists
    # 2. add feat:brainstormed label to issue (feature_marker already present)
    # 3. replace/append agentharness-state block in issue body
    # 4. call self._client.update_issue(issue_number, body=new_body)
```

### 3. `brainstorm._convert_raw_issue()` — new private async function

Runs the full conversion (equivalent to `/convertforagent`) in Python, without `gh` CLI subprocesses:

```python
async def _convert_raw_issue(feature_id: str, config: Config) -> None:
    # 1. List issues with feature_marker label
    # 2. Find the one whose title-slug matches feature_id
    #    → raise ValueError("no raw issue found for '{feature_id}'") if none
    # 3. Build FeatureState(status=brainstormed, state_issue_number=..., branch_name=feature_id)
    # 4. Create feature branch via GitHubClient (from default branch SHA; skip if exists)
    # 5. Upload artifacts/{feature_id}/brief.md via GitHubArtifactStore (issue body as brief)
    # 6. Call state_mgr.patch_existing_issue(issue_number, state, brief_content)
```

### 4. `brainstorm.enqueue_planner()` — auto-conversion pre-flight (GitHub only)

```python
async def enqueue_planner(feature_id: str, config: Config) -> None:
    state_mgr = create_state_manager(config)

    # GitHub-only: silently convert raw issues before proceeding
    if config.storage_backend == "github":
        try:
            await state_mgr.get(feature_id)
        except KeyError:
            await _convert_raw_issue(feature_id, config)

    # ... rest unchanged
```

No changes to the Azure path.

### 5. TUI adjustments

**`action_open_state_change`:** add guard for raw (unconverted) features — if `state.history` is empty, show notification `"Convert to harness feature first (press i)"` and return early.

**`_feature_label`:** no changes needed — `_phase_bar()` and `_task_summary()` already handle empty phases/tasks gracefully. Raw issues render as: `◎  {short-id}  □□□□□  brainstormed`.

---

## Data flow

```
User labels issue "agent"
        ↓
TUI refresh (list_features)
        ↓ issue has no state JSON
Synthetic FeatureState(status=brainstormed, state_issue_number=N)
        ↓
TUI displays: ◎  feat-my-feature  □□□□□  brainstormed
        ↓
User presses i
        ↓
enqueue_planner("feat-my-feature", config)
        ↓ state_mgr.get() raises KeyError
_convert_raw_issue("feat-my-feature", config)
  → find issue #N by title-slug match
  → create branch feat-my-feature
  → upload brief.md
  → patch_existing_issue(N, state, brief)
        ↓
Normal enqueue_planner flow continues
  → state_mgr.update(status=analyzing)
  → queue analyst task
```

---

## Files changed

| File | Change |
|------|--------|
| `agentharness/github_state.py` | `list_features()`: build synthetic state for raw issues; add `patch_existing_issue()` |
| `agentharness/brainstorm.py` | `enqueue_planner()`: add GitHub pre-flight; add `_convert_raw_issue()` |
| `agentharness/tui.py` | `action_open_state_change()`: guard for empty-history (raw) states |

---

## Out of scope

- Azure backend (no changes)
- `agentharness list` CLI command (works already via `state_mgr.list_features()`)
- `convertforagent` skill (remains as manual alternative; not deprecated)
- Detecting duplicate title slugs (existing dedup logic handles it)