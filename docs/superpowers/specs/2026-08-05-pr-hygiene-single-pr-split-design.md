# Design: split `/automerge` and `/rework` into single-PR + all-PR skills, add `/hygiene`

Date: 2026-08-05
Status: approved for planning

## Problem

`/automerge` and `/rework` each hard-code one scope: `/automerge` always reviews
every open `agent` PR in one run; `/rework` always picks exactly one (the
oldest eligible `needs-work` PR). Neither can be pointed at a specific PR, and
neither can be composed — there's no way to say "just this one" or "all of
them, using the single-PR logic per PR."

Separately, neither skill ever brings a PR's branch up to date with `main` or
confirms CI is green before acting on it. `/automerge`'s `candidates.sh` only
checks GitHub's `mergeable` flag (no textual conflicts) — a PR can be
`MERGEABLE` and still be behind `main` with stale or still-pending CI, and
`/automerge` will happily review and merge it anyway. There is currently no
skill that walks the open PRs and makes sure they're current and green.

## Scope

**In scope:**
- Split `/automerge` into `automerge-pr` (one PR) and `automerge-all` (fan-out
  over `automerge-pr`).
- Split `/rework` into `rework-pr` (one PR) and `rework-all` (fan-out over
  `rework-pr`).
- A new `hygiene-pr` / `hygiene-all` pair: bring a PR's branch current with
  its base branch and confirm CI passes, called reactively by `automerge-pr`
  and independently runnable as its own sweep.
- Both `-pr` skills accept an optional PR number; omitted, each finds its own
  single best candidate using the same eligibility rule its `-all` sibling
  uses for the full sweep.

**Out of scope:** running the test suite locally (unchanged from today —
"CI passing" means GitHub's own checks, not a local test run). Changing the
review scoring rubric. Changing `rework-pr`'s revision logic.

**Explicitly not doing:** calling `hygiene-pr` from `rework-pr`. The two solve
different currency problems. `hygiene-pr` does *automatic, conflict-free*
updates (`gh pr update-branch`) for PRs `automerge-pr` is about to act on —
it never resolves a real conflict, it reports `conflict` and stops.
`rework-pr` handles the case `hygiene-pr` can't: a PR that's actually
`CONFLICTING` with the default branch needs judgement to resolve, which is
exactly the kind of work `rework-pr` already does for review feedback — see
*Sync with the default branch* below. `rework-pr` gets its own merge step
for this reason, not by delegating to `hygiene-pr`. CI-failure reasons
`automerge-pr` posted are read the same way review feedback is (unchanged
from today).

## Architecture

```
hygiene-pr {N}?          automerge-pr {N}?         rework-pr {N}?
   |                         |                         |
   | (standalone,            | (standalone, applies    | (standalone, applies
   |  reports status)        |  verdict immediately)    |  fix immediately)
   |                         |                          |
   `-- called reactively ----'                          |
       by automerge-pr                                  |
                                                          |
hygiene-all               automerge-all              rework-all
   |                         |                          |
   |-- query all agent PRs  |-- query all agent PRs   |-- query all needs-work
   |-- fan out hygiene-pr   |-- fan out automerge-pr's|    PRs
   |   fully in parallel    |   review, in parallel   |-- fan out rework-pr
   |   (independent          |   (verdict-only mode)   |   fully in parallel
   |    branches, no race)  `-- apply verdicts          |   (independent
                                serially, ascending PR   |    branches, no race)
                                number
```

### Why `automerge-all` still serializes and `rework-all`/`hygiene-all` don't

Two `automerge-pr` runs merging to the same base branch concurrently is the
one place this design has a real race: a merge can invalidate another PR's
mergeability out from under it. `rework-pr` and `hygiene-pr` only ever push to
their own PR's branch — there's no shared resource two *different* PRs'
concurrent runs can collide on, so both `rework-all` and `hygiene-all` fan out
fully in parallel, start to finish, no barrier.

That leaves one more collision: two runs picking up the *same* PR — a
concurrent `rework-all` fan-out re-selecting a PR another run already claimed,
a manually-invoked `rework-pr` racing `rework-all`, or a crashed prior run
leaving no trace. `rework-pr` closes this with a claim, not just candidate
selection — see *Concurrency & conflict handling* below. `hygiene-pr` has no
equivalent claim yet; running `hygiene-all` concurrently with itself or with
`automerge-pr`'s reactive call on the same PR is not covered by this design
(see *Limits*).

## `hygiene-pr {N}` (or bare: oldest PR from `hygiene-all`'s own eligibility query)

1. Resolve target PR (explicit `{N}`, or oldest open `agent` PR by number).
2. Read its mergeable state, whether it's behind the base branch, and its
   check-run status.
3. If it's already not behind and checks are green: no-op. Report
   `already-clean`.
4. If behind or conflicting: `gh pr update-branch`.
5. Poll check-run status until it resolves, bounded by a timeout (see
   *Limits*). Report one of:
   - `fixed` — was stale/red, now current and green.
   - `still-failing` — current with base, but checks are red. A real
     problem, not staleness.
   - `conflict` — `update-branch` could not resolve it (real merge
     conflict). Needs a human, or `rework-pr` once flagged.
   - `pending-timeout` — checks still running when the poll window expired.
     Not a failure — retry later.

`hygiene-pr` never touches labels, comments, or merge state itself — it only
reports what it found and did. Labeling/commenting on a hygiene failure is
`automerge-pr`'s job (see below), because only `automerge-pr` knows whether a
hygiene failure should block a merge.

## `hygiene-all`

1. Query all open `agent` PRs (reuses `automerge`'s `candidates.sh`
   eligibility — draft/already-`needs-work` excluded, since those aren't
   `hygiene-pr`'s problem to fix).
2. Fan out one subagent per PR, fully in parallel, each running `hygiene-pr
   {N}`.
3. Report a table: PR, hygiene outcome. No further action — this skill only
   fixes branch currency and reports CI state, it never labels or merges.

Runnable entirely on its own — a human (or a schedule) can run `hygiene-all`
just to keep the backlog current, independent of whether `/automerge` ever
runs.

## `automerge-pr {N}` (or bare: oldest candidate from `automerge-all`'s query)

1. Resolve target PR.
2. Cheap read of its mergeable state and check-run status (same call
   `hygiene-pr` step 2 makes).
3. If it's already mergeable and checks are green: skip straight to step 4 —
   no call to `hygiene-pr` at all.
4. Otherwise, call `hygiene-pr {N}` and act on its report:
   - `fixed` / `already-clean` → proceed to review (step 5).
   - `still-failing` or `conflict` → **auto-reject**: label `needs-work`,
     post a comment stating the hygiene reason (in a `verdict: REJECT`
     block — see *Shared plumbing* below), skip the review entirely, report,
     stop.
   - `pending-timeout` → report this PR as skipped (`CI pending, retry`),
     stop.
5. Review: same `code-reviewer` subagent and scoring rubric as today's
   `/automerge`, spawned for this one PR.
6. Parse verdict (`parse_verdict.py`, unchanged).
7. Apply verdict — **mode-dependent**:
   - **Standalone** (invoked directly, e.g. `/automerge-pr 142`): apply
     immediately via `apply_verdict.sh`, same as today.
   - **Orchestrated** (spawned by `automerge-all`): stop after producing the
     parsed verdict; emit it (file path) instead of calling
     `apply_verdict.sh`. The parent applies it.
8. Report: PR number, hygiene outcome (`none` / `fixed` / `already-clean`),
   score, verdict, action.

## `automerge-all`

1. Query all eligible candidates (today's `candidates.sh`, extended to carry
   `createdAt` — needed for reporting, ordering stays PR-number-ascending to
   match the existing serial-apply order).
2. Spawn **one subagent per candidate, in parallel**, each told to run
   `automerge-pr {N}` in orchestrated (verdict-only) mode.
3. Collect verdicts (including PRs `automerge-pr` already auto-rejected on
   hygiene grounds — those don't need an apply step, they're already
   labelled).
4. **Apply the remaining verdicts serially**, ascending PR number — the
   no-two-merges-race guarantee, same as today's `/automerge` step 4.
5. Report: full table (PR, hygiene outcome, score, verdict, action) + skipped
   list + any `pending-timeout` PRs + truncation note.

## `rework-pr {N}` (or bare: oldest eligible `needs-work` PR, today's default)

Parameterized like the others (accepts an explicit PR number, skips the
candidate search when given one), plus four fixes to today's `/rework` found
while working through this design:

1. Resolve target PR (explicit `{N}`, or oldest eligible candidate from
   `find_candidate.sh`).
2. Confirm the PR is still `OPEN` (it may have been merged/closed by a human
   between candidate selection and now). If not, report skipped and stop —
   unchanged from today.
3. **Claim it.** Add the `agent-wip` label immediately after confirming
   `OPEN`, before any branch work starts — the same claim convention
   `oneshot`/`workonbug`/`workonepic` already use on issues. Every exit path
   from here on (not-open, unresolved conflict, exhausted push retries,
   success) releases the claim via `gh pr edit {N} --remove-label
   agent-wip`.
4. Check out the PR's branch (today's worktree convention, unchanged).
5. **Sync with the default branch — merge, not rebase.**
   `git merge "origin/$DEFAULT_BRANCH" --no-edit`, resolving any conflicts
   as a judgement call — the same tier as reading review feedback (step 6).
   Rebase was tried first and rejected: these branches are periodically
   synced via merge commits, and replaying their original linear commits
   with `git rebase` manufactures false conflicts on history that a plain
   `git merge` reconciles cleanly (verified directly — `git merge
   origin/$DEFAULT_BRANCH` succeeded with zero conflicts where `git rebase`
   had failed on the same worktree). Resolve `$DEFAULT_BRANCH` via `gh repo
   view --json defaultBranchRef --jq .defaultBranchRef.name` —
   `defaultBranchRefName` is not a valid field. Because merge only adds
   commits and never rewrites history, the push in step 8 stays a plain
   `git push`, no `--force-with-lease`.

   This is why `find_candidate.sh` no longer needs to permanently skip
   `CONFLICTING` PRs (see *Concurrency & conflict handling* below) — a
   genuinely conflicting `needs-work` PR is exactly what this step now
   exists to unstick.
6. Read the feedback — full review history, not just the latest verdict
   block (unchanged from today).
7. Revise the code (unchanged from today).
8. **Commit and push, with retry.** Stage only the changed files, commit,
   push to the PR's branch. If the push is rejected as non-fast-forward
   (something else wrote to the branch mid-run — not necessarily this
   skill; observed in practice when another process pushed commits directly
   to the same branch), fetch and merge the remote's new commits in — same
   judgement rule as step 5 — and retry. Capped at **3 attempts**: beyond
   that, it's not a one-off race anymore — stop, report what landed on the
   branch that this run didn't push, release the `agent-wip` claim, and
   leave `needs-work` in place for a human.
9. Finish: `finish_revision.sh` posts the summary, removes `needs-work`,
   and (new) **releases `agent-wip`**.
10. Report.

## Concurrency & conflict handling (`rework-pr` / `rework-all`)

Two problems found while designing the full-parallel `rework-all` fan-out,
two independent fixes:

**Claim, not just candidate selection.** Candidate selection alone doesn't
stop two runs from picking up the same PR — a concurrent `rework-all`
fan-out, a manually-invoked `rework-pr`, and a crashed prior run all look
identical to a fresh `find_candidate.sh` query. The `agent-wip` label (step 3
above) is a real claim: `find_candidate.sh` (and `rework-all`'s list-all
sibling) skip any PR that already carries it, so a PR mid-revision is
invisible to every other run's candidate search. This is what makes
`rework-all`'s fully-parallel fan-out safe — see the note in *Why
`automerge-all` still serializes...* above.

**Stale search index.** `gh pr list --label needs-work --label agent`
filters via GitHub's search index, which can lag behind live label state for
a short window after a label change — confirmed directly: a PR whose
`needs-work`/`agent` labels had just been removed was still returned as a
search hit, while the same response's live `.labels` field showed `[]`.
`find_candidate.sh` (and `rework-all`'s list-all sibling) re-check each
candidate's live `.labels` field after the search-filtered list returns,
before trusting it. A stale match is recorded in `skipped` with reason
`"stale search match (no longer carries needs-work+agent live)"` rather than
treated as real. The same risk applies to any other `gh pr list --label`
filter in this design (e.g. `automerge-pr/candidates.sh`) — worth watching
for, though not confirmed there and not fixed here.

## `rework-all`

1. Query **all** eligible `needs-work` PRs — today's `find_candidate.sh`
   only returns the single oldest; this needs a sibling script (or a
   `--all` mode) returning the full list, same shape as `candidates.sh`
   (`{candidates: [...], skipped: [...]}`), still enforcing the
   revision-cap filter and the live-label re-check above, and now also
   skipping any PR already carrying `agent-wip` (claimed by another
   in-flight run) rather than skipping `CONFLICTING` PRs permanently.
2. Spawn **one subagent per PR, fully in parallel**, each running
   `rework-pr {N}` end to end, including its own commit/push. No
   serialization — independent branches/worktrees, and the `agent-wip`
   claim prevents any two subagents from converging on the same PR even if
   the candidate list is momentarily stale.
3. Report: PR, summary of what was changed, skipped list with reasons.

## Shared plumbing

**New label: `agent-wip`.** Marks a PR as claimed by an in-progress
`rework-pr` run, following the same claim convention `oneshot` /
`workonbug` / `workonepic` already use on issues. Created best-effort (like
`needs-work` and `agent-merged` already are in `apply_verdict.sh`) the first
time it's needed. Added right after a PR is confirmed `OPEN`, removed on
every exit path.

**CI-failure comment format.** `find_candidate.sh`'s revision-attempt cap
counts PR comments matching `verdict:\s*REJECT`. `automerge-pr`'s
hygiene-triggered auto-reject comment (`still-failing` / `conflict`) must
emit a comment matching that same pattern, or a PR with a permanently broken
build could bounce between `automerge-pr` and `rework-pr` forever without
ever hitting `MAX_REVISION_ATTEMPTS`. The hygiene-reject comment reuses the
existing verdict block shape (`pr:`, `score: 0`, `verdict: REJECT`, `risk:`,
`reasons:`) so both the cap counter and a human reading the PR see one
consistent format for "why is this needs-work," whether the reason was a
code review or a hygiene failure.

**"Oldest" is sibling-consistent, not unified.** `automerge-pr`'s default
uses ascending PR number (matching `automerge-all`'s serial-apply order and
today's behavior). `rework-pr`'s default keeps using `createdAt` (its
current behavior, unchanged). `hygiene-pr`'s default uses ascending PR
number (matching `automerge`'s convention, since it's the same candidate
pool). These are deliberately not unified across families — each already
matches its own sibling's ordering, and forcing one convention onto all
three would change existing behavior for no benefit.

**Packaged mirror.** `agentharness/data/skills/` is a byte-identical copy of
`.claude/skills/`, enforced by `tests/test_packaged_skills.py`. Every new or
renamed skill directory (`hygiene-pr`, `hygiene-all`, `automerge-pr`,
`automerge-all`, `rework-pr`, `rework-all`) needs both copies created and
kept in sync, and the old `automerge/` and `rework/` directories removed from
both trees.

## Script changes

| Script | Change |
|---|---|
| `automerge/candidates.sh` → `automerge-pr/candidates.sh` | Moves with the skill; add `createdAt` and mergeable/check-run fields needed by the cheap hygiene-trigger check. `automerge-all` calls it by path (`.claude/skills/automerge-pr/candidates.sh`), the same way `oneshot` already calls `.claude/skills/oneshot/ensure_pr_linked.sh` — no new shared directory needed. |
| new: `hygiene-pr/update_and_wait.sh` | New — wraps `gh pr update-branch` + bounded `gh pr checks` poll, returns one of the five statuses above. `automerge-pr` calls it by path when it decides to invoke `hygiene-pr`. |
| `rework/find_candidate.sh` → `rework-pr/find_candidate.sh` | Moves with the skill; gains a list-all mode (or a new sibling script) returning every eligible `needs-work` PR, not just the oldest, for `rework-all` to call by path. Also: re-verifies live `.labels` after the search-filtered `gh pr list` result (stale search index), stops permanently skipping `CONFLICTING` PRs (now resolvable via step 5's merge), and skips PRs already carrying `agent-wip` |
| `automerge/apply_verdict.sh` → `automerge-pr/apply_verdict.sh` | Moves with the skill; logic unchanged, used identically by standalone `automerge-pr` and by `automerge-all`'s serial-apply step |
| `automerge/parse_verdict.py` → `automerge-pr/parse_verdict.py` | Moves with the skill; unchanged |
| `rework/finish_revision.sh` → `rework-pr/finish_revision.sh` | Moves with the skill; now also releases the `agent-wip` claim alongside removing `needs-work` |

Exact field names/flags (e.g. which `gh pr view --json` fields drive the
mergeable/behind/check-run read) are an implementation detail for the plan,
not fixed here.

## Limits worth knowing

- **CI poll timeout is a real trade-off.** Too short and slow CI reports
  `pending-timeout` on every run; too long and a `hygiene-all` sweep over N
  PRs ties up N subagents waiting. The exact bound is a planning-time
  decision, not fixed here.
- **`automerge-all`'s parallel-review/serial-apply split means a PR's
  hygiene auto-reject (labelling `needs-work`) happens inside the parallel
  phase, not the serial one** — two PRs could theoretically get labelled
  concurrently. This is fine: labelling different PRs never conflicts the
  way merging to the same base branch does.
- **`rework-pr`'s `agent-wip` claim only protects against other `rework-pr`
  runs.** It does not stop `hygiene-pr` from running `gh pr update-branch`
  on a PR that `rework-pr` currently has checked out, or `automerge-pr` from
  reactively calling `hygiene-pr` on it mid-revision. `hygiene-pr` has no
  claim mechanism in this design. Running `rework-all` concurrently with
  `hygiene-all` or `automerge-all` on overlapping PRs is not covered here;
  treat that combination as a human runs one family at a time until a real
  conflict is observed.
- **Push retries are capped at 3, not unbounded.** A PR under sustained
  concurrent writes from something other than this skill will still end up
  `needs-work` for a human after the third rejected push — this bounds the
  retry loop, it doesn't guarantee eventual success.

## Testing

Same shape as today's `test_automerge.py` / `test_rework.py`: a fake `gh`
stub per script, covering the new hygiene statuses (`already-clean`,
`fixed`, `still-failing`, `conflict`, `pending-timeout`), the
standalone-vs-orchestrated branch in `automerge-pr`, and the new
list-all mode in `rework-all`'s candidate script. `test_packaged_skills.py`
extends to cover the three new skill pairs.

`rework-pr`/`find_candidate.sh` additionally need: `agent-wip` added/removed
on every exit path (not-open, unresolved conflict, exhausted push retries,
success); a PR already carrying `agent-wip` excluded from candidate
selection; the stale-search-index re-check (a search hit whose live
`.labels` no longer contains `needs-work`+`agent` goes to `skipped`, not
`candidate`); merge-not-rebase sync against a fake default branch, including
a case with a reconciling merge commit already in history (rebase would
conflict, merge shouldn't); and the push-retry loop (reject → fetch/merge →
retry, success within 3 attempts, and stop-and-report after 3 failures).
