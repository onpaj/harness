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

**Explicitly not doing:** merging `hygiene-pr`'s currency check into
`rework-pr`. `rework-pr` doesn't need it — by the time a PR reaches
`rework-pr`, `automerge-pr` will already have re-checked currency/CI right
before it would have merged, and any CI-failure reason is already in the PR's
comments for `rework-pr` to read.

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
their own PR's branch — there's no shared resource two concurrent runs can
collide on, so both `rework-all` and `hygiene-all` fan out fully in parallel,
start to finish, no barrier.

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

Unchanged from today's `/rework`, parameterized: accept an explicit PR
number and skip the candidate search when given one. No hygiene step added —
see *Explicitly not doing* above.

## `rework-all`

1. Query **all** eligible `needs-work` PRs — today's `find_candidate.sh`
   only returns the single oldest; this needs a sibling script (or a
   `--all` mode) returning the full list, same shape as `candidates.sh`
   (`{candidates: [...], skipped: [...]}`), still enforcing the revision-cap
   filter per PR.
2. Spawn **one subagent per PR, fully in parallel**, each running
   `rework-pr {N}` end to end, including its own commit/push. No
   serialization — independent branches/worktrees.
3. Report: PR, summary of what was changed, skipped list with reasons.

## Shared plumbing

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
| `rework/find_candidate.sh` → `rework-pr/find_candidate.sh` | Moves with the skill; gains a list-all mode (or a new sibling script) returning every eligible `needs-work` PR, not just the oldest, for `rework-all` to call by path |
| `automerge/apply_verdict.sh` → `automerge-pr/apply_verdict.sh` | Moves with the skill; logic unchanged, used identically by standalone `automerge-pr` and by `automerge-all`'s serial-apply step |
| `automerge/parse_verdict.py` → `automerge-pr/parse_verdict.py` | Moves with the skill; unchanged |
| `rework/finish_revision.sh` → `rework-pr/finish_revision.sh` | Moves with the skill; unchanged |

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
- **`rework-all` and `hygiene-all` running at the same time as each other
  (or as `automerge-all`) is not covered by this design** — e.g. `rework-pr`
  revising a PR while `hygiene-pr` is mid-update-branch on the same PR. Out
  of scope for now; treat these as skills a human runs one at a time until a
  real conflict is observed.

## Testing

Same shape as today's `test_automerge.py` / `test_rework.py`: a fake `gh`
stub per script, covering the new hygiene statuses (`already-clean`,
`fixed`, `still-failing`, `conflict`, `pending-timeout`), the
standalone-vs-orchestrated branch in `automerge-pr`, and the new
list-all mode in `rework-all`'s candidate script. `test_packaged_skills.py`
extends to cover the three new skill pairs.
