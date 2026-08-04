# Design: `/rework` — autonomous revision of `needs-work` PRs

Date: 2026-08-04
Status: approved for planning

## Problem

`/automerge` reviews open `agent` PRs and, when a PR is not confident enough to
merge, posts its review as a comment and labels the PR `needs-work`
(`.claude/skills/automerge/apply_verdict.sh`). `candidates.sh` then excludes
`needs-work` PRs from every future `/automerge` run, by design — so nothing
re-reviews them automatically.

That is correct as far as it goes, but it also means a `needs-work` PR is a
dead end: the review sits there, unread by anyone unless a human happens to
notice it. There is no mechanism that acts on that feedback.

We want a skill that picks up a `needs-work` PR, revises it in place using the
review that rejected it, and pushes a fix — leaving it clean for `/automerge`
to reconsider on its next run.

## Scope

**In scope:** open PRs carrying the `needs-work` label — PRs `/automerge`
itself rejected.

**Out of scope:** PRs in the `comment` band (still open, no `needs-work`
label — those are left for a human by design, see the automerge spec).
Draft PRs, PRs with merge conflicts. A PR that has hit the revision-attempt
cap (see below) is also out of scope — it is reported, not touched.

**Explicitly not doing:** re-running `/automerge` automatically after the
fix. The label is removed and the branch is pushed; the PR becomes an
ordinary candidate again the next time `/automerge` runs, whenever that is.
Chaining the two would couple the skills together for a marginal convenience
and make each harder to reason about alone.

**One PR per invocation.** Like `chopchop`, `/rework` picks the single oldest
eligible `needs-work` PR, revises it, and stops. Run it again for the next
one. This keeps each run's blast radius to one branch and easy to review in
isolation, at the cost of needing repeated invocations to clear a backlog —
the same trade-off `chopchop` already makes for issues.

## Architecture

```
/rework
   |
   |-- 1. find_candidate.sh   ->  the oldest eligible needs-work PR, or none
   |
   |-- 2. worktree setup       ->  check out the PR's existing branch
   |        (../worktrees/feature-{id}-{slug}, oneshot's convention, reused)
   |
   |-- 3. read feedback        ->  gh pr view --comments, gh pr reviews,
   |                               inline review comments
   |
   |-- 4. revise                ->  the invoking session edits the code itself
   |        (no subagent spawn — same session that read the feedback fixes it)
   |
   |-- 5. commit + push         ->  to the PR's existing branch
   |
   `-- 6. finish_revision.sh   ->  remove needs-work, post audit comment,
            (only after a successful push)   clean up the worktree
```

### Deterministic work lives in scripts, not in the prompt

This follows the same split `/automerge` already established: the mechanical,
API-shaped steps (finding the right PR, applying the attempt cap, editing
labels, posting the audit comment) are scripts beside `SKILL.md`; the one step
that genuinely needs judgement — reading a review and fixing the code it
describes — is the only part left to the model.

| Script | Language | Responsibility |
|--------|----------|-----------------|
| `find_candidate.sh` | bash + `gh` + `jq` | List open `needs-work` PRs, apply the revision-attempt cap, emit the oldest eligible candidate and skip reasons as JSON |
| `finish_revision.sh` | bash + `gh` | Remove the `needs-work` label and post the audit comment for one PR; only ever called after a successful push |

### Why the invoking session does the revision itself, not a subagent

`/automerge` spawns a fresh subagent per PR because it is reviewing several
PRs at once and needs to keep their reasoning from bleeding into each other.
`/rework` handles exactly one PR per run, so that isolation problem does not
exist — a subagent would just add a spawn boundary with nothing on the other
side to protect. Reading the feedback and editing the code in the same
context is simpler to reason about and debug, matching how the existing
`/fix-review` command already works.

## Component 1: Candidate selection — `find_candidate.sh`

```bash
.claude/skills/rework/find_candidate.sh
```

```bash
gh pr list --state open --label needs-work --limit 100 \
  --json number,title,createdAt,headRefName,body
```

Repo detection follows the same convention as `automerge/candidates.sh` and
`applicationinsightsscan/gh-api.sh`: parse `origin` directly, override with
`GH_REPO=owner/repo`.

For each PR, oldest (`createdAt`) first:

1. Fetch its comments: `gh api repos/{repo}/issues/{number}/comments
   --jq '[.[].body]'`.
2. Count how many of those bodies match a `verdict:\s*REJECT` line — this is
   exactly the block `automerge/apply_verdict.sh` posts every time it labels
   a PR `needs-work`, so counting it requires no new bookkeeping and ties the
   count directly to actual rejections rather than label-edit events, which
   could come from a human relabeling the PR by hand.
3. If the count is `>= MAX_REVISION_ATTEMPTS`, the PR goes into `skipped`
   with reason `"revision cap reached (N attempts)"` and is never a
   candidate.
4. The first PR (oldest first) under the cap becomes `candidate`. Walking
   stops there — later PRs are neither candidates nor skipped; they are
   simply not considered this run, the same way `chopchop` only reports the
   one issue it picked.

Output:

```json
{
  "candidate": {
    "number": 129,
    "title": "…",
    "headRefName": "feature/118-Add-Widget",
    "attempts": 1,
    "linkedIssue": 118
  },
  "skipped": [
    { "number": 112, "reason": "revision cap reached (3 attempts)" }
  ]
}
```

`candidate` is `null` when there is nothing eligible (empty `needs-work` set,
or every `needs-work` PR is at cap). `linkedIssue` is parsed the same way
`automerge/candidates.sh` already parses it (`Closes #N` in the PR body), for
consistency, though `/rework` does not currently use it for anything beyond
reporting.

`MAX_REVISION_ATTEMPTS = 3` is a constant defined once, at the top of this
file, and nowhere else.

If `candidate` is `null`, print `No needs-work PRs ready to revise.`, list
`skipped` with reasons, and stop.

## Component 2: Worktree setup

Reuses `oneshot`'s naming convention rather than introducing a second one:
branch and worktree are already named `feature/{issue}-{Slug}` by whichever
`oneshot` run originally created this PR.

```bash
WORKTREE="../worktrees/$(echo "$HEAD_REF" | sed 's#/#-#')"
```

- If the worktree directory does not exist, create it from the PR's head
  branch: `git worktree add "$WORKTREE" "$HEAD_REF"`.
- If it already exists (a prior `/rework` run was interrupted, or `oneshot`
  left it behind), reuse it: `git -C "$WORKTREE" fetch origin "$HEAD_REF"`
  then reset it to the fetched tip, rather than failing or creating a
  duplicate.

All edits, commits, and the push happen inside this worktree — never against
the primary checkout.

## Component 3: Reading the feedback

The session gathers the PR's full comment and review history before touching
any code — not just the latest automerge block, so context from earlier
rounds or a human's inline notes is not lost:

```bash
gh pr view {N} --json title,body,comments,reviews
gh api repos/{repo}/pulls/{N}/comments   # inline (diff-anchored) comments
gh pr diff {N}
```

## Component 4: Revising the code

The session reads the feedback gathered in Component 3, identifies the
concrete issues it describes, and fixes them directly in the worktree —
`Read`, `Edit`, `Bash` as needed, same tools any implementation task uses.
This is the one part of `/rework` that is not deterministic and is not
scripted, for the same reason `/automerge`'s scoring step is not scripted:
judging what a review means and how to address it requires the model.

If the feedback is too vague to act on (e.g. only "-25: cannot verify
correctness" with no specific reason), the session should still attempt a
good-faith fix (added tests, clarified the ambiguous logic) rather than
aborting — an unaddressed low-confidence rejection would just cap out on the
next `/automerge` pass anyway.

## Component 5: Commit and push

Stage only the files actually changed (never `git add -A`, matching this
project's git-workflow convention), commit with a message summarizing what
was addressed, and push to the PR's existing branch — never a new branch, so
the fix lands in the same PR rather than opening a second one.

## Component 6: Finishing — `finish_revision.sh`

Called only after the push above succeeds:

```bash
.claude/skills/rework/finish_revision.sh --pr 129 --summary-file /tmp/rework-129-summary.md
```

The summary is written to a file first and posted with `--body-file`, never
interpolated into a shell string — the same discipline `automerge/SKILL.md`
already requires, since PR-derived text must never pass through shell
expansion, and this keeps the pattern uniform even though the summary here is
model-authored rather than PR-derived.

```bash
gh pr comment {N} --body-file "$SUMMARY_FILE"
gh pr edit {N} --remove-label needs-work
```

The comment is posted before the label is removed, so the audit trail exists
even if the label edit then fails. A failure on the label removal is reported
as a script failure (non-zero exit, structured JSON on stdout) — it must
never be silently treated as success, since a PR that is still labelled
`needs-work` after a "successful" run would then get skipped by every future
`/rework` run for the wrong reason.

The worktree is removed on success: `git worktree remove "$WORKTREE"`.

## Error handling

- **Push fails** (branch protection, diverged remote) — report the failure
  and stop before calling `finish_revision.sh`. `needs-work` is only ever
  removed after a confirmed successful push; a failed revision must not look
  resolved.
- **Worktree already exists** — reused via fetch + reset, per Component 2,
  not treated as an error.
- **`gh`/API errors** (rate limit, transient network) — propagate as a script
  failure with the real underlying message; never swallowed.
- **PR closed or merged between `find_candidate.sh` and the push** (raced by
  a human or another run) — detected via `gh pr view --json state` before
  editing; reported as skipped, not pushed to.
- **Every `needs-work` PR at cap** — `candidate` is `null`; `skipped` lists
  every stuck PR with its attempt count, so a human knows exactly what needs
  manual attention, the same transparency `automerge`'s `skipped` list
  already provides.

## Packaging

Same requirement as every skill in this repo:
`tests/test_packaged_skills.py` asserts `agentharness/data/skills/` mirrors
`.claude/skills/` byte-for-byte. `rework/` must be copied into
`agentharness/data/skills/rework/` as real files in the same change, or that
test goes red immediately.

## Constants

| Constant | Value | Defined in |
|----------|-------|------------|
| `MAX_REVISION_ATTEMPTS` | `3` | `find_candidate.sh` |
| `NEEDS_WORK_LABEL` | `needs-work` | `find_candidate.sh`, `finish_revision.sh` (must match `automerge/apply_verdict.sh`'s `NEEDS_WORK_LABEL` — duplicated across standalone scripts for the same reason repo-detection logic already is; keep all three in sync if the label name ever changes) |

## Risks

**No cap on how bad a revision can be.** The session fixing the PR is not
independently reviewed before the label is removed — the next signal is
whatever `/automerge` says on its next run. This is intentional (chaining a
review into this skill was explicitly ruled out of scope, above) but means a
confidently-wrong revision looks identical to a correct one until `/automerge`
runs again.

**The attempt cap counts `automerge` rejections, not `/rework` runs.** A PR
manually re-labelled `needs-work` by a human without ever going through
`/automerge` contributes 0 to the count. This is the correct behavior — the
cap exists to stop an automerge/rework loop, not to limit human intervention
— but it means a human-labelled PR is always eligible regardless of how many
times `/rework` has already tried it by hand-relabeling. Acceptable: this
edge case requires a human to be actively involved already.

**Fully autonomous, no confirmation prompt**, same as `/automerge`. The first
few runs should be watched.

## Testing

`tests/test_rework.py`, structured like `tests/test_automerge.py`:

`find_candidate.sh` (unit, `gh` stubbed by a fake on `PATH` returning canned
JSON):
- a `needs-work` PR with 0 prior `verdict: REJECT` comments → candidate
- a PR with `MAX_REVISION_ATTEMPTS - 1` → still candidate
- a PR with `MAX_REVISION_ATTEMPTS` → skipped, correct reason string
- two eligible PRs, oldest `createdAt` wins as candidate, the other is
  neither candidate nor skipped
- no `needs-work` PRs → `candidate: null`, `skipped: []`
- every `needs-work` PR at cap → `candidate: null`, all in `skipped`

`finish_revision.sh` (unit, `gh` stubbed):
- comment posted, then label removed, in that order
- label-removal failure → non-zero exit, structured JSON, comment still
  confirmed posted (not silently treated as full success)

Coverage target 80% per the repo standard, measured across both scripts.

## Deliverables

1. `.claude/skills/rework/SKILL.md` — orchestration and the revision
   instructions.
2. `.claude/skills/rework/find_candidate.sh`
3. `.claude/skills/rework/finish_revision.sh`
4. `agentharness/data/skills/rework/` — byte-identical copy of the above.
5. `tests/test_rework.py` — per the section above.
6. `CLAUDE.md` — add `/rework` to the Claude Code skills table.
