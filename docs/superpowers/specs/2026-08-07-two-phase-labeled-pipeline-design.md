# Design: split the oneshot pipeline into label-driven `plan-next-issue` / `implement-next-task` stages

Date: 2026-08-07
Status: approved for planning

## Problem

Today's `/oneshot` (invoked directly, or via `/chopchop` on a schedule) drives
the entire pipeline — analyst through PR — inside one long-running Claude
Code session, claimed atomically via `claim_issue.sh`.

Investigating 10 issues in Anela.Heblo stuck on `agent-wip` with no PR found
the root cause: an hourly Orca cron on `hermes` invokes `/chopchop` every
hour with no cap on concurrent invocations. `claim_issue.sh` correctly
prevents two runs claiming the *same* issue, but nothing stops N runs
claiming N *different* issues at once — 7 concurrent
`claude --dangerously-skip-permissions` processes were found running
together on one shared, non-dedicated machine (also running the user's own
interactive Claude Desktop/Orca sessions).

All 10 issues had real work behind them: analyst → architect → designer →
planner reliably completed in every single case (~12 minutes each), but the
developer phase (writing code + running `dotnet build`/`test` against a
large .NET solution) is slow and resource-heavy. Once several sessions pile
up, they contend for the same CPU/build resources — some sessions genuinely
died outright (3 of 10 showed zero file activity in 6 hours) while others
just crawled (6 of 10 still had commits landing within the last couple
hours). Nothing detects or resumes either case: a dead claim sits forever,
and all progress — including code the developer agent already wrote and, in
several cases, already committed locally — lived only in a local worktree on
whichever machine happened to run it, invisible on GitHub until the very
end.

## Scope

**In scope:** replacing the single monolithic `oneshot` session with two
independent, label-driven, short-lived skills — a Planning stage and an
Implementing stage — plus the concurrency and staleness handling that makes
repeated hourly invocations of each safe.

**Out of scope:** rescuing/finishing the 10 issues currently stuck on
`hermes` — one-time operational cleanup, not an architecture change.
Decomposing further than two stages (explicit non-goal for v1 — see *Why
two, not five*).

## Why two, not five

The old (pre-June-2026) architecture had one label state per phase
(`feat:analyzing`, `feat:architecting`, etc.) — decomposed to the finest
grain, then deleted in commit `0cd7aba` in favor of today's single-session
model. This design deliberately starts coarser than that old system:
`analyzing → architecting → designing → planning` has never failed or run
long in any observed run, so splitting it further buys nothing yet. All
observed failure and slowness is downstream of that point.

If the two-stage split turns out to be insufficient — e.g. planning itself
later grows slow or flaky, or the Implementing stage needs finer boundaries
than "one dev task" — decomposing further into more label states is a
natural, additive next step under this same design, not a redesign.

## Architecture

Two short-lived skills, each triggered independently on its own schedule
(retargeting the existing hourly Orca cron), replace `oneshot`'s single
session:

```
plan-next-issue                          implement-next-task
   |                                          |
   |-- pick oldest ready `agent` issue        |-- pick oldest issue in
   |-- claim (extends claim_issue.sh)         |   agent-implementing /
   |-- analyst -> architect -> designer       |   agent-ready-for-dev whose
   |   -> planner (today's orchestrator,      |   branch has no commit in
   |   unchanged)                             |   the last ~10 min
   |-- commit artifacts, push                 |-- claim (label swap only --
   |-- open DRAFT PR                          |   branch already exists)
   |-- label: agent-planning -> ready-for-dev |-- do ONE bounded unit: one
   |-- exit                                   |   dev task + review, OR
                                               |   one code-review round
                                               |-- commit, PUSH
                                               |-- if more work remains:
                                               |   leave label as-is, exit
                                               |   (next poll continues)
                                               |-- if pipeline is done:
                                               |   undraft PR, label:
                                               |   -> agent-completed
                                               |-- exit
```

Both are triggered the same way `oneshot`/`chopchop` are today (an hourly
cron invoking a Claude Code skill), but each run is bounded to a single
small unit of work and always exits promptly — no session is ever the
multi-hour, all-phases-in-one-sitting run that causes today's pileup.

## Label state machine

| Label | Meaning | Set by |
|---|---|---|
| `agent` | Unclaimed, ready for planning | issue creation / arch-review |
| `agent-planning` | Claimed, planning in progress | `plan-next-issue` claim step |
| `agent-ready-for-dev` | Planning done, draft PR open, waiting for implementing work | `plan-next-issue` on exit |
| `agent-implementing` | Implementing claimed; may span many short invocations before finishing | `implement-next-task`'s first invocation on this issue |
| `agent-completed` | PR undrafted, ready for human review | `implement-next-task` on final exit |

Downstream `needs-work`/`automerge-pr`/`rework-pr` semantics are unchanged —
they operate on the PR once it's out of draft, same as today.

## `plan-next-issue`

1. Query oldest open issue carrying `agent` (today's `chopchop` candidate
   logic, unchanged).
2. Claim it — extends `claim_issue.sh`: same atomic branch-ref creation, but
   swaps `agent` → `agent-planning` instead of `agent` → `agent-wip`.
3. Create the worktree, run today's orchestrator phase loop for analyst →
   architect → designer → planner only
   (`agentharness/data/claude-agents/orchestrator.md`'s existing Phase Loop
   section, unchanged — it already commits each artifact as it completes).
4. On `task-plan.r1.md` landing: commit, push the branch.
5. Open a **draft** PR (same body/format `oneshot` uses today, minus the
   code-review section — that doesn't exist yet). Run
   `ensure_pr_linked.sh` for the `agent`/`Closes #N`/title guarantees, same
   as today.
6. Swap `agent-planning` → `agent-ready-for-dev`.
7. Exit.

If this dies mid-phase, the next `plan-next-issue` poll should not treat the
issue as permanently claimed — candidate selection for planning is
therefore "oldest `agent` issue, OR oldest `agent-planning` issue whose
branch has no commit in the last ~10 minutes" (same recency check as
Implementing; see *Concurrency & staleness*).

## `implement-next-task`

1. Candidate selection: oldest issue labelled `agent-ready-for-dev` or
   `agent-implementing`, whose branch has had **no commit in the last ~10
   minutes** (this doubles as both queue-picking and stale-claim detection
   — see below).
2. If first pickup (`agent-ready-for-dev`): swap to `agent-implementing`,
   attach the worktree to the existing branch (`git fetch` + `git worktree
   add --track`, per today's oneshot step 4). If resuming
   (`agent-implementing` already set): just attach the worktree — label
   doesn't change.
3. Read `artifacts/feat-{issue}/state.json` (today's checkpoint format,
   unchanged) to find the next pending unit of work:
   - Next `pending`/`in_progress` dev task → run developer + reviewer for
     **that one task only** (today's orchestrator Developer/Reviewer Task +
     Handling Review Result sections, unchanged logic, but stop after one
     task instead of looping to the next).
   - All tasks `completed`, code-review not yet run or still
     `CHANGES_REQUESTED` under the revision cap → run **one round** of the
     Code Review phase (today's orchestrator logic, unchanged, but stop
     after one round).
   - Code review `CLEAN` (or revisions exhausted) → this is the finishing
     unit: undraft the PR, swap `agent-implementing` → `agent-completed`,
     exit.
4. **Commit and push before exiting, always** — including the actual code
   changes. Today's orchestrator only commits the `artifacts/` subtree
   during the developer/reviewer loop; this design's commit step must also
   stage and commit the developer's real source edits, not just the
   markdown summary, since durability now depends on the *branch*, not the
   worktree surviving.
5. Exit.

Every invocation therefore does at most: one dev-task-plus-review cycle, or
one code-review round, or the finishing step — never more, regardless of how
many tasks the plan has. An issue with 5 dev tasks takes at least 5 polls
(hours, at today's hourly cadence) to finish implementing; that is the
accepted trade-off for "slow but resilient."

## Concurrency & staleness

**Concurrency cap — local, per-stage, at the launcher.** Machine capacity is
a `hermes`-specific concern, not pipeline state, so it is enforced where the
cron actually launches a session, not via GitHub labels: before starting a
new `plan-next-issue` or `implement-next-task` invocation, the launcher
counts currently-running processes matching that stage's own invocation
pattern and skips this cycle if at/over that stage's configured cap. Two
independent counters/limits (e.g. default 2 and 2) — Planning's cap can be
raised more freely since it's cheap (LLM calls only); Implementing's stays
tight since it's the resource-heavy one.

Counting GitHub-labelled issues instead was considered and rejected: once
invocations are bounded to one task each, most issues sitting in
`agent-implementing` at any moment have no worker actively touching them —
they're just backlog waiting their turn. Counting them would block new work
even when `hermes` is idle. What needs capping is simultaneously-running
processes, which is inherently a machine-local fact.

**Staleness — folded into candidate selection, no separate sweep.** Because
a real worker only ever owns one bounded unit of work and pushes before
exiting, "is this issue actively being worked right now" and "is this issue
safe to resume" collapse into the same check: last-commit recency on its
branch. A no-commit window (default ~10 minutes, see *Limits*) is treated as
abandoned/safe-to-retry. No heartbeat, no separate sweep process, no new
label — this is a query against existing state, not new infrastructure.

**Durability principle.** All progress — planning artifacts, per-task code
changes, `state.json` — is committed and **pushed** before an invocation
exits. The remote branch, not any local worktree, is the source of truth for
"how far did this issue get." Any machine polling for work can pick up any
issue at any stage; nothing depends on `hermes` specifically staying alive
or keeping its worktrees.

## Relationship to existing components

- `claim_issue.sh` extends (parameterized target label instead of hardcoded
  `agent-wip`) rather than forks — same atomic-ref-creation mechanism,
  reused for both stages' first-claim step.
- `agentharness/checkpoint.py` / `state.json` format is unchanged — both
  stages read/write the same checkpoint shape `oneshot` uses today.
  `implement-next-task` just stops after one task instead of looping.
- `agentharness/data/claude-agents/orchestrator.md`'s Phase Loop,
  Developer/Reviewer Task, and Code Review phase sections are reused
  near-verbatim; the change is where the *invocation itself* starts and
  stops, not the per-phase logic.
- `oneshot`/`chopchop` are replaced by `plan-next-issue`/`implement-next-task`
  for the automated hourly path. Whether a direct human-invoked
  `/oneshot {issue}` (interactive, single long session, today's behavior)
  stays available as a manual override alongside the two new automated
  skills is a planning-time decision, not fixed here.
- Downstream skills (`automerge-pr`, `rework-pr`, `hygiene-pr`, `absorb`) are
  unaffected — they all operate on PRs already out of draft, which only
  happens at `implement-next-task`'s finishing step.

## Limits worth knowing

- **One task per poll means multi-task issues take multiple hours minimum**,
  at today's hourly cadence — accepted trade-off, not a bug, per the
  explicit "slow but resilient" priority this design optimizes for.
- **The 10-minute no-commit staleness window is a guess, not measured.** A
  dev task whose test suite legitimately runs long (as observed: `dotnet
  test` against the full Anela.Heblo solution) could exceed 10 minutes
  between commits and get wrongly reclaimed, causing duplicate work on the
  same task. This number needs tuning against real task durations during
  rollout — worth instrumenting before trusting it at low values.
- **The local per-stage concurrency cap is machine-specific by design** — if
  implementing work is ever split across multiple machines, each needs its
  own cap tuned to its own capacity; there is no global cap in this design.
- **Draft PRs accumulate stalled state visibly.** An issue whose
  implementing work is slow-but-alive now shows up as a draft PR sitting
  open for hours, which is the intended trade-off (visible on GitHub) but
  means the open-PR list will look busier than before.

## Testing

Same shape as `test_rework_pr.py`-style fake-`gh` stubs: candidate selection
(recency-window edge cases — exactly at the boundary, just under, just
over), the extended `claim_issue.sh`'s parameterized-label claim,
`implement-next-task`'s three branch points (next task / code-review round /
finishing), and the per-invocation "commit real code changes, not just
artifacts" step. `test_packaged_skills.py` extends to cover the two new
skill directories once `.claude/skills/plan-next-issue` and
`.claude/skills/implement-next-task` exist.
