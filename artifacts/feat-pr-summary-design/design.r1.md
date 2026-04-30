Now I have enough context to write the design document.

```markdown
# Design: PR Summary Design

## Component Design

### Overview

Five components change; no new files are introduced. The central change is threading `ArtifactStorage` from `run_task.py` into the dispatch chain so `_open_feature_pr` can read `brief.md` and the last developer impl artifact before handing pre-rendered strings to `GitHubStateManager.open_review`.

```
run_task.py
    └─ dispatch_after_completion(..., store=store)
           ├─ _dispatch_serial_next(..., store=store)
           └─ _dispatch_review_result(..., store=store)
                  └─ _open_feature_pr(state, state_mgr, store)
                         └─ _build_pr_content(state, store) → (title?, summary?)
                                ├─ store.download(brief_path) → _extract_brief_title
                                └─ store.download(impl_path)  → _extract_pr_summary
                         └─ state_mgr.open_review(feature_id, pr_title=…, pr_summary=…)
                                └─ GitHubStateManager: pick body branch, create PR
```

---

### `.agents/developer.md`

**Responsibility change:** instruct the developer agent to emit a `## PR Summary` section in its output artifact.

New required output order:
1. `## What was implemented`
2. `## Files created/modified`
3. `## Tests`
4. `## How to verify`
5. `## Notes`
6. `## PR Summary` *(new)* — free-form markdown describing what was built, why, and a `### Changes` subsection with one-sentence per-file rationale.
7. `## Status: <value>`

The prompt example must be concrete: section header, two prose paragraphs, a `### Changes` bulleted list with 2–3 backtick-fenced paths, then the `## Status:` line.

---

### `agentharness/dispatcher.py`

**Responsibility:** PR-content assembly. Decides what the PR says; delegates rendering to `GitHubStateManager`.

#### New module-private helpers

| Helper | Signature | Contract |
|--------|-----------|----------|
| `_extract_brief_title` | `(content: str) -> str` | First `# Heading` stripped of `#` and whitespace; else first non-empty line; else `""`. Pure, O(n). |
| `_extract_pr_summary` | `(impl_content: str) -> str | None` | Lines after `## PR Summary` up to next `## ` or EOF; rstripped. `None` if absent, whitespace-only, or only an empty `### Changes` subheading. Implemented as a line-walk scanner (not regex) to avoid multi-line lookahead pitfalls with code fences. |
| `_last_developer_artifact` | `(state: FeatureState) -> str | None` | Last `TaskEntry` where `phase == "developing"`, `status == TaskStatus.completed`, and `output_artifact` is not `None`, in `state.tasks` insertion order. Returns `output_artifact` or `None`. |
| `_build_pr_content` | `async (state: FeatureState, store: ArtifactStorage \| None) -> tuple[str \| None, str \| None]` | Downloads and parses both artifacts; catches all exceptions internally; logs `INFO` per fallback path taken, `log.exception` for unexpected errors; never raises. Returns `(pr_title_or_None, pr_summary_or_None)`. |

#### Updated dispatch chain signatures

```python
async def dispatch_after_completion(
    state: FeatureState,
    completed_task: TaskMessage,
    output: str,
    config: Config,
    queues: dict[str, TaskQueue],
    state_mgr: StateBackend | None = None,
    *,
    store: ArtifactStorage | None = None,   # NEW
) -> FeatureState | None: ...

async def _dispatch_serial_next(
    ...,
    store: ArtifactStorage | None = None,   # NEW
) -> FeatureState: ...

async def _dispatch_review_result(
    ...,
    store: ArtifactStorage | None = None,   # NEW
) -> FeatureState: ...

async def _open_feature_pr(
    state: FeatureState,
    state_mgr: StateBackend | None,
    store: ArtifactStorage | None = None,   # NEW
) -> None: ...
```

`_open_feature_pr` calls `_build_pr_content(state, store)` then forwards the result to `state_mgr.open_review`. Existing callers that omit `store` continue to work; the default `None` triggers the graceful-fallback path in `_build_pr_content`.

**Dead code removal:** `_build_pr_body` at line 610 (unused duplicate of the copy in `github_state.py`) is deleted.

---

### `agentharness/github_state.py`

**Responsibility:** GitHub API wrapper. Renders the PR body from pre-shaped inputs; does not read artifacts.

Updated `open_review` picks between two body branches:

```python
async def open_review(
    self,
    feature_id: str,
    *,
    pr_title: str | None = None,
    pr_summary: str | None = None,
) -> str | None: ...
```

Internal body construction is split into two pure helpers:

| Helper | Returns |
|--------|---------|
| `_build_log_body(state)` | Existing phases/tasks/tokens log-style body (factored out of the current inline closure, unchanged content). |
| `_compose_pr_body(state, pr_summary)` | `pr_summary + separator + closes_line + tokens_footer` when `pr_summary` is non-empty; else `_build_log_body(state)`. |

The separator between developer-authored content and harness metadata:
```
\n\n---\n\nCloses #{N}\n\n### Tokens used\n{tokens_line}
```
This matches the visual rhythm of the existing log-style body and prevents the `### Changes` list from running directly into the closes/footer block.

`create_pull_request` receives:
- `title`: `pr_title` if non-empty, else `f"{feature_id}: implementation complete"`
- `body`: `_compose_pr_body(state, pr_summary)`

---

### `agentharness/storage_protocol.py`

Protocol signature updated to match the implementation:

```python
class StateBackend(Protocol):
    async def open_review(
        self,
        feature_id: str,
        *,
        pr_title: str | None = None,
        pr_summary: str | None = None,
    ) -> str | None: ...
```

All other `StateBackend` methods are unchanged. The Azure backend has no `open_review` implementation; this change does not affect it at runtime.

---

### `agentharness/run_task.py`

One-line change at line 128: pass the in-scope `store` instance:

```python
# before
next_state = await dispatch_after_completion(updated_state, task, result.output, config, all_queues, state_mgr)

# after
next_state = await dispatch_after_completion(updated_state, task, result.output, config, all_queues, state_mgr, store=store)
```

`store` is already constructed earlier in `run_task.py` and in scope at this point.

---

## Data Schemas

### Developer agent output (`.agents/developer.md`)

Required sections in emission order:

```markdown
# Implementation: {task name}

## What was implemented
{description}

## Files created/modified
- `path/to/file.py` — {what it contains}

## Tests
{test files and coverage}

## How to verify
{verification steps}

## Notes
{deviations, assumptions, concerns}

## PR Summary
{Free-form markdown: what was built, why, key decisions.}

### Changes
- `agentharness/dispatcher.py` — added three helpers and threaded store through the dispatch chain
- `agentharness/github_state.py` — updated open_review to accept pr_title and pr_summary

## Status: DONE
```

The `## PR Summary` block is bounded by: the preceding `## Notes` line above and the `## Status:` line below. The scanner stops at any line that starts with `## `.

---

### `_extract_brief_title` parsing rules

Input: raw `brief.md` content string.

| Condition | Output |
|-----------|--------|
| Contains a line starting with `# ` | Text after leading `#` characters and surrounding whitespace, from the first such line |
| No `# ` heading | First non-empty stripped line |
| Empty or whitespace-only | `""` (caller uses default title) |

---

### `_extract_pr_summary` parsing rules

Input: raw developer impl artifact string.

Scanner state machine:

```
BEFORE_SECTION → line == "## PR Summary" → IN_SECTION
IN_SECTION → line starts with "## " → DONE (stop collecting)
IN_SECTION → else → append line to buffer
```

Post-processing:
- Join buffer lines, rstrip.
- If result is empty or whitespace-only → `None`.
- If result, stripped, is only a `### Changes` heading with no following list items → `None`.
- Otherwise → return the rstripped string (subheadings like `### Changes` are preserved verbatim).

---

### `_last_developer_artifact` lookup rules

Input: `FeatureState`.

Walk `state.tasks` in insertion order, collect all entries where:
- `phase == "developing"`
- `status == TaskStatus.completed`
- `output_artifact is not None`

Return the `output_artifact` of the **last** such entry, or `None` if none exist. The ordering invariant (`state.tasks` preserves insertion order) is covered by a dedicated unit test.

---

### `_build_pr_content` artifact paths

| Artifact | Path |
|----------|------|
| Brief | `artifacts/{feature_id}/brief.md` |
| Last developer impl | Value of `TaskEntry.output_artifact` for the last completed developer task (already an absolute artifact path, e.g. `artifacts/{feature_id}/impl/{task}.r{N}.md`) |

Both paths are passed directly to `ArtifactStorage.download(path: str) -> str`. Download failures (missing blob, network error, decode error) are caught inside `_build_pr_content`; the corresponding title or summary falls back to `None`.

---

### PR body shapes

**Happy path (`pr_summary` provided):**

```
{pr_summary content, verbatim}

---

Closes #{state_issue_number}

### Tokens used
{total_tokens or "unknown"}
```

**Fallback (`pr_summary` is None or empty):**

```
## Feature: {feature_id}

### Phases
- **{phase}**: {status}
...

### Tasks
- {task_id}: {status}
...

### Tokens used
{total_tokens or "unknown"}

---
*Generated by AgentHarness*

Closes #{state_issue_number}
```

The `Closes #N` line is omitted from both branches when `state.state_issue_number` is `None`.

---

### Fallback matrix

| Condition | `pr_title` | `pr_summary` | PR outcome |
|-----------|-----------|--------------|------------|
| `store is None` | `None` → default | `None` → log body | Current behaviour, bit-for-bit |
| `brief.md` missing or empty | `None` → default | from impl if present | Log-style title + (maybe) summary body |
| No completed developer task | brief title if extracted | `None` → log body | Human title + log body |
| `## PR Summary` absent or empty | brief title if extracted | `None` → log body | Human title + log body |
| All inputs present | brief title | developer summary | Full human-readable PR |

---

### Observability contract

| Event | Log level | Message format |
|-------|-----------|----------------|
| Brief artifact missing or unreadable | `INFO` | `"[{feature_id}] PR title fallback: brief.md not available ({reason})"` |
| Brief heading extraction yields empty string | `INFO` | `"[{feature_id}] PR title fallback: brief.md has no heading or content"` |
| Impl artifact missing or unreadable | `INFO` | `"[{feature_id}] PR summary fallback: impl artifact not available ({reason})"` |
| `## PR Summary` section absent or empty | `INFO` | `"[{feature_id}] PR summary fallback: no ## PR Summary section in impl artifact"` |
| Unexpected exception in `_build_pr_content` | `log.exception` (ERROR + stack trace) | `"[{feature_id}] Unexpected error building PR content; falling back to defaults"` |

---

### Test surface

| Module | New tests |
|--------|-----------|
| `tests/test_dispatcher.py` | `_extract_brief_title`: heading, first-line, empty; `_extract_pr_summary`: present, absent, whitespace-only, empty-changes-only, code-fence with embedded `## `, multi-section; `_last_developer_artifact`: none, single, multiple (ordering invariant); `_build_pr_content`: store=None, brief missing, impl missing, summary absent, all present (using async fake store). |
| `tests/test_github_state.py` | `open_review` body branching: pr_summary provided, pr_summary=None, pr_title provided, pr_title=None, both None (snapshot tests for body shape and separator). |
```