# Feature Brief: Configurable Feature Marker Label

## Problem Statement
The GitHub backend uses a hardcoded label `"agentharness-feature"` to identify feature issues. Users running AgentHarness in their own repos want to use their own label name. Additionally, the final PR created when a feature completes carries no identifying label, making it hard to filter in GitHub.

## Goals
- Allow the feature marker label to be configured per project via `config.json`
- Label the final PR with the configured feature marker label

## Functional Requirements
- Add `feature_marker: str = "agent"` field to `GitHubConfig` in `agentharness/config.py`
- Remove the hardcoded `FEATURE_MARKER = "agentharness-feature"` constant from `agentharness/github_labels.py`
- Pass `feature_marker` from config into `GitHubQueue` and `GitHubStateManager` via constructor
- Update factory functions in `storage.py` (`create_task_queue`, `create_state_manager`) to pass `config.github.feature_marker`
- Update `observer.py` to read `config.github.feature_marker` directly
- Add optional `labels: list[str] = []` parameter to `github_client.py:create_pull_request()`
- In `github_state.py:open_review()`, pass `[self._feature_marker]` as labels when creating the PR

## Non-Functional Requirements
- Backward compatible: existing deployments work without config changes (default `"agent"`)
- No performance impact

## Technical Constraints
- Python, Pydantic models for config
- GitHub backend only — Azure backend is unaffected
- `GitHubConfig` in `agentharness/config.py` is the right home for the new field
- GitHub REST API supports `labels` in the PR creation payload natively

## Out of Scope
- Other label types (`feat:*`, `state:*`, `queue:*`) remain as constants in `github_labels.py`
- Azure backend changes
- Environment variable override for the feature marker

## Success Criteria
- Setting `"github": { "feature_marker": "my-label" }` in `config.json` causes all feature issues and the final PR to use `"my-label"` instead of the default
- Omitting the field uses `"agent"` as default
- Final PR is labeled with the configured feature marker
- All existing tests pass; new/updated tests cover the configurable marker

## Additional Context
Full design spec at: `docs/superpowers/specs/2026-04-29-configurable-feature-marker-design.md`

Files to change:
- `agentharness/config.py`
- `agentharness/github_labels.py`
- `agentharness/github_queue.py`
- `agentharness/github_state.py`
- `agentharness/observer.py`
- `agentharness/storage.py`
- `agentharness/github_client.py`
- `tests/test_github_state.py`
- `tests/test_github_queue.py`
