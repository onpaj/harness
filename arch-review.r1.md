```markdown
# Architecture Review: Configurable Feature Marker Label

## Architectural Fit Assessment

This change fits cleanly into the existing pluggable backend system. The GitHub backend already isolates label conventions in `github_labels.py` and threads dependencies through constructors / factory functions in `storage.py`. The feature only loosens *one* hardcoded constant into a configuration-driven value — no new abstractions, no new modules, no new backend interactions.

The integration points are narrow and well-defined:
1. **Configuration plane** — `GitHubConfig` (Pydantic) loaded from `.pipeline/config.json`.
2. **Storage factories** — `storage.py:create_task_queue` and `create_state_manager`.
3. **GitHub-specific consumers** — `GitHubTaskQueue`, `GitHubStateManager`, the `observer.py` unified poller, and the `GitHubClient.create_pull_request` HTTP wrapper.
4. **Tests** — `test_github_state.py` and `test_github_queue.py` need fixtures that supply the marker.

The change is *additive* in the public API (new optional config field, new optional `labels` parameter on `create_pull_request`) and *structurally substitutive* in the internal API (constant → instance attribute). The Azure backend is untouched.

The only real architectural friction is the `parse_state_from_issue` module-level shim in `github_state.py` — it does not consume `FEATURE_MARKER`, so it survives unchanged, but the work overlaps with the comment-marked refactor opportunity. I recommend leaving it alone in this change.

## Proposed Architecture

### Component Overview

```
.pipeline/config.json
        │
        ▼
   GitHubConfig.feature_marker  ◄─── single source of truth
        │
        ▼
   storage.py factories
   ├─► create_task_queue(config, name)   ──► GitHubTaskQueue(client, name, worker_id, feature_marker)
   ├─► create_state_manager(config)      ──► GitHubStateManager(client, feature_marker)
   └─► observer.py: reads config.github.feature_marker directly for unified poller filter

   GitHubClient.create_pull_request(title, body, head, base, labels=None)
        │  if labels:
        ▼
   POST /repos/{o}/{r}/pulls          ─► returns PR
   POST /repos/{o}/{r}/issues/{n}/labels  ─► applies labels (PRs are issues)
```

Class-level state remains immutable after construction: `feature_marker` is set in `__init__` and only read thereafter. No new global state, no new threading concerns, no new caching.

### Key Design Decisions

#### Decision 1: Constructor injection over module-level setter
**Options considered:**
- (A) Set the constant once at startup via a setter (`set_feature_marker(value)`).
- (B) Pass marker through factory → constructor → instance attribute.
- (C) Read `os.environ` from inside `github_labels.py`.

**Chosen approach:** (B) — constructor injection.

**Rationale:** (A) introduces hidden global mutable state and a startup-ordering hazard (any import that pre-reads the constant breaks). (C) violates the "config.json only" scope (Out of Scope per spec). (B) matches the existing pattern: `GitHubClient.from_config`, `GitHubTaskQueue.from_config`, `GitHubStateManager.from_config` all already thread config-derived values via constructors. No surprises for readers.

#### Decision 2: Two-call pattern for PR labeling, encapsulated in `GitHubClient.create_pull_request`
**Options considered:**
- (A) Caller opens the PR, then calls `add_labels(pr_number, [...])` separately.
- (B) `create_pull_request` accepts `labels: list[str] | None` and performs both REST calls internally.

**Chosen approach:** (B).

**Rationale:** The brief misstates GitHub API behavior (`POST /pulls` does **not** accept `labels`). The spec correctly identifies this. Encapsulating the two-call pattern in the client matches the abstraction level of the rest of `GitHubClient` (callers think in terms of "create a labeled PR", not "create an issue-like resource then PATCH labels"). The PR `number` returned by step 1 is needed for step 2 anyway, so keeping both calls together avoids exposing that detail to `github_state.py`.

The function must **not** roll back on label failure (spec FR-7, OQ-3): re-raise after logging. The caller of `open_review` already swallows exceptions and returns `None`, so this composes correctly.

#### Decision 3: Default value — accept the breaking change, do not silently preserve `"agentharness-feature"`
**Options considered:**
- (A) Default `"agent"` (per brief / spec).
- (B) Default `"agentharness-feature"` to preserve existing-deployment behavior.
- (C) Detect existing labeled issues and default to whichever label is present.

**Chosen approach:** (A) — keep the brief's default of `"agent"`.

**Rationale:** (C) is over-engineered. (B) defeats the brief's intent of nudging users toward a project-specific label. (A) is an explicit, opt-in behavior change. Existing operators *must* set `feature_marker: "agentharness-feature"` in their config.json to retain prior behavior — and this is a one-line change clearly documented in release notes. Treat OQ-1 as resolved per the brief.

#### Decision 4: Keep the `parse_state_from_issue` module-level shim untouched
**Options considered:**
- (A) Remove the deprecated function.
- (B) Promote it to a method on `GitHubStateManager` (already exists as `_parse_state_from_issue`).
- (C) Leave it as-is for this change.

**Chosen approach:** (C).

**Rationale:** The shim does not depend on `FEATURE_MARKER`. Removing it expands scope and risks breaking `observer.py:_collect_states`. The TODO comment already documents the intended cleanup separately.

#### Decision 5: `feature_marker` is a plain `str` with Pydantic's default validation only
**Options considered:**
- (A) Add a Pydantic validator for GitHub label rules (length ≤ 50, allowed characters).
- (B) Strip-and-lower normalization.
- (C) No validation; trust GitHub to 422 invalid values at the boundary.

**Chosen approach:** (C).

**Rationale:** GitHub's label rules are simple but mildly opaque (Unicode allowed, but specific control-character rejections). Replicating them in Pydantic risks drift if GitHub changes. A 422 surfaces cleanly in observer logs the first time the marker is applied (during `ensure_labels`), which fails fast at startup. Empty string is the only edge case worth a guard — and Pydantic's default behavior (allowing empty) is acceptable here because the next `ensure_labels` call will fail loudly.

## Implementation Guidance

### Directory / Module Structure
No new files. Modify in place:

| File | Change |
|---|---|
| `agentharness/config.py` | Add `feature_marker: str = "agent"` to `GitHubConfig`. |
| `agentharness/github_labels.py` | Delete `FEATURE_MARKER`. Keep all other constants. |
| `agentharness/github_client.py` | Add `labels: list[str] \| None = None` parameter to `create_pull_request`; add second REST call when labels are non-empty. |
| `agentharness/github_queue.py` | Add `feature_marker` to `__init__` and `from_config`; replace constant references; thread through `ensure_all_queues` (now requires marker). |
| `agentharness/github_state.py` | Add `feature_marker` to `__init__` and `from_config`; replace constant references; pass `[self._feature_marker]` to `create_pull_request` in `open_review`; refactor module-level `_feature_id_from_issue` to not depend on the marker (it doesn't, in fact). |
| `agentharness/observer.py` | Replace `from agentharness.github_labels import FEATURE_MARKER, ...` with reading `config.github.feature_marker`. |
| `agentharness/storage.py` | Pass `config.github.feature_marker` into `GitHubTaskQueue.from_config` and `GitHubStateManager.from_config` (or update `from_config` to read it from `config` itself — see below). |
| `tests/test_github_state.py` | Replace `FEATURE_MARKER` import with a test fixture constant (`TEST_MARKER = "test-marker"`); construct `GitHubStateManager(client, feature_marker=TEST_MARKER)` in fixtures. |
| `tests/test_github_queue.py` | Same pattern; pass marker to constructor. |

### Interfaces and Contracts

```python
# agentharness/config.py
class GitHubConfig(BaseModel):
    token_env: str = "GITHUB_TOKEN"
    owner_env: str = "GITHUB_OWNER"
    runs_repo_env: str = "GITHUB_RUNS_REPO"
    clone_dir: str = ".worktrees"
    feature_marker: str = "agent"   # NEW

# agentharness/github_client.py
async def create_pull_request(
    self,
    title: str,
    body: str,
    head: str,
    base: str,
    labels: list[str] | None = None,
) -> dict: ...

# agentharness/github_queue.py
class GitHubTaskQueue:
    def __init__(
        self,
        client: GitHubClient,
        queue_name: str,
        worker_id: str,
        feature_marker: str,           # NEW (keyword-friendly position)
    ) -> None: ...

    @classmethod
    def from_config(cls, config: Config, queue_name: str) -> GitHubTaskQueue:
        ...
        return cls(
            client=client,
            queue_name=queue_name,
            worker_id=_default_worker_id(),
            feature_marker=config.github.feature_marker,
        )

    @classmethod
    async def ensure_all_queues(
        cls, config: Config, queue_names: list[str]
    ) -> None:
        # already has config; reads config.github.feature_marker internally

# agentharness/github_state.py
class GitHubStateManager:
    def __init__(
        self,
        client: GitHubClient,
        feature_marker: str,           # NEW
    ) -> None: ...

    @classmethod
    def from_config(cls, config: Config) -> GitHubStateManager:
        return cls(
            client=GitHubClient.from_config(config),
            feature_marker=config.github.feature_marker,
        )
```

**Constructor parameter ordering:** I recommend keeping `feature_marker` as the *last* positional parameter (or making it keyword-only via `*` if you want to be defensive). Existing test fixtures that instantiate by position need updating regardless, but adding it at the tail is the smallest diff.

**Factory contract:** `create_task_queue` and `create_state_manager` should *not* read `config.github.feature_marker` themselves — they should defer to the GitHub class's `from_config`, which is already the central place that reads from `Config`. This keeps the read paths consistent with `token`, `owner`, and `runs_repo`.

### Data Flow

**Startup (observer):**
```
load_config() → Config
   └─ Config.github.feature_marker = "agent" (or user value)

observer.observe(config)
   └─ GitHubTaskQueue.ensure_all_queues(config, queue_names)
        └─ ensure_labels([..., config.github.feature_marker, ...])
   └─ create_task_queue(config, q_name)         ← per queue
        └─ GitHubTaskQueue.from_config()
             └─ stores feature_marker on instance
   └─ create_state_manager(config)              ← if needed
        └─ GitHubStateManager.from_config()
             └─ stores feature_marker on instance
   └─ _unified_github_poll: reads config.github.feature_marker for list_issues filter
```

**Send task:**
```
GitHubTaskQueue.send_task(task)
   └─ labels = [self._queue_label, state_label, self._feature_marker]
   └─ client.create_issue(title, body, labels)
```

**Feature completion / open PR:**
```
GitHubStateManager.open_review(feature_id)
   └─ client.create_pull_request(
         title=...,
         body=...,
         head=feature_id,
         base=default_branch,
         labels=[self._feature_marker],     ← NEW
      )
        ├─ POST /pulls         → pr["number"]
        └─ POST /issues/{pr["number"]}/labels  body={"labels": [marker]}
```

## Risks and Mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| In-flight features under existing `"agentharness-feature"` label become invisible after upgrade | HIGH | Document migration in release notes: either rename existing labels in GitHub UI, or set `feature_marker: "agentharness-feature"` in config.json. Resolves OQ-1. |
| `ensure_all_queues` is a classmethod currently called from `observer.observe()`; its signature already takes `config`, so no break — but tests that call it directly may need updating | MEDIUM | Refactor to read `config.github.feature_marker` internally. No external signature change. |
| `parse_state_from_issue` module-level shim could be confused with the new architecture | LOW | Leave it as-is. It only consumes the issue body, never the marker. Add a one-line note if a reviewer asks. |
| Label-application failure after PR is created leaves PR unlabeled | LOW | Per spec FR-7: log and re-raise. `open_review` already swallows exceptions and returns `None`, so a partially-completed PR persists with no orphaned state — manual intervention applies the label idempotently. |
| Two AgentHarness deployments in the same repo with the same marker cross-contaminate | MEDIUM | Out of scope for code, but this is the *exact* problem this feature solves. Release notes should explicitly recommend distinct markers per deployment. |
| Tests construct `GitHubStateManager` / `GitHubTaskQueue` positionally; signature change breaks fixtures | LOW | Update ~20 test sites to pass `feature_marker="agentharness-feature"` (or similar test sentinel). Single grep + edit pass. |
| Pydantic accepts empty string for `feature_marker`, then `ensure_labels` 422s at startup | LOW | Acceptable — fails fast and loudly. Empty value is operator misconfiguration. |
| Brief contains incorrect claim about GitHub PR labels API | RESOLVED | Spec FR-7 already documents the two-call pattern. Implementation must follow the spec, not the brief. |

## Specification Amendments

1. **FR-3 (queue) and FR-4 (state manager):** Make `feature_marker` a **keyword argument** (positional after `*` or trailing) to reduce diff churn in tests. The spec's constructor signatures imply positional; I recommend keyword-friendly placement.

2. **FR-5 (storage factory):** Clarify that `create_task_queue` and `create_state_manager` do **not** read `config.github.feature_marker` directly. They delegate to `GitHubTaskQueue.from_config(config, queue_name)` and `GitHubStateManager.from_config(config)`, which already own the config-reading responsibility. The spec's pseudocode is fine; the architecture detail is "do not duplicate the read."

3. **FR-2 (constant removal):** Note that `GitHubTaskQueue.ensure_all_queues` currently includes `FEATURE_MARKER` in the labels-to-create list. This becomes `config.github.feature_marker` (read inside the classmethod). Tests that call `ensure_all_queues` need a Config fixture, not a constant.

4. **FR-7 (PR labeling):** Lock in the two-call pattern. The brief's claim that PR creation accepts labels natively is incorrect; the spec already calls this out. Implementation MUST use:
   - `POST /repos/{owner}/{repo}/pulls` (no labels in body)
   - then `POST /repos/{owner}/{repo}/issues/{pr_number}/labels` with `{"labels": [...]}` only when `labels` is truthy.

5. **OQ-1 (default value):** Resolved as `"agent"` per the brief. Document the breaking-change migration in release notes; no migration tooling.

6. **OQ-3 (label-application failure):** Resolved as "log + re-raise; do not delete PR." Caller (`open_review`) already wraps in try/except and returns `None`.

7. **OQ-4 (validation):** Resolved as "no upfront validation; rely on GitHub 422." No Pydantic validator added.

8. **OQ-5 (label auto-creation):** Resolved as "rely on `ensure_labels` at startup." This already happens in `GitHubTaskQueue.ensure_all_queues`, which runs before any task is dispatched. Color and description are cosmetic.

9. **New NFR (operator guidance):** Release notes must include:
   - The default change from `agentharness-feature` to `agent`.
   - Recommendation to set distinct markers per deployment in shared orgs.
   - Migration steps for in-flight features (rename label in GitHub UI **or** set `feature_marker: "agentharness-feature"`).

## Prerequisites

- **None blocking.** This is a pure code change with no migrations, no infrastructure work, and no new dependencies.
- **Documentation:** Release notes drafted with the migration steps above. Update `.env.example` and the GitHub-backend section of project README to mention `feature_marker`.
- **Optional config sample:** Add a commented example to `.pipeline/config.json` showing the `github.feature_marker` key, so operators discover it without reading the source.
- **Test fixture audit:** Before starting, grep `FEATURE_MARKER` in `tests/` and replace with a per-test marker constant (e.g., `TEST_FEATURE_MARKER = "test-marker"`) so tests don't accidentally couple to the production default.
```