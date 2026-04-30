# PR Summary Design

**Date:** 2026-04-30  
**Status:** Approved

## Problem

The final GitHub PR for a completed feature shows only raw operational log data: phase names with status values, internal task IDs, and a token count. There is nothing that tells a reviewer at a glance what was actually built.

## Goal

- PR **title** is human-readable, derived from the user's brief.
- PR **body** contains a meaningful summary: what was implemented, which files changed and why, and key design decisions — written by the developer agent that did the work.

## Design

### 1. Developer agent output format

`.agents/developer.md` gets a new required section added to the output format, placed after `## Notes`:

```markdown
## PR Summary
Brief description of what was implemented and the core rationale.

### Changes
- `path/to/file.py` — what changed and why (one sentence per file)
```

The section is free-form markdown. The developer writes it naturally — no schema to follow. If absent from the output, the PR body falls back gracefully to the current log-style.

### 2. Data flow

`store: ArtifactStorage | None = None` is threaded through the dispatch call chain so `_open_feature_pr` can read artifacts:

```
run_task.py (store already in scope at line 128)
  dispatch_after_completion(..., store=store)
    _dispatch_serial_next(..., store)
    _dispatch_review_result(..., store)
      _open_feature_pr(state, state_mgr, store)
        store.download("artifacts/{id}/brief.md")         → PR title
        store.download(last_dev_task.output_artifact)     → ## PR Summary
        state_mgr.open_review(feature_id, title, summary)
```

`store` is optional (`None`) so the existing Azure path and tests are unaffected.

### 3. `open_review` signature

`github_state.GitHubStateManager.open_review` gains two optional keyword arguments:

```python
async def open_review(
    self, feature_id: str, *, pr_title: str | None = None, pr_summary: str | None = None
) -> str | None:
```

- **PR title**: `pr_title` if provided, else `{feature_id}: implementation complete`.
- **PR body**: `pr_summary` if provided (with `Closes #N` and token-count footer appended), else current phases/tasks log.

`StateBackend` protocol in `storage_protocol.py` is updated with the same optional kwargs.

### 4. Helper parsers (all in `dispatcher.py`)

```python
def _extract_brief_title(content: str) -> str:
    # First `# Heading` stripped of `#`; fallback: first non-empty line

def _extract_pr_summary(impl_content: str) -> str | None:
    # Content from `## PR Summary` to next `##` or EOF; None if absent

def _last_developer_artifact(state: FeatureState) -> str | None:
    # output_artifact of the last completed developer task; None if none
```

All PR-assembly logic lives in `dispatcher.py`; `github_state.py` remains a thin GitHub API wrapper.

## Files changed

| File | Change |
|------|--------|
| `.agents/developer.md` | Add `## PR Summary` to output format spec |
| `agentharness/dispatcher.py` | Add helper parsers, thread `store` param, update `_open_feature_pr` |
| `agentharness/github_state.py` | Update `open_review` to accept `pr_title` / `pr_summary` |
| `agentharness/storage_protocol.py` | Update `StateBackend.open_review` protocol signature |
| `agentharness/run_task.py` | Pass `store` to `dispatch_after_completion` |

## Out of scope

- Per-file diff links in the PR body
- Summarizer agent (no new agent, no extra latency/cost)
- Changes to Azure backend (`open_review` only exists on GitHub state manager)
- Migration of existing features (old PRs keep the log-style body)

## Fallback behaviour

If `store` is `None`, if brief.md is missing, or if the impl artifact has no `## PR Summary` section, `open_review` silently falls back to the existing log-style PR body and the raw feature-ID title. No errors, no retries.