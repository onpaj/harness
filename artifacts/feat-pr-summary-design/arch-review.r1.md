```markdown
# Architecture Review: PR Summary Design

## Architectural Fit Assessment

This feature aligns cleanly with existing patterns. The dispatcher already orchestrates terminal-state side effects (worktree cleanup, PR creation), already parses agent output via `## Status:`-style regexes (`_parse_developer_status`, `_parse_review_result`, `_parse_analyst_status`), and already calls into the `StateBackend` protocol for the PR-open hop. The change keeps PR-content assembly in `dispatcher.py` (where state lives) and keeps `github_state.py` as a thin GitHub wrapper — consistent with how other phase orchestration is split today.

The only real architectural shift is **handing the dispatcher a read-handle to the artifact store**. Today `dispatch_after_completion` only sees `state_mgr` and the queues — it never reads artifacts. The PR-open path is the first place where downstream dispatch needs to read artifact content. This is a small but important new capability and must be threaded through deliberately so it doesn't become a creeping side channel for future agents.

The two main integration points are:
1. **`dispatcher._open_feature_pr`** — currently a 4-line shim at `dispatcher.py:733`; becomes the artifact-reading PR assembly site.
2. **`GitHubStateManager.open_review`** — currently builds the body itself; becomes a renderer that picks between two pre-shaped bodies.

There is a clean separation here: dispatcher decides **what** the PR says; state manager decides **how** to ship it to GitHub. We will preserve and tighten that boundary.

## Proposed Architecture

### Component Overview

```
                run_task.py
                    │
                    │ store: ArtifactStorage (already in scope @ line 128)
                    ▼
        dispatch_after_completion(..., store=store)
                    │
        ┌───────────┴───────────┐
        ▼                       ▼
_dispatch_serial_next   _dispatch_review_result
        │                       │
        └───────────┬───────────┘
                    ▼
        ┌─── _open_feature_pr(state, state_mgr, store) ───┐
        │                                                  │
        │   ┌── _build_pr_content(state, store) ──┐        │
        │   │   • download brief.md   ──► title   │        │
        │   │   • _last_developer_artifact(state) │        │
        │   │   • download impl       ──► summary │        │
        │   │   • return (title?, summary?)       │        │
        │   └──────────────────────────────────────┘       │
        │                    │                              │
        │                    ▼                              │
        │   state_mgr.open_review(                          │
        │     feature_id, pr_title=…, pr_summary=…)         │
        └───────────────────────────────────────────────────┘
                            │
                            ▼
                GitHubStateManager.open_review
                  • body = pr_summary or _build_log_body(state)
                  • title = pr_title or default
                  • create_pull_request(...)
```

### Key Design Decisions

#### Decision 1: Where does PR-content assembly live?
**Options considered:**
- A. Inside `GitHubStateManager.open_review` (pull `store` into `github_state.py`).
- B. Inside `_open_feature_pr` in `dispatcher.py`, passing pre-rendered strings to `open_review`.
- C. New module (`pr_summary.py`).

**Chosen approach:** B — assembly lives in `dispatcher.py`; `open_review` only chooses between two ready-made bodies.

**Rationale:** `github_state.py` is intentionally a thin GitHub API wrapper that knows nothing about artifacts; pulling artifact reads into it would entangle two backends (state + artifacts) that are deliberately decoupled by the protocol layer. The dispatcher already owns "what the next step needs"; this is just one more piece of context it gathers. C is over-engineering for ~60 lines of code that lives in exactly one call site.

#### Decision 2: How is `store` threaded through the dispatch chain?
**Options considered:**
- A. Add `store` parameter to every dispatch helper (spec-suggested).
- B. Build a tiny `DispatchContext` dataclass holding `config`, `queues`, `state_mgr`, `store` and pass that.
- C. Only thread `store` to `_open_feature_pr` directly; bypass `_dispatch_serial_next` / `_dispatch_review_result` plumbing.

**Chosen approach:** A — explicit optional `store: ArtifactStorage | None = None` kwarg on the three functions named in the spec.

**Rationale:** B is the better long-term shape but is out of scope; introducing it now means refactoring six callers and several tests for no spec-required benefit. C is impossible because `_open_feature_pr` is invoked from inside both `_dispatch_serial_next` and `_dispatch_review_result`. The spec explicitly chose A; we honor that.

#### Decision 3: How are artifact-read failures handled?
**Options considered:**
- A. Let any exception bubble — fail the dispatch.
- B. Catch broadly inside `_open_feature_pr`; log INFO and fall back.
- C. Catch narrowly (only HTTP/IO from the store); let parsing errors surface.

**Chosen approach:** B — catch broadly at the assembly boundary, log INFO and fall back to log-style PR content.

**Rationale:** FR-9 mandates graceful fallback — opening a PR is a user-visible terminal step and must never fail because a brief was missing or a developer agent forgot the new section. Narrow catching (C) sounds principled but in practice we'd still need to handle decode errors, surprise YAML in headers, etc. The blast radius of a swallowed parse error is zero (we just fall back); the blast radius of a thrown error is "feature stays in `done` but reviewer never sees a PR." Asymmetric — catch broadly.

#### Decision 4: Should the developer's free-form summary be sanitized?
**Options considered:**
- A. Pass it through verbatim to GitHub.
- B. Length-cap it (e.g. 16 KB) before sending.
- C. Strip HTML / suspicious patterns.

**Chosen approach:** A — pass verbatim. NFR-2 explicitly says no.

**Rationale:** GitHub already sanitizes PR bodies. The content originates from the same trust boundary (developer agent output) that already runs unfiltered into the impl artifact and into reviewer prompts. There is no new attack surface. Length capping risks truncating mid-fence and producing broken markdown for a non-problem; if PR-body length ever becomes a real issue, fix it at that point with awareness of the actual size.

#### Decision 5: Section parser — regex or line-walk?
**Options considered:**
- A. Regex matching `## PR Summary` to next `## ` heading.
- B. Manual line-by-line scanner.

**Chosen approach:** B — a small line-walk helper.

**Rationale:** Multi-line section regexes with non-greedy lookaheads to next-heading are a well-known footgun (interactions with code fences, trailing whitespace, BOMs). A 12-line scanner is clearer, easier to test, and avoids regex pitfalls. Other parsers in `dispatcher.py` (`_parse_developer_status` etc.) match short single-line patterns — different problem class. Use regex where it pays; use a scanner for block extraction.

## Implementation Guidance

### Directory / Module Structure

No new files. All code lands in existing modules:

| File | Change |
|------|--------|
| `.agents/developer.md` | Add `## PR Summary` to required output sections, with a small concrete example. |
| `agentharness/dispatcher.py` | Add `_extract_brief_title`, `_extract_pr_summary`, `_last_developer_artifact`, `_build_pr_content`. Update `dispatch_after_completion`, `_dispatch_serial_next`, `_dispatch_review_result`, `_open_feature_pr` signatures. Drop the now-dead `_build_pr_body` at line 610. |
| `agentharness/github_state.py` | Update `open_review` signature; split body assembly into `_build_log_body` (existing logic) and pick between `pr_summary` / `_build_log_body`. |
| `agentharness/storage_protocol.py` | Update `StateBackend.open_review` protocol signature with the two new keyword-only optional kwargs. |
| `agentharness/run_task.py` | At line 128, pass `store=store` to `dispatch_after_completion`. |
| `tests/test_dispatcher.py` | Add unit tests for the three helpers + a fake-store integration test for `_open_feature_pr`. |
| `tests/test_github_state.py` (new or existing) | Add tests for `open_review` body branching. |

### Interfaces and Contracts

```python
# dispatcher.py — module-private helpers

def _extract_brief_title(content: str) -> str:
    """First '# Heading' stripped, or first non-empty line, or ''."""

def _extract_pr_summary(impl_content: str) -> str | None:
    """Lines after '## PR Summary' until next line starting with '## '
    or EOF; rstrip; return None if absent or whitespace-only."""

def _last_developer_artifact(state: FeatureState) -> str | None:
    """Last TaskEntry where phase == 'developing' and status == completed
    and output_artifact is set; else None."""

async def _build_pr_content(
    state: FeatureState,
    store: ArtifactStorage | None,
) -> tuple[str | None, str | None]:
    """Return (pr_title_or_None, pr_summary_or_None).

    Catches all exceptions internally; logs INFO on each fallback path.
    Never raises."""

async def _open_feature_pr(
    state: FeatureState,
    state_mgr: StateBackend | None,
    store: ArtifactStorage | None = None,
) -> None:
    """Existing shim, extended to pass title/summary."""
```

```python
# storage_protocol.py
class StateBackend(Protocol):
    async def open_review(
        self,
        feature_id: str,
        *,
        pr_title: str | None = None,
        pr_summary: str | None = None,
    ) -> str | None: ...
```

```python
# github_state.py
async def open_review(
    self,
    feature_id: str,
    *,
    pr_title: str | None = None,
    pr_summary: str | None = None,
) -> str | None:
    state = await self.get(feature_id)
    title = pr_title or f"{feature_id}: implementation complete"
    body = self._compose_pr_body(state, pr_summary)
    # remainder unchanged
```

`_compose_pr_body(state, pr_summary)` returns either `pr_summary + closes_line + tokens_footer` or the existing log-style body. The closes line and footer assembly that exist today are factored out so both branches share them. Footer format is unchanged.

### Data Flow

**Happy path (single completed dev task, summary present):**

```
run_task.py:128 ──► dispatch_after_completion(..., store=store)
                       │  status == reviewing, last review PASS, no more pending
                       ▼
                    _dispatch_review_result(..., store=store)
                       │
                       ▼
                    _open_feature_pr(state, state_mgr, store)
                       │
                       ▼
                    _build_pr_content(state, store)
                       │  store.download("artifacts/{id}/brief.md")
                       │      → "# Add PR Summary Design\n..."
                       │  _extract_brief_title  → "Add PR Summary Design"
                       │  _last_developer_artifact(state)
                       │      → "artifacts/{id}/impl/main.r1.md"
                       │  store.download(impl_path)
                       │  _extract_pr_summary  → "Implemented...\n### Changes\n- ..."
                       ▼
                    state_mgr.open_review(
                        feature_id,
                        pr_title="Add PR Summary Design",
                        pr_summary="Implemented...\n### Changes\n- ...",
                    )
                       │
                       ▼
                    GitHub: create PR with humanized title and body
```

**Fallback path (any artifact missing):** `_build_pr_content` catches the exception, logs `INFO`, returns `(None, None)`; `open_review` falls through to the existing log-style body and default title — i.e., bit-for-bit current behavior.

**Mixed path (brief present, summary section absent):** `_build_pr_content` returns `(title, None)`; the GitHub backend uses the title but the **log-style body**. Per FR-9 this is the documented behavior — no synthesized summary.

## Risks and Mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| Developer agent emits malformed markdown that breaks GitHub rendering. | LOW | GitHub renderer is permissive; broken markdown degrades but does not error. No mitigation needed beyond NFR-2's existing posture. |
| `## PR Summary` containing a `## ` line inside a fenced code block ends parsing early. | MEDIUM | Document this in the developer prompt example. Long-term: scanner can track fence state; for v1 we accept the limitation since a normal summary won't contain `## ` inside fences. |
| Developer agent on revision rounds emits a different summary than the original task; we always use the *last* completed task's. | LOW | This is by design — last revision is the freshest. State machine guarantees the last completed dev task reflects the shipped code. |
| `_last_developer_artifact` walks `state.tasks` in arbitrary order. | MEDIUM | `state.tasks` is documented as preserving insertion order; the helper iterates and returns the *latest* matching entry. Add a unit test that locks this ordering invariant. |
| Adding `store` kwarg to dispatch fns breaks pickling of partials in tests. | LOW | All call sites already pass keyword args; default of `None` keeps existing tests green. |
| `open_review` callers that expected positional title/body get surprised. | LOW | Only one production caller exists (`_open_feature_pr`). Keyword-only enforcement (`*`) catches any drift at type-check time. |
| Token-count footer position changes (FR-7 says "append" — appending to summary may look ugly inline with the developer's `### Changes` list). | MEDIUM | Insert a single blank line between the summary body and the `Closes #N` / footer block. Make the separator explicit in `_compose_pr_body`. Add a snapshot test. |
| Exception in `_build_pr_content` is so broad it masks real bugs. | LOW | Use `log.exception` (not `log.info`) on the catch path so stack traces appear in DEBUG/ERROR logs even when we fall back. |

## Specification Amendments

1. **Token-count footer separator.** FR-7 says "append `Closes #N` and the token-count footer." Clarify: the appended block is preceded by a blank line and a horizontal rule (`---`) to visually separate developer-authored content from harness metadata. Body shape:
   ```
   {pr_summary}

   ---

   Closes #{N}

   ### Tokens used
   {tokens_line}
   ```
   This matches the visual rhythm of the existing log-style body.

2. **Helper signature for `_extract_pr_summary`.** Spec says "Returns `None` if the section is present but the body is empty or whitespace only." Add: returns `None` if the body, after stripping, contains *only* the `### Changes` subheading with no list items underneath — an empty changes list is functionally an empty summary.

3. **Logging level.** NFR-4 says INFO/DEBUG. Pin the three fallback paths to **`INFO`** (one line, with feature_id and which fallback was taken) and use **`log.exception`** (which renders at ERROR with stack trace) for unexpected exceptions caught during artifact download/parse — this preserves debuggability without polluting normal output.

4. **Developer prompt example.** FR-1's "small example" should explicitly show: (a) the section header, (b) two short prose paragraphs, (c) a `### Changes` list with 2–3 entries using backticked paths. Concrete examples in agent prompts measurably improve compliance; vague examples don't.

5. **Refactor of duplicated `_build_pr_body`.** The dead helper at `dispatcher.py:610` (currently unused — `open_review` has its own copy at `github_state.py:463`) should be deleted as part of this work. Keeping two copies of the log-style body invites them to drift.

## Prerequisites

None blocking. All inputs are already in place:

- `ArtifactStorage` protocol exposes `download` (used elsewhere).
- `FeatureState.tasks` already records `output_artifact` per `TaskEntry`.
- `state.state_issue_number` and `state.total_tokens_used()` already feed the existing PR body.
- `run_task.py` already constructs `store` before calling `dispatch_after_completion` (`run_task.py:128` is downstream of store creation).
- No GitHub API changes; `create_pull_request` already accepts arbitrary title and body strings.
- No new env vars, no migrations, no infrastructure work.

The only **soft** prerequisite is updating `.agents/developer.md` *before* the dispatcher change ships in the same release — otherwise the first feature run after deploy would have new dispatcher code reading a `## PR Summary` section that the agent prompt doesn't yet instruct the model to produce. Order the commits so prompt and code land together; FR-9's fallback covers any race regardless.
```