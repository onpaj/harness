# Configurable Feature Marker Label Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the GitHub backend's feature marker label configurable per project via `config.json` (default `"agent"`) and apply that label to the final pull request created when a feature completes.

**Architecture:** Replace the hardcoded `FEATURE_MARKER = "agentharness-feature"` constant with a `feature_marker: str` field on `GitHubConfig`. Thread the marker through constructor injection into `GitHubTaskQueue` and `GitHubStateManager` (via their `from_config` classmethods). Extend `GitHubClient.create_pull_request` to accept an optional `labels` argument and apply them via the issues-labels REST endpoint after PR creation. `open_review` passes `[self._feature_marker]` to attach the marker to the final PR.

**Tech Stack:** Python 3.11+, Pydantic, httpx (async), pytest + pytest-asyncio, GitHub REST API v3.

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `agentharness/config.py` | Pydantic config models | Add `feature_marker: str = "agent"` to `GitHubConfig` |
| `agentharness/github_labels.py` | Label name constants | Delete `FEATURE_MARKER` constant |
| `agentharness/github_client.py` | Async HTTP wrapper for GitHub REST | Add `labels: list[str] \| None = None` to `create_pull_request`; perform second REST call to apply labels |
| `agentharness/github_queue.py` | Issue-as-task-queue | Add `feature_marker` keyword-only `__init__` param; thread through `from_config` and `ensure_all_queues`; replace constant references |
| `agentharness/github_state.py` | Issue-as-feature-state | Add `feature_marker` keyword-only `__init__` param; thread through `from_config`; replace constant references; pass `labels=[self._feature_marker]` in `open_review` |
| `agentharness/observer.py` | Unified GitHub poller | Replace `FEATURE_MARKER` import with `config.github.feature_marker` reads; update `_collect_states`, `_handle_implement_issue` |
| `agentharness/storage.py` | Backend factory | No code change — factories already delegate to `from_config` |
| `tests/test_github_state.py` | Unit tests | Replace `FEATURE_MARKER` import with local `TEST_FEATURE_MARKER = "test-marker"`; pass marker to constructor in fixtures |
| `tests/test_github_queue.py` | Unit tests | Same pattern; pass `feature_marker` to constructor; update `ensure_all_queues` test if present |
| `tests/test_github_client.py` (new or extended) | Unit tests | Cover the two-call labeled-PR creation path |
| `tests/test_config.py` | Config unit tests | Add coverage for new `feature_marker` default and override |
| `.env.example` and project README | Operator docs | Document new `github.feature_marker` config key |

No new files in production code. One new (or extended) test file for `GitHubClient.create_pull_request`.

---

## Task 1: Add `feature_marker` field to `GitHubConfig`

**Files:**
- Modify: `agentharness/config.py:74-93`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_config.py` (append at end of the file, or create the file if it does not yet exist with the relevant imports):

```python
import json
from pathlib import Path

import pytest
from pydantic import BaseModel

from agentharness.config import Config, GitHubConfig, load_config


def test_github_config_default_feature_marker():
    """GitHubConfig.feature_marker defaults to 'agent' when not specified."""
    cfg = GitHubConfig()
    assert cfg.feature_marker == "agent"


def test_github_config_accepts_custom_feature_marker():
    """GitHubConfig.feature_marker accepts a user-supplied value."""
    cfg = GitHubConfig(feature_marker="my-label")
    assert cfg.feature_marker == "my-label"


def test_load_config_reads_feature_marker_from_json(tmp_path: Path):
    """load_config wires github.feature_marker from config.json."""
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "storage_backend": "github",
        "github": {"feature_marker": "custom-marker"},
        "queues": {},
    }))
    config = load_config(config_path)
    assert config.github.feature_marker == "custom-marker"


def test_load_config_defaults_feature_marker_when_missing(tmp_path: Path):
    """load_config falls back to 'agent' when github.feature_marker is omitted."""
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "storage_backend": "github",
        "github": {},
        "queues": {},
    }))
    config = load_config(config_path)
    assert config.github.feature_marker == "agent"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_config.py -v -k "feature_marker"`
Expected: FAIL — `GitHubConfig` has no `feature_marker` attribute (AttributeError) or schema mismatch.

- [ ] **Step 3: Add the field to `GitHubConfig`**

Edit `agentharness/config.py`. Find the `GitHubConfig` class and add the `feature_marker` field:

```python
class GitHubConfig(BaseModel):
    token_env: str = "GITHUB_TOKEN"
    owner_env: str = "GITHUB_OWNER"      # optional — falls back to git remote
    runs_repo_env: str = "GITHUB_RUNS_REPO"  # optional — falls back to git remote
    clone_dir: str = ".worktrees"
    feature_marker: str = "agent"

    @property
    def token(self) -> str:
        value = os.environ.get(self.token_env)
        if not value:
            raise RuntimeError(f"Environment variable {self.token_env!r} is not set.")
        return value

    @property
    def owner(self) -> str:
        return os.environ.get(self.owner_env) or _parse_github_remote()[0]

    @property
    def runs_repo(self) -> str:
        return os.environ.get(self.runs_repo_env) or _parse_github_remote()[1]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_config.py -v -k "feature_marker"`
Expected: PASS — all four feature_marker tests pass.

- [ ] **Step 5: Commit**

```bash
git add agentharness/config.py tests/test_config.py
git commit -m "feat: add feature_marker field to GitHubConfig"
```

---

## Task 2: Add labeled-PR support to `GitHubClient.create_pull_request`

**Files:**
- Modify: `agentharness/github_client.py:297-304`
- Test: `tests/test_github_client.py` (create if missing)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_github_client.py` (or append if it exists). Use `respx` if available, otherwise mock `_request` directly. The codebase doesn't appear to have respx — mock the `_request` method directly:

```python
"""Unit tests for agentharness.github_client.GitHubClient."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from agentharness.github_client import GitHubClient


def _make_client() -> GitHubClient:
    return GitHubClient(token="test-token", owner="acme", repo="runs")


@pytest.mark.asyncio
async def test_create_pull_request_without_labels_makes_one_call():
    """When labels is None, only POST /pulls is called."""
    client = _make_client()
    with patch.object(
        client, "_request", new=AsyncMock(return_value={"number": 1, "html_url": "u"})
    ) as mock_request:
        result = await client.create_pull_request(
            title="t", body="b", head="feat", base="main"
        )
    assert result == {"number": 1, "html_url": "u"}
    assert mock_request.await_count == 1
    method, url = mock_request.call_args[0][:2]
    assert method == "POST"
    assert url.endswith("/pulls")
    await client.close()


@pytest.mark.asyncio
async def test_create_pull_request_with_empty_labels_makes_one_call():
    """Empty list labels=[] is treated like None — no second call."""
    client = _make_client()
    with patch.object(
        client, "_request", new=AsyncMock(return_value={"number": 1})
    ) as mock_request:
        await client.create_pull_request(
            title="t", body="b", head="feat", base="main", labels=[]
        )
    assert mock_request.await_count == 1
    await client.close()


@pytest.mark.asyncio
async def test_create_pull_request_with_labels_applies_them_via_issues_endpoint():
    """When labels is non-empty, a second POST /issues/{n}/labels call is made."""
    client = _make_client()
    responses = [
        {"number": 42, "html_url": "https://example/pr/42"},  # POST /pulls
        [{"name": "agent"}],                                   # POST /issues/42/labels
    ]
    with patch.object(
        client, "_request", new=AsyncMock(side_effect=responses)
    ) as mock_request:
        result = await client.create_pull_request(
            title="t", body="b", head="feat", base="main", labels=["agent"]
        )
    assert result == {"number": 42, "html_url": "https://example/pr/42"}
    assert mock_request.await_count == 2
    second_method, second_url = mock_request.await_args_list[1].args[:2]
    assert second_method == "POST"
    assert second_url.endswith("/issues/42/labels")
    second_kwargs = mock_request.await_args_list[1].kwargs
    assert second_kwargs["json"] == {"labels": ["agent"]}
    await client.close()


@pytest.mark.asyncio
async def test_create_pull_request_reraises_when_label_apply_fails():
    """If label application fails, the error propagates (no rollback)."""
    client = _make_client()
    responses = [
        {"number": 99, "html_url": "u"},
        RuntimeError("rate limited"),
    ]

    async def _side_effect(*args, **kwargs):
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    with patch.object(client, "_request", new=AsyncMock(side_effect=_side_effect)):
        with pytest.raises(RuntimeError, match="rate limited"):
            await client.create_pull_request(
                title="t", body="b", head="feat", base="main", labels=["agent"]
            )
    await client.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_github_client.py -v`
Expected: FAIL — `create_pull_request` has no `labels` parameter (TypeError) and tests expecting two calls fail.

- [ ] **Step 3: Update `create_pull_request`**

Edit `agentharness/github_client.py`. Replace the existing `create_pull_request` method (around lines 297-304) with:

```python
    async def create_pull_request(
        self,
        title: str,
        body: str,
        head: str,
        base: str,
        labels: list[str] | None = None,
    ) -> dict:
        """Create a PR; if `labels` is non-empty, apply them via the issues endpoint.

        GitHub's POST /pulls does not accept labels in the payload — PRs are issues
        under the hood, so labels are applied via POST /issues/{number}/labels after
        PR creation. If label application fails, the error is logged and re-raised;
        the PR is not rolled back.
        """
        pr = await self._request(
            "POST",
            self._repo_url("/pulls"),
            json={"title": title, "body": body, "head": head, "base": base},
        )
        if labels:
            number = pr["number"]
            try:
                await self._request(
                    "POST",
                    self._repo_url(f"/issues/{number}/labels"),
                    json={"labels": labels},
                )
            except Exception:
                log.error(
                    "Failed to apply labels %r to PR #%s in %s/%s; PR is created but unlabeled",
                    labels, number, self.owner, self.repo,
                )
                raise
        return pr
```

Note: this method references `log`. Add a module-level logger near the top imports if not already present:

```python
import logging

log = logging.getLogger(__name__)
```

Place these imports next to the other top-of-file imports (after the `import httpx` line). If a `log` already exists, leave it alone.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_github_client.py -v`
Expected: PASS — all four tests pass.

- [ ] **Step 5: Commit**

```bash
git add agentharness/github_client.py tests/test_github_client.py
git commit -m "feat: support labels parameter in create_pull_request"
```

---

## Task 3: Inject `feature_marker` into `GitHubTaskQueue`

**Files:**
- Modify: `agentharness/github_queue.py:16-110`
- Test: `tests/test_github_queue.py:1-373`

- [ ] **Step 1: Update tests to use a local `TEST_FEATURE_MARKER` sentinel**

Edit `tests/test_github_queue.py`. Make these changes:

1. Replace the import block (around lines 16-23):

```python
from agentharness.github_labels import (
    STATE_BLOCKED,
    STATE_COMPLETED,
    STATE_DEAD_LETTER,
    STATE_IN_PROGRESS,
    STATE_QUEUED,
)
```

2. Add a test sentinel constant after the imports:

```python
TEST_FEATURE_MARKER = "test-marker"
```

3. Update `_make_queue` (around lines 68-73) to pass the marker:

```python
def _make_queue(client: MagicMock | None = None) -> GitHubTaskQueue:
    return GitHubTaskQueue(
        client=client or _make_client(),
        queue_name=_QUEUE_NAME,
        worker_id=_WORKER_ID,
        feature_marker=TEST_FEATURE_MARKER,
    )
```

4. Update the `test_send_task_creates_issue_with_correct_labels` assertion (around line 110):

```python
    assert set(kwargs["labels"]) == {_QUEUE_LABEL, STATE_QUEUED, TEST_FEATURE_MARKER}
```

5. Update the `test_ensure_exists_calls_ensure_labels_with_all_required_labels` expected set (around lines 348-358):

```python
    expected = {
        _QUEUE_LABEL,
        STATE_QUEUED,
        STATE_IN_PROGRESS,
        STATE_COMPLETED,
        STATE_DEAD_LETTER,
        STATE_BLOCKED,
        TEST_FEATURE_MARKER,
    }
    assert expected.issubset(called_labels)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_github_queue.py -v`
Expected: FAIL — `GitHubTaskQueue.__init__()` got an unexpected keyword argument `feature_marker`, plus `FEATURE_MARKER` import errors elsewhere.

- [ ] **Step 3: Update `GitHubTaskQueue`**

Edit `agentharness/github_queue.py`. Make these changes:

1. Update the imports block (around lines 16-29) — remove `FEATURE_MARKER`:

```python
from agentharness.github_labels import (
    CLAIMED_BY_PREFIX,
    IMPLEMENT_LABEL,
    QUEUE_NAME_TO_LABEL,
    STATE_BLOCKED,
    STATE_COMPLETED,
    STATE_DEAD_LETTER,
    STATE_IN_PROGRESS,
    STATE_QUEUED,
    TASK_STATE_LABELS,
    claimed_by_label,
    is_claimed_by_label,
)
```

2. Replace the `__init__` method (around lines 61-70):

```python
    def __init__(
        self,
        client: GitHubClient,
        queue_name: str,
        worker_id: str,
        *,
        feature_marker: str,
    ) -> None:
        self._client = client
        self._queue_name = queue_name
        self._worker_id = worker_id
        self._queue_label = QUEUE_NAME_TO_LABEL.get(queue_name, f"queue:{queue_name}")
        self._feature_marker = feature_marker
```

3. Update `from_config` (around lines 80-89):

```python
    @classmethod
    def from_config(cls, config: Config, queue_name: str) -> GitHubTaskQueue:
        from agentharness.github_client import GitHubClient

        client = GitHubClient.from_config(config)
        return cls(
            client=client,
            queue_name=queue_name,
            worker_id=_default_worker_id(),
            feature_marker=config.github.feature_marker,
        )
```

4. Update `ensure_all_queues` (around lines 91-110):

```python
    @classmethod
    async def ensure_all_queues(cls, config: Config, queue_names: list[str]) -> None:
        """Ensure all labels for every queue in one GitHub API list call."""
        from agentharness.github_client import GitHubClient

        client = GitHubClient.from_config(config)
        queue_labels = [
            QUEUE_NAME_TO_LABEL.get(q, f"queue:{q}") for q in queue_names
        ]
        all_labels = queue_labels + [
            STATE_QUEUED,
            STATE_IN_PROGRESS,
            STATE_COMPLETED,
            STATE_DEAD_LETTER,
            STATE_BLOCKED,
            config.github.feature_marker,
            IMPLEMENT_LABEL,
        ]
        await client.ensure_labels(all_labels)
        await client.close()
```

5. Replace `FEATURE_MARKER` references in `send_task` and `ensure_exists`:

Around line 119 (`send_task`):
```python
        labels = [self._queue_label, state_label, self._feature_marker]
```

Around line 257 (`ensure_exists`):
```python
        labels_needed = [
            self._queue_label,
            STATE_QUEUED,
            STATE_IN_PROGRESS,
            STATE_COMPLETED,
            STATE_DEAD_LETTER,
            STATE_BLOCKED,
            self._feature_marker,
        ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_github_queue.py -v`
Expected: PASS — all `test_github_queue.py` tests pass.

- [ ] **Step 5: Commit**

```bash
git add agentharness/github_queue.py tests/test_github_queue.py
git commit -m "feat: thread feature_marker into GitHubTaskQueue via constructor"
```

---

## Task 4: Inject `feature_marker` into `GitHubStateManager`

**Files:**
- Modify: `agentharness/github_state.py:19-365`
- Test: `tests/test_github_state.py:11-492`

- [ ] **Step 1: Update tests to use `TEST_FEATURE_MARKER`**

Edit `tests/test_github_state.py`. Make these changes:

1. Replace the import block (around lines 11-17) — remove `FEATURE_MARKER`:

```python
from agentharness.github_labels import (
    FEATURE_STATUS_TO_LABEL,
    FEAT_ANALYZING,
    FEAT_DEVELOPING,
    FEAT_DONE,
)
```

2. Add a test sentinel after the import block:

```python
TEST_FEATURE_MARKER = "test-marker"
```

3. Update `_make_issue` (around lines 46-61) to use `TEST_FEATURE_MARKER`:

```python
def _make_issue(
    state: FeatureState,
    *,
    number: int = 42,
    brief_content: str = "",
    extra_labels: list[str] | None = None,
) -> dict:
    """Build a minimal GitHub issue dict with state embedded in the body."""
    feat_lbl = _feature_label(state.feature_id)
    status_lbl = FEATURE_STATUS_TO_LABEL[state.status]
    label_names = [TEST_FEATURE_MARKER, feat_lbl, status_lbl] + (extra_labels or [])
    return {
        "number": number,
        "body": _replace_state_block(brief_content, state),
        "labels": [{"name": n} for n in label_names],
    }
```

4. Update every direct `GitHubStateManager(client)` call to pass the marker. There are many (search for `GitHubStateManager(client)`):

```python
mgr = GitHubStateManager(client, feature_marker=TEST_FEATURE_MARKER)
```

5. Update assertions at lines 137-148 in `test_create_calls_ensure_label_and_create_issue`:

```python
    # Assert — ensure_labels called with marker and status label
    client.ensure_labels.assert_awaited_once()
    labels_arg, _ = client.ensure_labels.call_args
    assert TEST_FEATURE_MARKER in labels_arg[0]
    assert FEATURE_STATUS_TO_LABEL[state.status] in labels_arg[0]

    # Assert — create_issue called with correct labels and title
    client.create_issue.assert_awaited_once()
    _, kwargs = client.create_issue.call_args
    assert kwargs["title"] == _feature_issue_title(state.feature_id)
    assert TEST_FEATURE_MARKER in kwargs["labels"]
    assert FEATURE_STATUS_TO_LABEL[state.status] in kwargs["labels"]
```

6. Update lines 233 and 442 (any remaining `FEATURE_MARKER` references in test bodies):

```python
        {"name": TEST_FEATURE_MARKER},
```

and

```python
        "labels": [{"name": TEST_FEATURE_MARKER}],
```

7. Update `test_from_config_creates_instance` (around lines 475-491):

```python
def test_from_config_creates_instance():
    # Arrange
    config = MagicMock()
    config.github.token = "ghp_test"
    config.github.owner = "acme"
    config.github.runs_repo = "runs"
    config.github.feature_marker = "configured-marker"

    with patch(
        "agentharness.github_client.GitHubClient.from_config",
        return_value=AsyncMock(),
    ) as mock_from_config:
        # Act
        mgr = GitHubStateManager.from_config(config)

        # Assert
        mock_from_config.assert_called_once_with(config)
        assert isinstance(mgr, GitHubStateManager)
        assert mgr._feature_marker == "configured-marker"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_github_state.py -v`
Expected: FAIL — `GitHubStateManager.__init__()` got unexpected keyword argument `feature_marker`, plus import errors.

- [ ] **Step 3: Update `GitHubStateManager`**

Edit `agentharness/github_state.py`. Make these changes:

1. Update imports (around lines 19-24) — remove `FEATURE_MARKER`:

```python
from agentharness.github_labels import (
    FEATURE_STATUS_TO_LABEL,
    FEAT_STATUS_LABELS,
    LABEL_TO_FEATURE_STATUS,
)
```

2. Replace `__init__` and `from_config` (around lines 115-125):

```python
class GitHubStateManager:
    """StateBackend implementation backed by GitHub Issues."""

    def __init__(
        self,
        client: GitHubClient,
        *,
        feature_marker: str,
    ) -> None:
        self._client = client
        self._feature_marker = feature_marker

    @classmethod
    def from_config(cls, config: Config) -> GitHubStateManager:
        from agentharness.github_client import GitHubClient

        return cls(
            client=GitHubClient.from_config(config),
            feature_marker=config.github.feature_marker,
        )
```

3. Update `_find_issue` (around line 156):

```python
        items = await self._client.list_issues(labels=[self._feature_marker])
```

4. Update `create` (around lines 195-214) — replace both `FEATURE_MARKER` references:

```python
    async def create(self, state: FeatureState, brief_content: str = "") -> None:
        """Create a GitHub issue representing the feature's initial state.

        The issue body contains the brief content followed by the fenced
        agentharness-state block holding the serialized FeatureState JSON.
        """
        status_label = FEATURE_STATUS_TO_LABEL[state.status]
        await self._client.ensure_labels([self._feature_marker, status_label], color="0075ca")

        title = _feature_issue_title(state.feature_id)
        body = _replace_state_block(brief_content, state)
        issue = await self._client.create_issue(
            title=title,
            body=body,
            labels=[self._feature_marker, status_label],
        )
        issue_number: int = issue["number"]
        updated = state.model_copy(update={"state_issue_number": issue_number})
        await self._client.update_issue(issue_number, body=_replace_state_block(brief_content, updated))
        log.debug("Created state issue #%d for feature %s", issue_number, state.feature_id)
```

5. Update `list_features` (around lines 280-292) — replace both `FEATURE_MARKER` references:

```python
        items = await self._client.list_issues(labels=[self._feature_marker], direction="desc")

        # feature_id -> (issue_number, issue_dict) — keep newest issue per feature
        seen: dict[str, tuple[int, dict]] = {}
        for issue in items:
            feature_id = _feature_id_from_issue(issue)
            if feature_id is None:
                log.warning(
                    "Issue #%d has %s label but no parseable state JSON — skipping",
                    issue["number"],
                    self._feature_marker,
                )
                continue
```

6. Update `open_review` (around lines 316-364) — pass `labels=[self._feature_marker]` to `create_pull_request`:

```python
        try:
            default_branch = await self._client.get_default_branch()
            pr = await self._client.create_pull_request(
                title=f"{feature_id}: implementation complete",
                body=_build_pr_body(state),
                head=feature_id,
                base=default_branch,
                labels=[self._feature_marker],
            )
            pr_url = pr.get("html_url")
            ...
```

(Leave the surrounding try/except and logging unchanged.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_github_state.py -v`
Expected: PASS — all `test_github_state.py` tests pass.

- [ ] **Step 5: Add a unit test asserting `open_review` passes the marker as a label**

Append to `tests/test_github_state.py`:

```python
# ---------------------------------------------------------------------------
# open_review
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_open_review_passes_feature_marker_as_label():
    """The final PR is created with the configured feature_marker label."""
    # Arrange
    state = _make_state(status=FeatureStatus.done)
    issue = _make_issue(state, number=20)
    client = _mock_client()
    client.list_issues.return_value = [issue]
    client.get_default_branch.return_value = "main"
    client.create_pull_request.return_value = {
        "number": 99,
        "html_url": "https://example/pr/99",
    }
    mgr = GitHubStateManager(client, feature_marker=TEST_FEATURE_MARKER)

    # Act
    pr_url = await mgr.open_review(state.feature_id)

    # Assert
    assert pr_url == "https://example/pr/99"
    client.create_pull_request.assert_awaited_once()
    _, kwargs = client.create_pull_request.call_args
    assert kwargs["labels"] == [TEST_FEATURE_MARKER]
    assert kwargs["base"] == "main"
    assert kwargs["head"] == state.feature_id
```

Run: `.venv/bin/pytest tests/test_github_state.py::test_open_review_passes_feature_marker_as_label -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add agentharness/github_state.py tests/test_github_state.py
git commit -m "feat: thread feature_marker into GitHubStateManager and apply to final PR"
```

---

## Task 5: Update `observer.py` to read `config.github.feature_marker`

**Files:**
- Modify: `agentharness/observer.py:106-302`

- [ ] **Step 1: Replace `FEATURE_MARKER` import and uses**

Edit `agentharness/observer.py`. Find the import inside `_unified_github_poll` (around line 117):

Replace:
```python
    from agentharness.github_labels import FEATURE_MARKER, IMPLEMENT_LABEL, LABEL_TO_QUEUE_NAME, STATE_IN_PROGRESS, STATE_QUEUED
```

With:
```python
    from agentharness.github_labels import IMPLEMENT_LABEL, LABEL_TO_QUEUE_NAME, STATE_IN_PROGRESS, STATE_QUEUED
```

Then update the `list_issues` call (around line 147):

Replace:
```python
                issues = await client.list_issues(labels=[FEATURE_MARKER])
```

With:
```python
                issues = await client.list_issues(labels=[config.github.feature_marker])
```

- [ ] **Step 2: Update `_handle_implement_issue` to thread the marker into `GitHubStateManager`**

Around line 286 in `_handle_implement_issue`, replace:
```python
        await GitHubStateManager(client).create(state, body)
```

With:
```python
        await GitHubStateManager(
            client, feature_marker=config.github.feature_marker
        ).create(state, body)
```

- [ ] **Step 3: Update `_collect_states` to pass the marker into `GitHubStateManager`**

`_collect_states` (around lines 305-329) currently constructs `GitHubStateManager(client)` without a marker. The function takes only `client` and `issues`, not `config`, so we need to either:

(a) Thread `config` into `_collect_states`, or
(b) Inline the parsing without instantiating `GitHubStateManager` (preferred — `_state_from_issue` is the only call, and it's a thin wrapper).

Use option (a) — add `config: Config` to the signature.

Replace the function body (around lines 305-329) with:

```python
async def _collect_states(
    client: "GitHubClient", issues: list[dict], config: Config
) -> list[dict]:
    """Parse FeatureState from tracking issues only, skipping task queue issues.

    Deduplicates by feature_id, keeping the highest-numbered issue per feature.
    """
    from agentharness.github_labels import TASK_STATE_LABELS
    from agentharness.github_state import GitHubStateManager, parse_state_from_issue

    seen: dict[str, tuple[int, dict]] = {}  # feature_id -> (issue_number, state_dict)
    for issue in issues:
        label_names = {lbl["name"] for lbl in issue.get("labels", [])}
        if label_names & TASK_STATE_LABELS:
            continue  # task queue issue, not a tracking issue
        state = parse_state_from_issue(issue)
        if state is None:
            try:
                mgr = GitHubStateManager(
                    client, feature_marker=config.github.feature_marker
                )
                state = await mgr._state_from_issue(issue)
            except Exception:
                continue
        issue_number: int = issue.get("number", 0)
        existing = seen.get(state.feature_id)
        if existing is None or issue_number > existing[0]:
            seen[state.feature_id] = (issue_number, state.model_dump(mode="json"))
    return [entry[1] for entry in seen.values()]
```

Then update the call site inside `_unified_github_poll` (around line 209):

Replace:
```python
                states = await _collect_states(client, issues)
```

With:
```python
                states = await _collect_states(client, issues, config)
```

- [ ] **Step 4: Verify no `FEATURE_MARKER` references remain in observer.py**

Run: `grep -n "FEATURE_MARKER" agentharness/observer.py`
Expected: no output (the constant is fully removed from this module).

- [ ] **Step 5: Run all observer-related tests and the full suite to spot regressions**

Run: `.venv/bin/pytest tests/ -v`
Expected: PASS — same tests as before (no observer-specific tests existed for `_collect_states`; the change is mechanical and exercised indirectly).

- [ ] **Step 6: Commit**

```bash
git add agentharness/observer.py
git commit -m "feat: read feature_marker from config in observer"
```

---

## Task 6: Remove `FEATURE_MARKER` constant from `github_labels.py`

**Files:**
- Modify: `agentharness/github_labels.py:85`

- [ ] **Step 1: Verify no remaining references**

Run: `grep -rn "FEATURE_MARKER" agentharness/ tests/`
Expected: only matches in `agentharness/github_labels.py` itself (line 85). If any other file references it, return to the relevant task.

- [ ] **Step 2: Delete the constant**

Edit `agentharness/github_labels.py`. Remove line 85:

```python
FEATURE_MARKER = "agentharness-feature"
```

The surrounding section header comment "Marker and claim labels" can stay (or be tightened, optional). Leave the rest of the file unchanged.

- [ ] **Step 3: Run the full test suite to verify nothing imports the removed constant**

Run: `.venv/bin/pytest tests/ -v`
Expected: PASS — all tests pass.

- [ ] **Step 4: Verify no lingering imports**

Run: `grep -rn "from agentharness.github_labels import" agentharness/ tests/ | grep -i feature_marker`
Expected: no output.

- [ ] **Step 5: Commit**

```bash
git add agentharness/github_labels.py
git commit -m "refactor: remove hardcoded FEATURE_MARKER constant"
```

---

## Task 7: Verify `storage.py` factory is unchanged and end-to-end wiring is correct

**Files:**
- Verify only: `agentharness/storage.py:64-78`

- [ ] **Step 1: Inspect `storage.py`**

Read `agentharness/storage.py:64-78`. Confirm:

- `create_task_queue` calls `GitHubTaskQueue.from_config(config, queue_name)`.
- `create_state_manager` calls `GitHubStateManager.from_config(config)`.

Both `from_config` classmethods now read `config.github.feature_marker` internally (Tasks 3 and 4). No factory change needed.

- [ ] **Step 2: Run an integration-style test**

Run: `.venv/bin/pytest tests/ -v`
Expected: PASS — entire suite green.

- [ ] **Step 3: Sanity-check that end-to-end objects carry the marker**

Add to `tests/test_config.py` (append):

```python
def test_storage_factories_thread_feature_marker_to_github_classes(tmp_path: Path):
    """Both factories produce GitHub instances carrying the configured marker."""
    import os
    from agentharness.storage import create_state_manager, create_task_queue

    os.environ.setdefault("GITHUB_TOKEN", "ghp_dummy_for_test")
    os.environ.setdefault("GITHUB_OWNER", "acme")
    os.environ.setdefault("GITHUB_RUNS_REPO", "runs")

    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "storage_backend": "github",
        "github": {"feature_marker": "wired-through"},
        "queues": {"analyst-queue": {"agent": ".agents/analyst.md"}},
    }))
    config = load_config(config_path)

    queue = create_task_queue(config, "analyst-queue")
    state = create_state_manager(config)

    assert queue._feature_marker == "wired-through"
    assert state._feature_marker == "wired-through"
```

Run: `.venv/bin/pytest tests/test_config.py::test_storage_factories_thread_feature_marker_to_github_classes -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/test_config.py
git commit -m "test: verify storage factories thread feature_marker into GitHub backends"
```

---

## Task 8: Update operator-facing docs and examples

**Files:**
- Modify: `.env.example` (if it exists)
- Modify: project README (if it documents the GitHub backend)
- Modify: `.pipeline/config.json` (add a commented example — optional, since JSON does not support comments; if not tolerated, skip)

- [ ] **Step 1: Inspect existing docs**

Run: `ls .env.example README.md 2>/dev/null; grep -l "storage_backend" *.md docs/**/*.md 2>/dev/null`
Decide which file is the right place to mention the new key. If `README.md` has a "GitHub backend" section, add to it; otherwise add to `.env.example` near other GitHub config notes.

- [ ] **Step 2: Add operator note**

Add the following snippet to the most appropriate doc (likely `README.md` under the GitHub backend section). If both `README.md` and `.env.example` are present, prefer `README.md`:

```markdown
**`feature_marker`** (optional, defaults to `"agent"`)

The label applied to feature-tracking issues and the final pull request. Set this in
`.pipeline/config.json` to use a project-specific marker — required when running multiple
AgentHarness deployments in the same GitHub organization.

```json
{
  "storage_backend": "github",
  "github": {
    "feature_marker": "my-project-agent"
  }
}
```

**Migration from earlier versions:** the legacy hardcoded marker was `"agentharness-feature"`.
After upgrade, in-flight features tracked under that label become invisible. To preserve
legacy behavior, set `"feature_marker": "agentharness-feature"` in your config; otherwise,
rename existing labels in the GitHub UI to `"agent"` (or your chosen marker).
```

- [ ] **Step 3: Commit**

```bash
git add README.md .env.example
git commit -m "docs: document feature_marker config and migration"
```

If only one of the two files was touched, adjust the `git add` accordingly.

---

## Task 9: Final smoke check

- [ ] **Step 1: Run the entire test suite**

Run: `.venv/bin/pytest tests/ -v`
Expected: PASS — all tests green.

- [ ] **Step 2: Confirm the constant is fully gone**

Run: `grep -rn "FEATURE_MARKER" agentharness/ tests/`
Expected: no output.

- [ ] **Step 3: Confirm the new field is reachable from a fresh `Config` load**

Run a one-liner sanity:
```bash
.venv/bin/python -c "from agentharness.config import GitHubConfig; print(GitHubConfig().feature_marker)"
```
Expected: `agent`

- [ ] **Step 4: (Optional) Coverage check**

Run: `.venv/bin/pytest tests/ --cov=agentharness --cov-report=term-missing`
Expected: coverage on the touched modules is at or above 80% on the changed code paths.

---

## Self-Review Checklist (already applied during plan authoring)

**Spec coverage:**
- FR-1 (`feature_marker` field) → Task 1
- FR-2 (remove `FEATURE_MARKER`) → Task 6
- FR-3 (`GitHubTaskQueue` injection) → Task 3
- FR-4 (`GitHubStateManager` injection) → Task 4
- FR-5 (factories thread marker) → Tasks 3, 4, 7 (factories delegate to `from_config`)
- FR-6 (observer reads from config) → Task 5
- FR-7 (`labels` parameter on `create_pull_request`) → Task 2
- FR-8 (apply marker to final PR) → Task 4 (open_review test) + Task 2 (client support)
- NFR-1..NFR-5 → Covered implicitly by tests + minimal API surface change.
- Open Questions OQ-1..OQ-5 → Resolved per spec/arch decisions and documented in Task 8 release notes.

**Type/symbol consistency:**
- `feature_marker` is a keyword-only kwarg on `GitHubTaskQueue.__init__` and `GitHubStateManager.__init__`.
- `from_config` classmethods on both classes thread `config.github.feature_marker`.
- `create_pull_request` adds `labels: list[str] | None = None` (consistent across signature, test, and call site).
- All references to `self._feature_marker` are read-only after construction.

**Placeholder scan:** no TBD/TODO/"similar to" stubs.
