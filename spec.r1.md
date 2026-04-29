# Specification: Configurable Feature Marker Label

## Summary
Make the GitHub backend's feature marker label configurable per project via `config.json` instead of using the hardcoded `"agentharness-feature"` constant, and apply that label to the final pull request created when a feature completes. This enables multi-tenant usage where different projects can use distinct marker labels for filtering.

## Background
AgentHarness's GitHub backend identifies feature-tracking issues with a label, currently hardcoded as `"agentharness-feature"` in `agentharness/github_labels.py:FEATURE_MARKER`. Two problems result:

1. **No per-project customization.** Users running AgentHarness in their own repositories cannot pick a label that fits their conventions or coexist with other AgentHarness deployments in the same org without label collisions.
2. **Unlabeled final PR.** When a feature completes and a PR is opened via `github_state.py:open_review()`, no marker label is applied. This makes the PR indistinguishable from manual PRs in GitHub UI filters and search queries.

Other label categories (`feat:*`, `state:*`, `queue:*`) are derivative naming conventions used internally and remain constants. Only the *feature marker* — the discriminator that says "this is an AgentHarness feature" — needs to be configurable.

## Functional Requirements

### FR-1: Add `feature_marker` field to `GitHubConfig`
Extend the Pydantic `GitHubConfig` model in `agentharness/config.py` with a new field:

```python
feature_marker: str = "agent"
```

The default value is `"agent"` (a deliberate change from the legacy `"agentharness-feature"`, per the brief's stated default). The field is loaded from the `github.feature_marker` key in `.pipeline/config.json` and is optional.

**Acceptance criteria:**
- `GitHubConfig` exposes a `feature_marker: str` attribute with default `"agent"`.
- A `config.json` containing `{"github": {"feature_marker": "my-label"}}` produces a `GitHubConfig` with `feature_marker == "my-label"`.
- A `config.json` omitting the field produces a `GitHubConfig` with `feature_marker == "agent"`.
- The field validates as a non-empty string (Pydantic default validation; empty string is technically allowed but should not be supplied).

### FR-2: Remove `FEATURE_MARKER` constant from `github_labels.py`
Delete the module-level constant `FEATURE_MARKER = "agentharness-feature"` from `agentharness/github_labels.py`. Any helper functions in that module that referenced it must accept the marker as a parameter or be moved to call sites that hold the configured value.

**Acceptance criteria:**
- `agentharness/github_labels.py` no longer exports `FEATURE_MARKER`.
- No remaining references to the symbol exist anywhere in `agentharness/` or `tests/` (verified by grep).
- All other constants (`STATE_LABELS`, `QUEUE_LABELS`, `FEAT_PREFIX`, etc.) remain unchanged.

### FR-3: Inject `feature_marker` into `GitHubQueue`
Modify `agentharness/github_queue.py:GitHubQueue.__init__()` to accept `feature_marker: str` as a constructor parameter and store it as `self._feature_marker`. Replace internal references to the removed constant with `self._feature_marker`.

**Acceptance criteria:**
- `GitHubQueue(client, queue_name, feature_marker, ...)` constructs successfully.
- All issue-creation, label-filtering, and label-application code paths within `GitHubQueue` use `self._feature_marker` instead of the constant.
- Existing tests that instantiate `GitHubQueue` are updated to pass the marker.

### FR-4: Inject `feature_marker` into `GitHubStateManager`
Modify `agentharness/github_state.py:GitHubStateManager.__init__()` to accept `feature_marker: str` as a constructor parameter and store it as `self._feature_marker`. Replace internal references to the removed constant with `self._feature_marker`.

**Acceptance criteria:**
- `GitHubStateManager(client, feature_marker, ...)` constructs successfully.
- `parse_state_from_issue()` and any other helpers that need the marker either accept it as a parameter or are called from instances that hold it.
- Issue-listing, state-write, and label-application code paths use `self._feature_marker`.

### FR-5: Update factory functions in `storage.py`
Modify `agentharness/storage.py`:
- `create_task_queue(config, queue_name)` must pass `config.github.feature_marker` to `GitHubQueue`.
- `create_state_manager(config)` must pass `config.github.feature_marker` to `GitHubStateManager`.

The Azure branches of these factories are unchanged.

**Acceptance criteria:**
- Both factories thread the configured marker into the GitHub-backend constructors.
- No factory code reads the marker from any source other than `config.github.feature_marker`.

### FR-6: Update `observer.py` to read `config.github.feature_marker`
The unified GitHub poller in `agentharness/observer.py` must read the marker from `config.github.feature_marker` directly (rather than importing a constant) for any operations that filter or apply the label outside the queue/state-manager abstractions.

**Acceptance criteria:**
- `observer.py` contains no import of the removed `FEATURE_MARKER` constant.
- Any label-based issue filtering in the observer uses `config.github.feature_marker`.
- The observer continues to function identically when `feature_marker` is set to `"agent"`.

### FR-7: Add `labels` parameter to `create_pull_request()`
Extend `agentharness/github_client.py:create_pull_request()` with a new optional parameter:

```python
async def create_pull_request(
    self,
    repo: str,
    title: str,
    head: str,
    base: str,
    body: str,
    labels: list[str] | None = None,
) -> dict: ...
```

Behavior:
- If `labels` is `None` or empty, the PR is created exactly as before (no labels applied).
- If `labels` is non-empty, the labels are applied to the PR after creation. GitHub's `POST /repos/{owner}/{repo}/pulls` does not accept labels in the payload — labels are applied to the underlying *issue* via `POST /repos/{owner}/{repo}/issues/{number}/labels`. The client must perform this second call when labels are supplied.

**Note:** The brief states "GitHub REST API supports `labels` in the PR creation payload natively." This is incorrect — PRs in GitHub are issues under the hood, and labels are applied via the issues labels endpoint. This deviation is documented in Open Questions.

**Acceptance criteria:**
- Calling `create_pull_request(..., labels=["my-label"])` produces a PR with `my-label` applied.
- Calling `create_pull_request(...)` without `labels` produces a PR with no labels (existing behavior preserved).
- If label application fails after PR creation, the PR is **not** rolled back; the failure is logged and re-raised, so the caller can handle the partially completed state.
- The function remains idempotent-friendly with respect to retries: re-applying an existing label is a no-op on GitHub's side.

### FR-8: Apply feature marker label to final PR
In `agentharness/github_state.py:open_review()` (or the corresponding method that creates the final PR when a feature reaches `done`), pass `labels=[self._feature_marker]` to `create_pull_request()`.

**Acceptance criteria:**
- When a feature completes, the resulting PR carries the configured `feature_marker` label.
- The PR can be retrieved by filtering on that label via `gh pr list --label <marker>` or the GitHub UI.
- Setting `feature_marker` to a custom value (e.g., `"my-label"`) results in the PR carrying `"my-label"`, not `"agent"` and not the legacy `"agentharness-feature"`.

## Non-Functional Requirements

### NFR-1: Performance
- The added label-application call adds at most one extra GitHub REST request per *completed feature* (not per agent run). This is negligible relative to the overall pipeline cost.
- No change to per-task or per-poll overhead.
- No change to the unified GitHub poller's API call budget per cycle.

### NFR-2: Security
- No secrets or credentials are introduced.
- The `feature_marker` value is plain text and visible in logs and GitHub UI; users should not encode sensitive information in it. This expectation is implicit in the "label" semantics and needs no special documentation.
- No change to authentication or authorization flow.

### NFR-3: Backward Compatibility
- Existing deployments that do not specify `github.feature_marker` in `config.json` receive the default value `"agent"`.
- **Behavior change:** Deployments that previously relied on the hardcoded `"agentharness-feature"` label will, after upgrade, start using `"agent"`. Pre-existing issues labeled `"agentharness-feature"` will no longer be discovered by the observer. This is a breaking change at the data level for in-flight features and must be called out in release notes. See Open Questions.

### NFR-4: Configurability
- A single change to `config.json` propagates the marker through all label-aware code paths without code changes.
- The configuration is read once at startup; runtime changes require an observer restart.

### NFR-5: Test Coverage
- Updated and new unit tests cover the configurable marker in `tests/test_github_state.py` and `tests/test_github_queue.py`.
- Coverage of the new code paths must meet the project's 80% baseline.
- Tests use mocked GitHub clients (no live API calls).

## Data Model

### `GitHubConfig` (Pydantic)
| Field | Type | Default | Description |
|---|---|---|---|
| `token` | `str` | (required) | GitHub PAT |
| `owner` | `str` | (auto-detected) | Repo owner |
| `runs_repo` | `str` | (auto-detected) | Repo name |
| **`feature_marker`** | **`str`** | **`"agent"`** | **Label applied to feature-tracking issues and the final PR** |

No new domain entities are introduced. The marker is a plain string, applied as a GitHub label to:
- Each feature-tracking issue (existing behavior, now with configurable label name)
- The final PR opened when the feature completes (new behavior)

## API / Interface Design

### Configuration (`config.json`)
```json
{
  "storage_backend": "github",
  "github": {
    "feature_marker": "my-label"
  }
}
```

### Python API changes

```python
# agentharness/config.py
class GitHubConfig(BaseModel):
    ...
    feature_marker: str = "agent"

# agentharness/github_queue.py
class GitHubQueue:
    def __init__(self, client, queue_name, feature_marker: str, ...): ...

# agentharness/github_state.py
class GitHubStateManager:
    def __init__(self, client, feature_marker: str, ...): ...

# agentharness/github_client.py
async def create_pull_request(
    self,
    repo: str,
    title: str,
    head: str,
    base: str,
    body: str,
    labels: list[str] | None = None,
) -> dict: ...

# agentharness/storage.py
def create_task_queue(config, queue_name):
    if config.storage_backend == "github":
        return GitHubQueue(..., feature_marker=config.github.feature_marker)

def create_state_manager(config):
    if config.storage_backend == "github":
        return GitHubStateManager(..., feature_marker=config.github.feature_marker)
```

### GitHub REST flow for labeled PR
1. `POST /repos/{owner}/{repo}/pulls` — create PR (no labels in payload).
2. `POST /repos/{owner}/{repo}/issues/{pr_number}/labels` with body `{"labels": ["agent"]}` — apply label.

## Dependencies
- **Pydantic** — already in use for config models. No new dependency.
- **httpx** — already used by `github_client.py`. The added labels call uses the existing client.
- **GitHub REST API** — `POST /repos/{owner}/{repo}/issues/{number}/labels` endpoint. No new permissions required beyond what the existing PAT already has (PRs and issues share scope).
- **No new external services or libraries.**

## Out of Scope
- Making `feat:*`, `state:*`, `queue:*`, and other label families configurable. Only the feature marker is parameterized.
- Azure backend changes — the Azure backend uses no labels and is unaffected.
- Environment-variable override for `feature_marker` (e.g., `AGENTHARNESS_FEATURE_MARKER`). Configuration is `config.json` only.
- Migration tooling to relabel existing `"agentharness-feature"` issues to the new default `"agent"`.
- Per-feature override (different markers for different features within one project).
- Validation that the configured label name is valid per GitHub's label-name rules (length, characters). Pydantic's default string validation is sufficient; invalid values will surface as 422 errors at the GitHub API boundary.
- UI/TUI changes to display or filter by the configured marker.

## Open Questions

### OQ-1: Default value choice — `"agent"` vs preserving `"agentharness-feature"`
The brief specifies `"agent"` as the default. However, this changes behavior for existing deployments: features tracked under the legacy `"agentharness-feature"` label become invisible after upgrade.

**Assumption:** We follow the brief and use `"agent"` as the default, treating this as an intentional breaking change. Release notes must document the migration path: either rename existing labels in the repo or set `feature_marker: "agentharness-feature"` in `config.json` to preserve old behavior.

**Decision needed:** Confirm whether the breaking default is acceptable, or whether the default should be `"agentharness-feature"` to preserve compatibility (with new deployments encouraged to override).

### OQ-2: GitHub API for PR label application
The brief states "GitHub REST API supports `labels` in the PR creation payload natively." This is inaccurate — `POST /pulls` does not accept a `labels` field; labels must be applied via the issues endpoint after PR creation.

**Assumption:** Implementation will use the two-call pattern (create PR, then apply labels via `POST /issues/{n}/labels`). No functional impact, just an extra HTTP round-trip per completed feature.

### OQ-3: Failure semantics when label application fails after PR creation
If the PR is created successfully but the subsequent labels API call fails (network, rate limit, etc.), what is the desired behavior?

**Assumption:** Log the error and re-raise. The PR exists but is unlabeled; manual intervention or a retry of the dispatcher's terminal step can re-apply the label (idempotent). Do not attempt to delete the PR.

### OQ-4: Validation of `feature_marker` value
Should we validate the marker against GitHub's label naming rules (e.g., max 50 chars, no certain special characters)?

**Assumption:** No upfront validation. GitHub will reject invalid names with a 422 at runtime, which surfaces as a clear error in observer logs. Adding Pydantic validators for GitHub's specific rules is not justified for a single config field.

### OQ-5: Label creation
If the configured `feature_marker` does not yet exist as a label in the target repository, GitHub will auto-create it on first use (label creation is implicit when applying an unknown label to an issue/PR). Is this the desired behavior, or should the system pre-create the label with a specific color/description?

**Assumption:** Rely on GitHub's implicit label creation. Color and description are cosmetic and can be set manually post-hoc by the repo owner. No code is needed to manage label metadata.