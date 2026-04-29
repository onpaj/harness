# Configurable Feature Marker Label

**Date:** 2026-04-29  
**Status:** Approved

## Summary

Two related changes to the GitHub backend:
1. The `agentharness-feature` label used to identify feature issues is moved from a hardcoded constant to a configurable field in `GitHubConfig`, defaulting to `"agent"`.
2. The final PR opened when a feature completes is labeled with the configured feature marker.

## Config Change

Add `feature_marker: str = "agent"` to `GitHubConfig` in `agentharness/config.py`.

Configurable via `config.json`:
```json
{
  "github": { "feature_marker": "my-project" }
}
```

When omitted, defaults to `"agent"`. Backward compatible — existing deployments that relied on `"agentharness-feature"` must set the field explicitly if they want to preserve that label.

The constant `FEATURE_MARKER` in `agentharness/github_labels.py` is removed (no longer used at runtime).

## Propagation

The marker string flows into the three runtime consumers:

| Component | Change |
|-----------|--------|
| `GitHubQueue` | Accepts `feature_marker: str` in `__init__`; replaces imported constant |
| `GitHubStateManager` | Same pattern; stores as `self._feature_marker` |
| `observer.py` | Reads `config.github.feature_marker` directly (already has `config` in scope) |

Factory functions `create_task_queue` and `create_state_manager` in `storage.py` pass `config.github.feature_marker` when constructing these objects.

## PR Labeling

`github_client.py:create_pull_request()` gains an optional `labels: list[str] = []` parameter, included in the GitHub API JSON body.

`github_state.py:open_review()` passes `[self._feature_marker]` to label the PR with the configured marker.

## Files Changed

- `agentharness/config.py` — add `feature_marker` field to `GitHubConfig`
- `agentharness/github_labels.py` — remove `FEATURE_MARKER` constant
- `agentharness/github_queue.py` — accept `feature_marker` in constructor
- `agentharness/github_state.py` — accept `feature_marker` in constructor; use in `open_review()`
- `agentharness/observer.py` — read from `config.github.feature_marker`
- `agentharness/storage.py` — pass `feature_marker` to factory-constructed objects
- `agentharness/github_client.py` — add `labels` param to `create_pull_request()`
- `tests/test_github_state.py` — update fixture/assertions for new constant
- `tests/test_github_queue.py` — update assertions for new constant

## Out of Scope

- Azure backend (no concept of labels)
- Any other label values (`feat:*`, `state:*`, `queue:*`) — those remain as constants in `github_labels.py`
