# Design: Configurable Feature Marker Label

## Component Design

### `GitHubConfig` (agentharness/config.py)

Adds a single field to the existing Pydantic model:

```python
class GitHubConfig(BaseModel):
    token_env: str = "GITHUB_TOKEN"
    owner_env: str = "GITHUB_OWNER"
    runs_repo_env: str = "GITHUB_RUNS_REPO"
    clone_dir: str = ".worktrees"
    feature_marker: str = "agent"
```

**Responsibility:** Single source of truth for the marker string. No validation beyond Pydantic's default str check.

---

### `github_labels.py` (agentharness/github_labels.py)

**Responsibility:** Module-level label constants for internal naming conventions only.

**Change:** Remove `FEATURE_MARKER = "agentharness-feature"`. All other constants (`STATE_LABELS`, `QUEUE_LABELS`, `FEAT_PREFIX`, etc.) remain unchanged. No callers of the removed constant remain after the other changes below.

---

### `GitHubClient` (agentharness/github_client.py)

**Responsibility:** HTTP wrapper around the GitHub REST API. Encapsulates the two-call PR-labeling pattern.

**Interface change:**

```python
async def create_pull_request(
    self,
    title: str,
    body: str,
    head: str,
    base: str,
    labels: list[str] | None = None,
) -> dict:
    """
    Creates a PR. If labels is non-empty, applies them via the issues endpoint
    after PR creation. Does not roll back the PR if label application fails.
    """
```

**Call sequence when `labels` is truthy:**
1. `POST /repos/{owner}/{repo}/pulls` — returns PR dict including `number`.
2. `POST /repos/{owner}/{repo}/issues/{pr["number"]}/labels` with body `{"labels": labels}`.

If step 2 raises, log the error and re-raise. The caller handles the partially-complete state.

---

### `GitHubTaskQueue` (agentharness/github_queue.py)

**Responsibility:** GitHub Issues as a task queue. Owns `feature_marker` for issue creation and label filtering.

**Interface:**

```python
class GitHubTaskQueue:
    def __init__(
        self,
        client: GitHubClient,
        queue_name: str,
        worker_id: str,
        *,
        feature_marker: str,
    ) -> None:
        self._feature_marker = feature_marker

    @classmethod
    def from_config(cls, config: Config, queue_name: str) -> GitHubTaskQueue:
        return cls(
            client=GitHubClient.from_config(config),
            queue_name=queue_name,
            worker_id=_default_worker_id(),
            feature_marker=config.github.feature_marker,
        )

    @classmethod
    async def ensure_all_queues(cls, config: Config, queue_names: list[str]) -> None:
        # reads config.github.feature_marker internally; no signature change for callers
```

All internal label sets that previously included `FEATURE_MARKER` replace it with `self._feature_marker`.

---

### `GitHubStateManager` (agentharness/github_state.py)

**Responsibility:** Feature lifecycle state via GitHub issue labels + JSON body. Owns `feature_marker` for state writes and final PR creation.

**Interface:**

```python
class GitHubStateManager:
    def __init__(
        self,
        client: GitHubClient,
        *,
        feature_marker: str,
    ) -> None:
        self._feature_marker = feature_marker

    @classmethod
    def from_config(cls, config: Config) -> GitHubStateManager:
        return cls(
            client=GitHubClient.from_config(config),
            feature_marker=config.github.feature_marker,
        )

    async def open_review(self, feature_id: str, ...) -> str | None:
        # passes labels=[self._feature_marker] to client.create_pull_request
```

The module-level `parse_state_from_issue` shim is untouched (does not consume the marker).

---

### `observer.py` (agentharness/observer.py)

**Responsibility:** Unified GitHub poller. Reads `config.github.feature_marker` directly for issue-list filtering. Removes the now-deleted `FEATURE_MARKER` import.

**Change:** Replace `from agentharness.github_labels import FEATURE_MARKER` with direct reads of `config.github.feature_marker` at all use sites within the module.

---

### `storage.py` (agentharness/storage.py)

**Responsibility:** Backend factory. Delegates config reading to each class's `from_config` classmethod; does not read `feature_marker` itself.

```python
def create_task_queue(config: Config, queue_name: str) -> TaskQueue:
    if config.storage_backend == "github":
        return GitHubTaskQueue.from_config(config, queue_name)
    ...

def create_state_manager(config: Config) -> StateBackend:
    if config.storage_backend == "github":
        return GitHubStateManager.from_config(config)
    ...
```

No direct references to `feature_marker` in `storage.py`.

---

## Data Schemas

### `GitHubConfig` field addition

| Field | Type | Default | Source |
|---|---|---|---|
| `feature_marker` | `str` | `"agent"` | `config.json` → `github.feature_marker` |

### `config.json` shape

```json
{
  "storage_backend": "github",
  "github": {
    "feature_marker": "my-label"
  }
}
```

Omitting `github.feature_marker` is equivalent to `"agent"`.

### GitHub REST payloads

**PR creation (step 1) — unchanged:**
```
POST /repos/{owner}/{repo}/pulls
Body: { "title": "...", "body": "...", "head": "...", "base": "..." }
Response: { "number": 42, ... }
```

**Label application (step 2) — new, only when `labels` is truthy:**
```
POST /repos/{owner}/{repo}/issues/42/labels
Body: { "labels": ["agent"] }
Response: [ { "name": "agent", ... } ]
```

**Issue creation (existing, now uses instance marker):**
```
POST /repos/{owner}/{repo}/issues
Body: {
  "title": "...",
  "body": "...",
  "labels": ["queue:analyst", "state:analyzing", "agent"]
}
```

### Internal label sets

Labels applied to feature-tracking issues (assembled in `GitHubTaskQueue`):

| Label | Source | Configurable? |
|---|---|---|
| `feat:{feature_id}` | derived from feature ID | No |
| `state:{phase}` | current pipeline phase | No |
| `queue:{queue_name}` | queue name | No |
| `{feature_marker}` | `self._feature_marker` | **Yes** |

Labels applied to the final PR (assembled in `GitHubStateManager.open_review`):

| Label | Source |
|---|---|
| `{feature_marker}` | `self._feature_marker` |

### Test fixture constant

All test files replace `from agentharness.github_labels import FEATURE_MARKER` with a local sentinel:

```python
TEST_FEATURE_MARKER = "test-marker"
```

Constructors under test receive `feature_marker=TEST_FEATURE_MARKER` explicitly.