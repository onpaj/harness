# GitHub Backend Implementation Plan

## Context

AgentHarness currently uses Azure Blob Storage (artifacts) and Azure Storage Queues (inter-agent messaging). This plan implements a GitHub backend that replaces both with GitHub feature branches (artifacts) and GitHub Issues with labels (queue/state). 

**Goal:** `STORAGE_BACKEND=github` in `.env` routes the entire pipeline through GitHub. Azure remains the default and must keep working.

**Already done (do not re-implement):**
- `agentharness/storage_protocol.py` — `RawMessage`, `ArtifactStorage`, `TaskQueue`, `StateBackend` Protocols
- `agentharness/azure_artifacts.py` — `AzureArtifactStore`
- `agentharness/azure_queue.py` — `AzureTaskQueue`
- `agentharness/config.py` — `GitHubConfig` class + `storage_backend: str` field on `Config`
- `agentharness/storage.py` — path helpers + `ArtifactStore`/`PipelineQueue` aliases

**Architecture reference:** `/Users/pajgrtondrej/.claude/plans/i-wonder-if-we-inherited-wilkes.md`

---

## Phase 1 — Foundation (parallel)

### T1: Add httpx dependency

**File:** `pyproject.toml`

Add `httpx[http2]>=0.27.0` to the `dependencies` list. The GitHub client uses `httpx.AsyncClient` for all REST calls.

**Verify:** `pip install -e ".[dev]"` succeeds; `python -c "import httpx"` passes.

---

### T2: `agentharness/github_client.py` — GitHub REST wrapper

Create a thin async HTTP client wrapping GitHub REST API v3.

**Class:** `GitHubClient`

```python
class GitHubClient:
    def __init__(self, token: str, owner: str, repo: str) -> None: ...

    @classmethod
    def from_config(cls, config: Config) -> GitHubClient: ...

    async def close(self) -> None: ...

    # Issues
    async def create_issue(self, title: str, body: str, labels: list[str]) -> dict: ...
    async def get_issue(self, number: int) -> dict: ...
    async def update_issue(self, number: int, *, title: str | None = None, body: str | None = None, state: str | None = None) -> dict: ...
    async def add_labels(self, number: int, labels: list[str]) -> None: ...
    async def remove_label(self, number: int, label: str) -> None: ...
    async def create_comment(self, number: int, body: str) -> dict: ...
    async def update_comment(self, comment_id: int, body: str) -> None: ...
    async def search_issues(self, query: str, sort: str = "created", order: str = "asc") -> list[dict]: ...

    # Sub-issues (GitHub's native parent/child)
    async def add_sub_issue(self, parent_number: int, child_number: int) -> None: ...

    # Refs / branches
    async def get_ref(self, ref: str) -> dict: ...
    async def create_ref(self, ref: str, sha: str) -> dict: ...

    # Contents (for state.json CAS-writes if needed)
    async def get_content(self, path: str, ref: str) -> dict: ...
    async def put_content(self, path: str, message: str, content: str, sha: str | None, branch: str) -> dict: ...

    # Labels (idempotent create)
    async def ensure_label(self, name: str, color: str = "ededed") -> None: ...

    # Pull requests
    async def create_pull_request(self, title: str, body: str, head: str, base: str) -> dict: ...
```

**Implementation notes:**
- Use `httpx.AsyncClient` with `Authorization: Bearer {token}` and `Accept: application/vnd.github+json` headers.
- Raise `GitHubApiError(status_code, message)` for 4xx/5xx.
- For `search_issues`: encode query, return `response["items"]`.
- For conditional GET, use `If-None-Match` header if an etag is provided.
- `add_sub_issue`: POST to `/repos/{owner}/{repo}/issues/{parent}/sub_issues` with `{"sub_issue_id": child_id}`.
- The client is a context manager (`async with GitHubClient(...) as client`).

**File structure:**
```python
class GitHubApiError(Exception):
    def __init__(self, status_code: int, message: str) -> None: ...

class GitHubClient:
    ...
```

**Verify:** Unit tests in `tests/test_github_client.py` mocking `httpx.AsyncClient` responses. Test that `create_issue` sends correct headers, `search_issues` encodes query, `GitHubApiError` is raised on 422.

---

### T3: Label constants

**File:** `agentharness/github_labels.py`

Define all label names used across the GitHub backend as constants. This prevents typos across modules.

```python
# Feature-level status labels
FEAT_ANALYZING = "feat:analyzing"
FEAT_ARCHITECTING = "feat:architecting"
FEAT_DESIGNING = "feat:designing"
FEAT_PLANNING = "feat:planning"
FEAT_DEVELOPING = "feat:developing"
FEAT_REVIEWING = "feat:reviewing"
FEAT_DEV_REVISION = "feat:dev_revision"
FEAT_DONE = "feat:done"
FEAT_FAILED = "feat:failed"

FEAT_STATUS_LABELS: frozenset[str] = frozenset({
    FEAT_ANALYZING, FEAT_ARCHITECTING, FEAT_DESIGNING, FEAT_PLANNING,
    FEAT_DEVELOPING, FEAT_REVIEWING, FEAT_DEV_REVISION, FEAT_DONE, FEAT_FAILED,
})

# Task status labels
STATE_QUEUED = "state:queued"
STATE_IN_PROGRESS = "state:in-progress"
STATE_COMPLETED = "state:completed"
STATE_FAILED = "state:failed"
STATE_DEAD_LETTER = "state:dead-letter"
STATE_BLOCKED = "state:blocked"

TASK_STATE_LABELS: frozenset[str] = frozenset({
    STATE_QUEUED, STATE_IN_PROGRESS, STATE_COMPLETED, STATE_FAILED,
    STATE_DEAD_LETTER, STATE_BLOCKED,
})

# Queue routing labels
QUEUE_ANALYST = "queue:analyst"
QUEUE_ARCHITECT = "queue:architect"
QUEUE_DESIGNER = "queue:designer"
QUEUE_PLANNER = "queue:planner"
QUEUE_DEVELOPER = "queue:developer"
QUEUE_REVIEWER = "queue:reviewer"

# Maps queue-name from config to label
QUEUE_NAME_TO_LABEL: dict[str, str] = {
    "analyst-queue":   QUEUE_ANALYST,
    "architect-queue": QUEUE_ARCHITECT,
    "designer-queue":  QUEUE_DESIGNER,
    "planner-queue":   QUEUE_PLANNER,
    "developer-queue": QUEUE_DEVELOPER,
    "review-queue":    QUEUE_REVIEWER,
}

# Marker label on parent issues
FEATURE_MARKER = "agentharness-feature"

# Claimed-by prefix
CLAIMED_BY_PREFIX = "claimed-by:"

def claimed_by_label(worker_id: str) -> str:
    return f"{CLAIMED_BY_PREFIX}{worker_id}"

def is_claimed_by_label(label: str) -> bool:
    return label.startswith(CLAIMED_BY_PREFIX)
```

**Verify:** Import in Python REPL succeeds; all constants are strings.

---

## Phase 2 — Core GitHub Implementations (sequential after T2, T3)

### T4: `agentharness/github_artifacts.py` — Feature branch artifact store

Implements `ArtifactStorage` protocol. Stores artifacts as files committed to the feature's branch in the runs repo. Uses local git clone as a cache.

**Class:** `GitHubArtifactStore`

```python
class GitHubArtifactStore:
    def __init__(self, client: GitHubClient, feature_id: str, local_clone_dir: Path) -> None: ...

    @classmethod
    def from_config(cls, config: Config, feature_id: str) -> GitHubArtifactStore: ...

    async def upload(self, path: str, content: str | bytes) -> None: ...
    async def download(self, path: str) -> str: ...
    async def exists(self, path: str) -> bool: ...
    async def close(self) -> None: ...
```

**Path convention:** paths passed in are like `artifacts/{feature_id}/spec.r1.md`. The store maps them to `runs/{path}` on the feature branch (i.e., `runs/artifacts/feat-X/spec.r1.md`).

Actually simpler: artifacts are stored at the same `path` on the feature branch. The branch is `feat-{feature_id}` (wait — feature_id already starts with `feat-`, so just use `feature_id` as the branch name).

**Branch:** `feature_id` (e.g., `feat-20260427-abc123`)

**Implementation strategy:**
- Maintain a local clone of the runs repo at `local_clone_dir` (e.g., `.runs-cache/{owner}/{repo}`).
- `upload(path, content)`:
  1. Ensure local clone exists (`git clone` if not, `git fetch` otherwise).
  2. `git checkout {feature_id}` (branch must exist — created by `brainstorm.py`).
  3. Write `content` to `{local_clone_dir}/{path}`.
  4. `git add {path} && git commit -m "agent: upload {path}" && git push origin {feature_id}`.
  5. Use `asyncio.to_thread` for all git operations.
- `download(path)`: `git fetch origin {feature_id} && git show {feature_id}:{path}`.
- `exists(path)`: `git ls-tree -r {feature_id} --name-only | grep {path}`.
- All git subprocess calls use `asyncio.create_subprocess_exec` with `check=True` equivalent.

**Local clone dir:** Configurable, default `.runs-cache`. Store as `config.github_clone_dir` (add this to `GitHubConfig`).

**Verify:** Unit tests in `tests/test_github_artifacts.py` mocking subprocess calls. Test upload writes file, commits, pushes. Test download reads from git show.

---

### T5: `agentharness/github_queue.py` — Issues-as-queue

Implements `TaskQueue` protocol. Each task is a GitHub Issue with labels for queue routing, status, and worker claim.

**Class:** `GitHubTaskQueue`

```python
class GitHubTaskQueue:
    def __init__(self, client: GitHubClient, queue_name: str, worker_id: str) -> None: ...

    @classmethod
    def from_config(cls, config: Config, queue_name: str) -> GitHubTaskQueue: ...

    async def send_task(self, task: TaskMessage, visibility_timeout: int = 0) -> None: ...
    async def receive_task(self, visibility_timeout: int = 30) -> tuple[TaskMessage, RawMessage] | None: ...
    async def delete_message(self, raw: RawMessage) -> None: ...
    async def extend_visibility(self, raw: RawMessage, timeout: int) -> RawMessage: ...
    async def move_to_dead_letter(self, raw: RawMessage, dead_letter_queue_name: str, connection_string: str) -> None: ...
    async def purge(self) -> None: ...
    async def ensure_exists(self) -> None: ...
    async def get_depth(self) -> int: ...
    async def close(self) -> None: ...
```

**Protocol mapping:**

`send_task(task)`:
- Creates a GitHub Issue with:
  - Title: `[{queue_name}] {task.task_id}`
  - Body: YAML frontmatter fenced block with full `TaskMessage` JSON + `--- \n Task: {task.task_id}`
  - Labels: `[queue_label, STATE_QUEUED, FEATURE_MARKER]`
- If `visibility_timeout > 0`: add `STATE_BLOCKED` instead of `STATE_QUEUED` (gated tasks not immediately pickable).
- Returns the issue number (store in `task`'s `RawMessage` later).

`receive_task(visibility_timeout)`:
- Search: `is:open+label:{queue_label}+label:{STATE_QUEUED}+repo:{owner}/{repo}` ordered by created asc.
- Take the oldest issue. If none, return `None`.
- Claim it: remove `STATE_QUEUED`, add `STATE_IN_PROGRESS` + `claimed_by_label(worker_id)`.
- Post heartbeat comment: `"⏱ Started by {worker_id} at {iso_timestamp}"` — store returned `comment_id` in `RawMessage.pop_receipt`.
- Parse `TaskMessage` from the issue body's frontmatter block.
- Return `(task, RawMessage(id=str(issue_number), pop_receipt=str(comment_id), content=raw_body, dequeue_count=...))`.

`extend_visibility(raw, timeout)`:
- Edit the heartbeat comment (by `comment_id` in `raw.pop_receipt`) with new timestamp.
- Return `raw` unchanged (pop_receipt is stable for GitHub — comment_id doesn't change on edit).

`delete_message(raw)` — called on success:
- Add `STATE_COMPLETED`, remove `STATE_IN_PROGRESS` + any `claimed-by:*` labels.
- Close the issue.

`move_to_dead_letter(raw, ...)`:
- Add `STATE_DEAD_LETTER`, remove `STATE_IN_PROGRESS` + `claimed-by:*` labels.
- Post comment: `"⚠️ Dead-lettered after max retries"`.
- Close the issue.

`purge()`:
- Close all open issues with `queue_label`. (Used by TUI 'p' key — dangerous, confirm in docs.)

`ensure_exists()`:
- Call `client.ensure_label(queue_label)`, `client.ensure_label(STATE_QUEUED)`, etc. No-op if labels already exist.

`get_depth()`:
- Search `is:open+label:{queue_label}+label:{STATE_QUEUED}` → return `len(items)`.

**Heartbeat timestamp format:** ISO 8601 UTC, embedded in comment body as `"⏱ Heartbeat: {timestamp}\n\nWorker: {worker_id}"`. Sweeper parses this to check staleness.

**`dequeue_count` in `RawMessage`:** GitHub issues don't have a native dequeue count. Approximate by counting comments that contain "⚠️ Reclaimed" — parse from issue comments list in `receive_task`.

**Verify:** Unit tests in `tests/test_github_queue.py` with mocked `GitHubClient`. Test `send_task` calls `create_issue` with correct labels; `receive_task` returns None on empty search, claims and returns task on hit; `extend_visibility` calls `update_comment`; `delete_message` closes issue; `get_depth` counts open queued issues.

---

### T6: `agentharness/github_state.py` — Issue-label state manager

Implements `StateBackend` protocol. Feature state lives in the parent issue (labels + body frontmatter). Task entries live in task sub-issues.

**Class:** `GitHubStateManager`

```python
class GitHubStateManager:
    def __init__(self, client: GitHubClient) -> None: ...

    @classmethod
    def from_config(cls, config: Config) -> GitHubStateManager: ...

    async def create(self, state: FeatureState) -> None: ...
    async def get(self, feature_id: str) -> FeatureState: ...
    async def update(
        self,
        feature_id: str,
        updater: Callable[[FeatureState], FeatureState],
    ) -> FeatureState: ...
    async def set_worktree_path(self, feature_id: str, worktree_path: str) -> None: ...
    async def set_cleanup_warning(self, feature_id: str, message: str) -> None: ...

    # Internal helpers
    async def _find_parent_issue(self, feature_id: str) -> dict: ...
    async def _state_from_issue(self, issue: dict) -> FeatureState: ...
    async def _apply_diff(self, feature_id: str, old: FeatureState, new: FeatureState) -> None: ...
```

**State serialization:**
- Feature status → parent issue label (one of `FEAT_*` labels).
- `FeatureState` pydantic fields that don't map to labels → stored as a JSON blob in the parent issue body inside a fenced block:
  ```
  ```agentharness-state
  {"feature_id": "...", "created_at": "...", "updated_at": "...", "phases": {...}, "tasks": [...], "history": [...], "config": {...}}
  ```
  ```
  The first line of the issue body (before the fenced block) is the brief summary.
- `worktree_path` and `cleanup_warning` → stored in the JSON blob.

**`create(state)`:**
- Searches for existing parent issue by `feature_id` label (`agentharness-feature` + `feature:{feature_id}`).
- If not found: creates parent issue with title `{feature_id}: {brief_title}`, body = JSON blob, labels = `[FEATURE_MARKER, f"feature:{feature_id}", FEAT_ANALYZING]`.
- This is called once at feature creation.

**`get(feature_id)`:**
- Find parent issue via label `feature:{feature_id}`.
- Parse JSON blob from body.
- Infer `status` from the `feat:*` label on the issue.
- Return reconstructed `FeatureState`.

**`update(feature_id, updater)`:**
- `get()` current state.
- Apply `updater(current)` → `new_state`.
- Compute diff: changed status → add new `feat:*` label, remove old one; body blob always rewritten with full JSON.
- Apply diff via `update_issue(body=...) + add_labels(...) + remove_label(...)`.
- Return `new_state`.
- **No CAS/lease needed** because the pipeline is single-writer per feature at any point in time (serial task execution). If concurrent writes are detected (unlikely), log a warning and continue.

**`set_worktree_path` / `set_cleanup_warning`:**
- Thin wrappers over `update()`, same as Azure `StateManager`.

**`list_features()`** (bonus, used by TUI):
- Search issues with label `agentharness-feature`.
- Return list of `(feature_id, issue_number)` tuples.

**Verify:** Unit tests in `tests/test_github_state.py` with mocked `GitHubClient`. Test `create` creates issue with correct labels and body; `get` reconstructs `FeatureState`; `update` applies label diff and rewrites body.

---

## Phase 3 — Factory Wiring (sequential after Phase 2)

### T7: `agentharness/storage.py` — Backend factory

Replace the current alias-only `storage.py` with a factory that dispatches on `config.storage_backend`.

**Add to `storage.py`:**

```python
from agentharness.azure_artifacts import AzureArtifactStore
from agentharness.azure_queue import AzureTaskQueue
from agentharness.storage_protocol import ArtifactStorage, TaskQueue, StateBackend

def create_artifact_store(config: Config, feature_id: str | None = None) -> ArtifactStorage:
    """Return the configured ArtifactStorage backend."""
    if config.storage_backend == "github":
        from agentharness.github_artifacts import GitHubArtifactStore
        assert feature_id is not None, "feature_id required for GitHub artifact store"
        return GitHubArtifactStore.from_config(config, feature_id)
    from azure.storage.blob.aio import BlobServiceClient
    client = BlobServiceClient.from_connection_string(config.storage.connection_string)
    return AzureArtifactStore(client, config.storage.container)


def create_task_queue(config: Config, queue_name: str) -> TaskQueue:
    """Return the configured TaskQueue backend for a single queue."""
    if config.storage_backend == "github":
        from agentharness.github_queue import GitHubTaskQueue
        return GitHubTaskQueue.from_config(config, queue_name)
    return AzureTaskQueue.from_connection_string(config.storage.connection_string, queue_name)


def create_state_manager(config: Config) -> StateBackend:
    """Return the configured StateBackend."""
    if config.storage_backend == "github":
        from agentharness.github_state import GitHubStateManager
        return GitHubStateManager.from_config(config)
    from azure.storage.blob.aio import BlobServiceClient
    from agentharness.state_manager import StateManager
    client = BlobServiceClient.from_connection_string(config.storage.connection_string)
    return StateManager(client, config.storage.container)
```

Keep all existing path helpers and backward-compat aliases unchanged.

**Verify:** `from agentharness.storage import create_artifact_store, create_task_queue, create_state_manager` imports cleanly. With `config.storage_backend = "azure"`, returns Azure instances. With `"github"`, returns GitHub instances (mock the underlying clients in tests).

---

### T8: `agentharness/observer.py` — Backend selection + sweeper

Two changes:

**1. Use factory in `observe()`:**

Replace the hardcoded Azure client creation (lines 22-34) with:
```python
from agentharness.storage import create_task_queue

queues: dict[str, TaskQueue] = {}
for q_name in config.queue_names():
    q = create_task_queue(config, q_name)
    await q.ensure_exists()
    queues[q_name] = q
```

Remove the `BlobServiceClient` creation and `ArtifactStore`/`store` references (the observer doesn't actually use the artifact store — only `run_task.py` does).

Also remove the `store.ensure_container_exists()` call (Azure-specific). Move it inside `create_artifact_store` for the Azure case.

**2. Add `_sweep_stale_claims()` coroutine (GitHub backend only):**

```python
_STALE_CLAIM_TIMEOUT = 150  # seconds before a claimed task is reclaimed
_SWEEP_INTERVAL = 60        # seconds between sweeps

async def _sweep_stale_claims(config: Config) -> None:
    """Periodically reclaim stale in-progress issues (GitHub backend only)."""
    if config.storage_backend != "github":
        return
    from agentharness.github_client import GitHubClient
    from agentharness.github_labels import STATE_IN_PROGRESS, STATE_QUEUED, is_claimed_by_label
    client = GitHubClient.from_config(config)
    try:
        while True:
            await asyncio.sleep(_SWEEP_INTERVAL)
            try:
                issues = await client.search_issues(
                    f"is:open+label:{STATE_IN_PROGRESS}+repo:{client.owner}/{client.repo}"
                )
                now = datetime.now(UTC)
                for issue in issues:
                    heartbeat_ts = _parse_heartbeat_timestamp(issue)
                    if heartbeat_ts and (now - heartbeat_ts).total_seconds() > _STALE_CLAIM_TIMEOUT:
                        await _reclaim_issue(client, issue)
            except Exception as exc:
                log.warning("Sweeper error: %s", exc)
    finally:
        await client.close()


def _parse_heartbeat_timestamp(issue: dict) -> datetime | None:
    """Parse the heartbeat timestamp from the first comment body containing '⏱ Heartbeat:'."""
    # issue dict may include comments; or we parse from body if embedded
    # Implementation: look for pattern "⏱ Heartbeat: {ISO}" in comments list
    ...


async def _reclaim_issue(client: GitHubClient, issue: dict) -> None:
    """Remove in-progress claim and requeue the issue."""
    number = issue["number"]
    labels_to_remove = [
        lbl["name"] for lbl in issue.get("labels", [])
        if is_claimed_by_label(lbl["name"]) or lbl["name"] == STATE_IN_PROGRESS
    ]
    for label in labels_to_remove:
        await client.remove_label(number, label)
    await client.add_labels(number, [STATE_QUEUED])
    await client.create_comment(number, "⚠️ Reclaimed: stale heartbeat (observer restart or crash)")
    log.info("Reclaimed stale issue #%d", number)
```

Add `_sweep_stale_claims(config)` to the `asyncio.gather(...)` call alongside the queue pollers.

**Verify:** Existing tests still pass (sweeper is no-op for Azure). Add a test that sweeper calls `_reclaim_issue` for issues with stale heartbeat and skips fresh ones.

---

### T9: `agentharness/brainstorm.py` — GitHub branch + issue creation

Add a GitHub-path to `upload_brief()` and `enqueue_planner()`.

**`upload_brief()` GitHub path:**

```python
async def upload_brief(feature_id: str, brief_content: str, config: Config) -> None:
    if config.storage_backend == "github":
        await _upload_brief_github(feature_id, brief_content, config)
        return
    # ... existing Azure path unchanged ...

async def _upload_brief_github(feature_id: str, brief_content: str, config: Config) -> None:
    from agentharness.github_client import GitHubClient
    from agentharness.github_labels import FEAT_ANALYZING, FEATURE_MARKER
    from agentharness.github_state import GitHubStateManager

    client = GitHubClient.from_config(config)
    try:
        # 1. Create branch from main
        main_sha = (await client.get_ref("heads/main"))["object"]["sha"]
        await client.create_ref(f"refs/heads/{feature_id}", main_sha)

        # 2. Commit brief.md to branch
        brief_path = f"artifacts/{feature_id}/brief.md"
        await client.put_content(
            path=brief_path,
            message=f"feat: add brief for {feature_id}",
            content=base64.b64encode(brief_content.encode()).decode(),
            sha=None,
            branch=feature_id,
        )

        # 3. Create initial FeatureState and persist as parent issue
        state = FeatureState(feature_id=feature_id, status=FeatureStatus.analyzing, ...)
        mgr = GitHubStateManager(client)
        await mgr.create(state)
    finally:
        await client.close()
```

**`enqueue_planner()` GitHub path:**

```python
async def enqueue_planner(feature_id: str, config: Config) -> None:
    if config.storage_backend == "github":
        await _enqueue_planner_github(feature_id, config)
        return
    # ... existing Azure path unchanged ...
```

`_enqueue_planner_github` creates the `analyst-1` task issue as a sub-issue of the parent, with labels `[queue:analyst, state:queued]`, body containing the `TaskMessage` JSON for the analyst task.

**Verify:** Unit tests in `tests/test_brainstorm.py` with mocked GitHub client. Verify branch creation, file commit, parent issue creation, and task sub-issue creation all called correctly.

---

### T10: `agentharness/run_task.py` — Git checkout instead of blob download

Replace Azure-specific client creation and blob download/upload with factory-based calls.

**Changes:**

1. Replace hardcoded Azure client creation with factory:
```python
# Remove: blob_service = BlobServiceClient.from_connection_string(...)
# Remove: store = ArtifactStore(blob_service, ...)
# Remove: state_mgr = StateManager(blob_service, ...)
store = create_artifact_store(config, feature_id=task.feature_id)
state_mgr = create_state_manager(config)
```

2. Replace per-queue `PipelineQueue.from_connection_string(...)` with:
```python
all_queues = {q_name: create_task_queue(config, q_name) for q_name in config.queue_names()}
```

3. The `_download_with_retry` function already uses `store.download()` — no change needed to that function.

4. The `store.upload(task.output_artifact, result.output)` call — no change needed (protocol method).

5. Remove `from azure.storage.blob.aio import BlobServiceClient` import.

6. Fix `finally` block — no longer need `await blob_service.close()` separately (it's covered by `await store.close()`).

**Note on GitHub artifact store and work_dir:** When `config.storage_backend == "github"`, the `GitHubArtifactStore` uses a local git clone. The `work_dir` for the developer agent should point to `{clone_dir}/{feature_id}/implementation/`. This needs to be wired: if `task.work_dir` is set and backend is GitHub, set `work_dir = Path(store.get_work_dir())` (add `get_work_dir() -> Path` to `GitHubArtifactStore`).

**Verify:** All existing `run_task` tests still pass. Add tests verifying factory is called and Azure import is removed from the module.

---

### T11: `agentharness/dispatcher.py` — PR on `done`

Add a PR creation step when feature reaches `done` state.

In `_dispatch_review_result()` (around line 310 where `FeatureStatus.done` is set), after writing `with_status(done)`, call:

```python
async def _open_feature_pr(state: FeatureState, config: Config) -> None:
    """Open a GitHub PR for the completed feature (GitHub backend only)."""
    if config.storage_backend != "github":
        return
    from agentharness.github_client import GitHubClient
    client = GitHubClient.from_config(config)
    try:
        pr = await client.create_pull_request(
            title=f"{state.feature_id}: implementation complete",
            body=_build_pr_body(state),
            head=state.feature_id,
            base="main",
        )
        log.info("Opened PR #%d for feature %s", pr["number"], state.feature_id)
    except Exception as exc:
        log.error("Could not open PR for %s: %s", state.feature_id, exc)
    finally:
        await client.close()


def _build_pr_body(state: FeatureState) -> str:
    phases_summary = "\n".join(
        f"- **{phase}**: {info.status.value}"
        for phase, info in state.phases.items()
    )
    tasks_summary = "\n".join(
        f"- {t.task_id}: {t.status.value}"
        for t in state.tasks
    )
    return f"""## Feature: {state.feature_id}

### Phases
{phases_summary}

### Tasks
{tasks_summary}

### Tokens used
{state.total_tokens_used or "unknown"}

---
*Generated by AgentHarness*
"""
```

Call `_open_feature_pr(state, config)` inside `dispatch_after_completion()` when the new state is `done`.

**Important:** `dispatch_after_completion` currently takes `config: Config` — verify it does (line 81), it does.

**Verify:** Existing dispatcher tests still pass. Add test that `_open_feature_pr` is called with GitHub backend and not called with Azure backend.

---

### T12: `agentharness/tui.py` — Issue-based state loading

Replace Azure-specific `_load_all_states` and `_load_queue_depths` with backend-dispatching versions.

**`_load_all_states(config)`** — replace lines 786-813 with:

```python
async def _load_all_states(config: Config) -> list[FeatureState]:
    if config.storage_backend == "github":
        return await _load_states_github(config)
    return await _load_states_azure(config)


async def _load_states_azure(config: Config) -> list[FeatureState]:
    # ... existing Azure implementation (unchanged, just renamed) ...


async def _load_states_github(config: Config) -> list[FeatureState]:
    from agentharness.github_state import GitHubStateManager
    mgr = GitHubStateManager.from_config(config)
    features = await mgr.list_features()
    states: list[FeatureState] = []
    for feature_id, _ in features:
        try:
            state = await mgr.get(feature_id)
            states.append(state)
        except Exception:
            pass
    def sort_key(s: FeatureState):
        active = s.status not in (FeatureStatus.done, FeatureStatus.failed)
        return (not active, -(s.updated_at.timestamp() if s.updated_at else 0))
    return sorted(states, key=sort_key)
```

**`_load_queue_depths(config)`** — replace lines 816-829 with:

```python
async def _load_queue_depths(config: Config) -> dict[str, int]:
    if config.storage_backend == "github":
        return await _load_depths_github(config)
    return await _load_depths_azure(config)


async def _load_depths_azure(config: Config) -> dict[str, int]:
    # ... existing Azure implementation (unchanged, just renamed) ...


async def _load_depths_github(config: Config) -> dict[str, int]:
    from agentharness.storage import create_task_queue
    depths: dict[str, int] = {}
    for queue_name in config.queue_names():
        try:
            q = create_task_queue(config, queue_name)
            depths[queue_name] = await q.get_depth()
            await q.close()
        except Exception:
            depths[queue_name] = 0
    return depths
```

**Verify:** Existing TUI tests still pass. Azure path is unchanged. GitHub path returns same data shape.

---

## Phase 4 — Tests + Integration

### T13: Unit tests for all new modules

Write unit tests (pytest-asyncio) for every new module. All tests must use mocked clients — no real GitHub API calls.

**Test files to create:**
- `tests/test_github_client.py` — covers `create_issue`, `search_issues`, `GitHubApiError`, `ensure_label`
- `tests/test_github_artifacts.py` — covers `upload`, `download`, `exists` with mocked subprocess
- `tests/test_github_queue.py` — covers `send_task`, `receive_task`, `delete_message`, `extend_visibility`, `get_depth`, `purge`
- `tests/test_github_state.py` — covers `create`, `get`, `update`, `set_worktree_path`, `list_features`
- `tests/test_storage_factory.py` — covers `create_artifact_store`, `create_task_queue`, `create_state_manager` with both backends
- `tests/test_observer_sweeper.py` — covers `_sweep_stale_claims` with stale and fresh issues
- `tests/test_brainstorm_github.py` — covers `upload_brief` GitHub path

**Minimum coverage target:** 80% of all new `github_*.py` modules.

**Verify:** `pytest tests/ -v` passes with 0 failures (all 222 existing tests + new ones).

---

### T14: `.env.example` + documentation update

**File:** `.env.example`

Append GitHub env vars:
```bash
# GitHub backend (set STORAGE_BACKEND=github to use)
GITHUB_TOKEN=
GITHUB_OWNER=
GITHUB_RUNS_REPO=
STORAGE_BACKEND=azure
```

**File:** `.pipeline/config.json`

No changes needed — queue names are backend-agnostic.

**File:** `agentharness/cli.py`

Update the `init` command's `.env.example` writer (search for `AZURE_STORAGE_CONNECTION_STRING=` in `cli.py`) to also include the GitHub vars.

**Verify:** `.env.example` contains all required vars. `agentharness init` creates a complete example.

---

## Dependency Graph

```
T1 (httpx dep)
T3 (labels)
     ↓
T2 (github_client) ──→ T4 (github_queue)
                   ──→ T5 (github_artifacts)
                   ──→ T6 (github_state)
                            ↓
T4 + T5 + T6 ──→ T7 (storage factory)
                        ↓
              ┌─────────┼──────────┐
              T8        T9         T10
           (brainstorm) (run_task) (dispatcher)
              └─────────┴──────────┘
                        ↓
                    T11 (tui)
                        ↓
                    T12 (tests)
                        ↓
                    T13 (docs)
```

**Parallel tasks:** T1 + T2 + T3 can all start at once. T4 + T5 + T6 can run in parallel once T2 and T3 are done. T8 + T9 + T10 + T11 can run in parallel once T7 is done.

---

## Acceptance Criteria (end-to-end)

1. `pytest tests/ -v` — 0 failures, ≥80% coverage on new modules.
2. `STORAGE_BACKEND=azure` — existing pipeline works identically (Azure tests pass, no regressions).
3. `STORAGE_BACKEND=github` smoke test:
   - `agentharness brainstorm` creates a feature branch in `agentharness-runs-test` repo.
   - `agentharness implement feat-X` opens parent issue + analyst task sub-issue with correct labels.
   - Observer picks up the task issue, runs agent, commits output to feature branch, closes sub-issue.
   - On feature `done`, a PR is opened from `feat-X` → `main`.
4. Crash recovery: kill observer mid-task, restart — sweeper reclaims the stale issue within 150s.
5. `agentharness watch` renders correctly from GitHub issue state.

---

## Key Files Reference

| File | Role | Status |
|------|------|--------|
| `agentharness/storage_protocol.py` | Protocol types + RawMessage | ✅ Done |
| `agentharness/azure_artifacts.py` | Azure blob impl | ✅ Done |
| `agentharness/azure_queue.py` | Azure queue impl | ✅ Done |
| `agentharness/config.py` | GitHubConfig + storage_backend | ✅ Done |
| `agentharness/github_labels.py` | Label constants | T3 |
| `agentharness/github_client.py` | httpx REST wrapper | T2 |
| `agentharness/github_artifacts.py` | Git branch artifact store | T5 |
| `agentharness/github_queue.py` | Issues-as-queue | T4 |
| `agentharness/github_state.py` | Issue-label state manager | T6 |
| `agentharness/storage.py` | Backend factory | T7 |
| `agentharness/observer.py` | Sweeper + backend select | T8 |
| `agentharness/brainstorm.py` | GitHub branch+issue creation | T9 |
| `agentharness/run_task.py` | Git checkout + factory | T10 |
| `agentharness/dispatcher.py` | PR on done | T11 |
| `agentharness/tui.py` | Issue-based state read | T12 |
| `pyproject.toml` | httpx dependency | T1 |
