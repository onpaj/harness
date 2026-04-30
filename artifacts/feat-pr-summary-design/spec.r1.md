# Specification: PR Summary Design

## Summary
Replace the current operational-log style of GitHub PR titles and bodies with a human-readable summary derived from the user's brief and the developer agent's own work narrative. The developer agent produces a free-form `## PR Summary` section that the dispatcher extracts and forwards to the GitHub state manager when opening the feature PR. If any input is missing, the system falls back to the current log-style output.

## Background
At the end of a successful feature pipeline, AgentHarness opens a GitHub PR for the feature branch. Today that PR has:

- A title formatted as `{feature_id}: implementation complete` — opaque to reviewers.
- A body that lists internal phase names with status values, task IDs, and a total token count — useful for debugging the pipeline, useless for understanding what was built.

Reviewers cannot tell at a glance what the feature does, which files were touched, or why specific design decisions were made. The developer agent already has all this context at the moment it finishes its work; the brief already contains a human-authored title. The fix is to surface both, with a graceful fallback to the existing format when artifacts are unavailable.

## Functional Requirements

### FR-1: Developer agent emits a `## PR Summary` section
`.agents/developer.md` gains a new required section in its output format, placed immediately after the existing `## Notes` section. The section header is `## PR Summary`, followed by free-form markdown the developer writes naturally — no schema, no validation. A `### Changes` subsection lists touched files with one-sentence rationales.

**Acceptance criteria:**
- The developer agent prompt instructs the agent to emit a `## PR Summary` section after `## Notes` and before the `## Status:` line.
- The instruction includes a small example showing a free-form summary plus a `### Changes` bulleted list.
- Existing `## Status:` parsing continues to function unchanged.
- A developer output without `## PR Summary` is still accepted by the dispatcher (no error, no retry).

### FR-2: Brief title extraction
`dispatcher.py` exposes a helper `_extract_brief_title(content: str) -> str` that returns a human-readable PR title from `brief.md`.

**Acceptance criteria:**
- If the brief contains a `# Heading` line, the helper returns its text with leading `#` characters and surrounding whitespace stripped.
- If no `#` heading is present, the helper returns the first non-empty stripped line.
- If the brief is empty or only whitespace, the helper returns an empty string and the caller falls back to the default title.

### FR-3: PR summary extraction
`dispatcher.py` exposes a helper `_extract_pr_summary(impl_content: str) -> str | None` that returns the body of the `## PR Summary` section from a developer impl artifact.

**Acceptance criteria:**
- Returns the markdown content from immediately after the `## PR Summary` line up to (but not including) the next line beginning with `## ` or end of file.
- Returns `None` if the section is absent.
- Returns `None` if the section is present but the body is empty or whitespace only.
- Trailing whitespace is stripped; the section's own subheadings (e.g. `### Changes`) are preserved verbatim.

### FR-4: Last developer artifact lookup
`dispatcher.py` exposes a helper `_last_developer_artifact(state: FeatureState) -> str | None` that returns the `output_artifact` path of the most recently completed developer task in the feature state.

**Acceptance criteria:**
- Returns the `output_artifact` of the last `TaskEntry` whose status is `completed` and whose agent is the developer agent (in the order tasks appear in `state.tasks`).
- Returns `None` if no completed developer task exists or none has an `output_artifact` set.

### FR-5: Threading the artifact store through dispatch
The `ArtifactStorage` instance already available in `run_task.py` (line ~128) is threaded into the dispatch chain so the PR-open path can read `brief.md` and the last impl artifact.

**Acceptance criteria:**
- `dispatch_after_completion(...)` accepts an optional `store: ArtifactStorage | None = None` keyword argument and forwards it.
- `_dispatch_serial_next(...)` and `_dispatch_review_result(...)` accept and forward the same parameter.
- `_open_feature_pr(state, state_mgr, store)` receives the store and uses it to download artifacts.
- All existing call sites that do not pass `store` continue to work (the parameter defaults to `None`).
- `run_task.py` passes the in-scope `store` instance when calling `dispatch_after_completion`.

### FR-6: PR-open assembly
`_open_feature_pr` in `dispatcher.py` assembles the title and summary and passes them to the state manager.

**Acceptance criteria:**
- When `store is not None`:
  - Downloads `artifacts/{feature_id}/brief.md` and runs `_extract_brief_title`. If the result is non-empty it is used as the PR title; otherwise the default title is used.
  - Calls `_last_developer_artifact(state)`. If a path is returned, downloads it and runs `_extract_pr_summary`. The result (or `None`) is passed as `pr_summary`.
- When `store is None`, both `pr_title` and `pr_summary` are passed as `None`.
- Any download failure (missing blob, network error, decode error) is caught and treated as if the artifact were absent; no exception propagates out of `_open_feature_pr` for content-extraction failures.
- All PR-content assembly logic stays in `dispatcher.py`; `github_state.py` remains a thin GitHub API wrapper.

### FR-7: `open_review` signature and behaviour
`GitHubStateManager.open_review` accepts optional `pr_title` and `pr_summary` keyword arguments and uses them to produce the final PR.

**Acceptance criteria:**
- New signature:
  ```python
  async def open_review(
      self,
      feature_id: str,
      *,
      pr_title: str | None = None,
      pr_summary: str | None = None,
  ) -> str | None:
  ```
- PR **title**: `pr_title` if provided and non-empty, else `{feature_id}: implementation complete`.
- PR **body**:
  - If `pr_summary` is provided and non-empty: use it as the body, then append `Closes #{N}` (where `{N}` is the feature's tracking issue number) and the token-count footer.
  - If `pr_summary` is `None` or empty: assemble the existing phases/tasks log-style body unchanged.
- Existing positional-arg callers continue to work because both new arguments are optional and keyword-only.

### FR-8: Protocol update
`StateBackend.open_review` in `storage_protocol.py` is updated to declare the new optional kwargs.

**Acceptance criteria:**
- Protocol signature matches `GitHubStateManager.open_review`'s new signature exactly.
- Azure state backend is unaffected at runtime (no Azure `open_review` exists; only the GitHub backend implements it).
- Type checkers do not report new errors at existing call sites.

### FR-9: Graceful fallback
The full system degrades to the current behaviour whenever any required input is missing.

**Acceptance criteria:**
- `store is None` → default title + log-style body.
- `brief.md` missing or empty → default title + (whatever body was assembled from the impl artifact).
- No completed developer task or no `## PR Summary` section in its impl artifact → log-style body (with the brief-derived title still applied if available).
- No errors are raised, no retries are triggered, no warnings interrupt the dispatch flow. Failures are logged at INFO/DEBUG level only.

## Non-Functional Requirements

### NFR-1: Performance
- The PR-open path adds at most two artifact downloads (`brief.md` and the last impl artifact). Both must complete within the existing `_open_feature_pr` timing budget.
- No new agent invocations are introduced (no LLM calls, no extra latency, no extra token cost).
- Helper parsers run in O(n) on input size with n bounded by typical artifact sizes (a few KB to ~100 KB).

### NFR-2: Security
- No new external trust boundaries are introduced. Content originates from the same artifact store that already feeds the pipeline.
- The developer-authored `## PR Summary` is rendered into a GitHub PR body. GitHub already escapes/sandboxes markdown; no additional sanitization is required beyond what `open_review` does today.
- No new secrets, tokens, or permissions are required beyond the existing `GITHUB_TOKEN`.

### NFR-3: Backwards compatibility
- All new function parameters default to a value (`None`) that preserves current behaviour.
- Existing tests pass without modification.
- The Azure backend code path is not touched.
- Already-merged PRs are not migrated; this affects PRs opened after the change ships.

### NFR-4: Observability
- When falling back due to a missing artifact or absent `## PR Summary`, log a single INFO/DEBUG line indicating which fallback was taken (brief missing, impl missing, summary section missing). This aids debugging without polluting normal operation.

## Data Model

No new persistent entities. The existing `FeatureState` and `TaskEntry` models are read-only inputs to the dispatcher helpers. Conceptually the new flow consumes:

| Entity | Source | Purpose |
|--------|--------|---------|
| `brief.md` | `ArtifactStorage` at `artifacts/{feature_id}/brief.md` | Source of human-readable PR title |
| Last developer impl artifact | `ArtifactStorage` at `TaskEntry.output_artifact` | Source of `## PR Summary` section |
| `FeatureState.tasks` | Existing state | Locating the last completed developer task |
| Tracking issue number | Existing state | `Closes #N` link in PR body |
| Token count | Existing state | Footer in PR body |

## API / Interface Design

### Developer agent output (`.agents/developer.md`)

Required output sections in order:
1. Existing sections (implementation summary, tests, etc.)
2. `## Notes`
3. `## PR Summary` *(new)* — free-form markdown describing what was built and why, optionally followed by a `### Changes` bulleted file list.
4. `## Status: <DONE|DONE_WITH_CONCERNS|BLOCKED|NEEDS_CONTEXT>`

### `dispatcher.py` (helpers — module-private)

```python
def _extract_brief_title(content: str) -> str: ...
def _extract_pr_summary(impl_content: str) -> str | None: ...
def _last_developer_artifact(state: FeatureState) -> str | None: ...
```

### `dispatcher.py` (dispatch chain)

```python
async def dispatch_after_completion(
    ..., store: ArtifactStorage | None = None
) -> None: ...

async def _dispatch_serial_next(
    ..., store: ArtifactStorage | None = None
) -> None: ...

async def _dispatch_review_result(
    ..., store: ArtifactStorage | None = None
) -> None: ...

async def _open_feature_pr(
    state: FeatureState,
    state_mgr: StateBackend,
    store: ArtifactStorage | None,
) -> None: ...
```

### `agentharness/github_state.py` and `agentharness/storage_protocol.py`

```python
async def open_review(
    self,
    feature_id: str,
    *,
    pr_title: str | None = None,
    pr_summary: str | None = None,
) -> str | None: ...
```

### `agentharness/run_task.py`

Passes the existing in-scope `store` instance through to `dispatch_after_completion`.

## Dependencies

- Existing `ArtifactStorage` protocol and its GitHub implementation.
- Existing `GitHubStateManager.open_review` and its underlying GitHub PR-creation code path.
- Existing `FeatureState` / `TaskEntry` models.
- No new third-party libraries.
- No new agents.

## Out of Scope

- Per-file diff links in the PR body.
- Adding a dedicated summarizer agent (the goal is zero added latency/cost).
- Any changes to the Azure backend or its tests; `open_review` only exists on the GitHub state manager.
- Migrating already-opened PRs to the new format.
- Validating, linting, or transforming the developer's free-form `## PR Summary` content.
- Localization or templating of the default title or log-style fallback body.

## Open Questions

None.

## Status: COMPLETE