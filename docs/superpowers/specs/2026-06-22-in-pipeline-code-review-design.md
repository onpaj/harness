# In-Pipeline Whole-Branch Code Review

**Date:** 2026-06-22
**Status:** Approved (design)

## Problem

The AgentHarness pipeline has no real review of the **actual code** it writes.

- The per-task `reviewer.md` agent runs with `allowed_tools: []` and only reads the
  developer's *text summary* (`impl/{task}.md`) against the task spec. It never sees
  a diff or a source file — it's a spec-compliance gate, not a code review.
- The only diff-level review is **outsourced to the Claude Code GitHub Action**,
  triggered by an `@claude` marker commit on the opened PR (`oneshot/SKILL.md`), with
  the orchestrator's *Skip-Review Check* deferring to it.

We want the pipeline to review its own code internally, before opening the PR, and to
stop depending on the external `@claude` action.

## Goal

Add a final **whole-branch code-review stage** that runs after all developer tasks
complete and before the PR is opened. It reviews the entire feature diff vs the base
branch — the way the CI action reviews a full PR — and uses its findings to drive a
bounded auto-fix loop. The external `@claude` review is removed.

## Approach (chosen)

- **Scope:** a single final review of `git diff (merge-base master HEAD)...HEAD`
  (option B), not a per-task code review.
- **Disposition:** block + bounded auto-fix loop (option A), reusing the existing
  developer-revision machinery.
- **Criteria:** the `/code-review` skill philosophy (option B) — **correctness bugs**
  plus **reuse / simplification / efficiency** cleanups, high-confidence findings only,
  no style nits.

Finding-to-disposition mapping (falls straight out of the criteria split):

| Bucket | Disposition |
|--------|-------------|
| Correctness bugs | **Blocking** → trigger a developer fix round |
| Reuse / simplification / efficiency cleanups | **Advisory** → recorded + attached to PR, never block |

## Components

### 1. New agent — `agentharness/data/agents/code-reviewer.md`

Distinct from the per-task `reviewer.md`, which is **left unchanged**.

Frontmatter:

```yaml
id: code-reviewer
display_name: "Code Reviewer Agent"
model: claude-sonnet-4-6        # reads real code; needs a strong model
phase: code-review
max_turns: 30
allowed_tools: [bash, read, grep, glob]   # MUST inspect real code, not a summary
output_format: markdown
visibility_timeout: 1800
retry_limit: 2
output_parsing: none            # orchestrator parses the result line itself
```

System prompt embodies the `/code-review` philosophy and emits a parseable result:

```
## Review Result: CLEAN | CHANGES_REQUESTED

### Blocking (correctness)
- `path/to/file.py:42` — <bug + why it is wrong>

### Advisory (cleanup)
- `path/to/file.py:88` — <reuse / simplification / efficiency suggestion>
```

Rules baked into the prompt:
- Report only **high-confidence** findings. When unsure, omit.
- Only **correctness** issues go under *Blocking*. Everything else is *Advisory*.
- `CHANGES_REQUESTED` **iff** there is at least one Blocking finding; otherwise `CLEAN`.
- No style/formatting nits, no speculative "could also" suggestions.
- It receives the diff and may `read`/`grep` the wider tree for context.

### 2. Orchestrator — new **Code Review phase**

Added to `agentharness/data/claude-agents/orchestrator.md`, in the **Completion**
section, after `developing` is marked `completed` and before handoff to PR creation.

Round count `N` is derived from existing `code-review.r{N}.md` artifacts (no new
checkpoint field). Bounded by the checkpoint's existing `max_revisions` (default 3).

Loop:

1. `agentharness checkpoint phase feat-{id} code-review in_progress`.
2. Compute the diff:
   `git diff $(git merge-base master HEAD)...HEAD` (capture to a temp file / pass inline).
3. Spawn the code-reviewer Task: system prompt from `code-reviewer.md` + the diff +
   `spec.r1.md` for intent. Instruct it to write `artifacts/feat-{id}/code-review.r{N}.md`.
4. Commit + hard-verify the artifact (same strict-persistence pattern as every other
   artifact).
5. Parse the `## Review Result:` line.
   - **CLEAN** (or only Advisory): `checkpoint phase feat-{id} code-review completed`.
     Continue to PR.
   - **CHANGES_REQUESTED** and `N < max_revisions`: write a synthetic review-fix task
     context from the Blocking findings, spawn a **developer revision round** against it
     (developer already works in-place on the current branch), commit its work, then
     loop back to step 2 with `N+1`.
   - **CHANGES_REQUESTED** and `N >= max_revisions`: `checkpoint phase feat-{id}
     code-review completed` (do not fail the whole feature), and carry the unresolved
     Blocking findings forward so they are appended to the PR body. Work is never lost.

### 3. Remove the external `@claude` review

- `oneshot/SKILL.md`: drop the `@claude` marker commit (the `--allow-empty … @claude`
  step). The final commit no longer needs a trigger phrase.
- `orchestrator.md`: remove the **Skip-Review Check** (it existed only to defer to the
  CI action; with no `@claude`, the per-task reviewer simply always runs as intended —
  restoring the design's original behavior). Update the impl-artifact commit ordering
  notes that referenced the skip check.
- `oneshot/SKILL.md` PR body: in place of the `@claude` trigger, append the final
  code-review summary — the **Advisory** findings and any unresolved **Blocking**
  findings from `code-review.r{N}.md` — so a human reviewer still sees them on the PR.

### 4. Checkpoint — no code change required

`update_phase` accepts an arbitrary phase string, so `code-review` is a valid phase
with no model/CLI change. `checkpoint status` is unchanged (it returns `complete` once
tasks finish; the orchestrator drives the code-review phase explicitly from there). The
round counter is the `code-review.r{N}.md` file count, bounded by `max_revisions`.

## Artifacts (new)

```
artifacts/feat-{id}/code-review.r{N}.md      # whole-branch review, per round
```

## Data flow

```
developing completed
        │
        ▼
  git diff (merge-base master HEAD)...HEAD
        │
        ▼
  code-reviewer Task ──► code-review.r{N}.md ──► commit
        │
        ├─ CLEAN / advisory-only ───────────────► PR (with advisory notes)
        │
        └─ CHANGES_REQUESTED, N < max ──► developer revision round
                                              │
                                              ▼   (re-diff, N+1)
                                          loop to review
        │
        └─ CHANGES_REQUESTED, N >= max ─► PR (unresolved blocking notes attached)
```

## Error handling

- Review agent produces no/garbled `## Review Result:` line → treat as `CLEAN` is unsafe;
  instead retry the review Task once (`retry_limit: 2`), then on continued failure mark
  the round CLEAN with a recorded warning in the artifact so the pipeline still completes
  (never hard-block the feature on a flaky reviewer).
- Empty diff (no code changed) → skip the review phase, mark `code-review completed`.
- `git merge-base` failure (shallow/unrelated history) → fall back to `git diff master...HEAD`.

## Testing

- **Unit (Python):** the only Python change is potentially a small diff/round helper if
  we add one to the CLI; if the loop stays entirely in the orchestrator markdown, the
  Python surface is unchanged and existing `test_*` suites must still pass. Add a unit
  test for any new helper (e.g. computing the next review round from existing artifacts).
- **Agent-definition test:** assert `code-reviewer.md` parses (valid frontmatter, required
  fields) the same way other agent defs are validated.
- **Orchestrator behavior** is markdown-driven and exercised by a manual end-to-end
  `/oneshot` run on a throwaway issue; document the manual test plan in the PR.

## Out of scope (YAGNI)

- Per-task code review (rejected in favor of B).
- Posting inline PR review comments via the GitHub API (advisory findings go in the PR
  body, not as line comments).
- Configurable effort levels (`low/medium/high`) — fixed at the high-confidence default.
- Changing the per-task `reviewer.md`.
```
