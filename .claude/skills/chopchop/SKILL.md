---
name: chopchop
description: Stop loafing and pick up the next piece of work. Finds the oldest open GitHub issue labelled `agent` that has no PR yet and runs the oneshot pipeline on it. Use when the user says "chopchop", "do some work", "get to work", "next issue", "pick up the next task", or otherwise tells the harness to stop being lazy and ship something.
---

You are the "get off your ass and do work" skill. Your job: find the single
oldest open issue that still needs work, then kick off the `oneshot` pipeline on
it. No feature ID required from the user — you go find the work yourself.

**Hard rule: exactly one issue per invocation, start to finish.** Once you
pick an issue in step 2, you are committed to it for the rest of this run.
You must not, under any circumstances:
- go back to step 1 or re-run the candidate list during this invocation,
- pick up, glance at, or start work on any other issue while this one is
  in flight, even if oneshot's pipeline pauses, hands control back to you
  between phases, or finishes faster than expected,
- treat "oneshot said the pipeline is running autonomously" as permission
  to consider this invocation done and go find more work.

Step 4 does not fire-and-forget oneshot — it drives that issue's entire
pipeline (via the orchestrator agent, through to PR creation and the
`agent-completed` label) inside this same invocation. This invocation's job
ends only when that one issue is fully handled — done, or blocked and
reported to the user. If you want to work on another issue, that is a
**new** `/chopchop` invocation, never a continuation of this one.

## What you do

1. **List candidate issues.** Get all open issues labelled `agent`, oldest
   first, using the `gh` CLI:
```bash
gh issue list --label agent --state open --json number,title,createdAt \
  --limit 200 --search "sort:created-asc"
```
   If the list is empty, tell the user there's nothing to do ("No `agent` issues
   waiting — you're all caught up.") and stop.

2. **Find the oldest one without a PR.** Walk the list from oldest to newest. For
   each issue number `N`, the oneshot pipeline uses a branch named
   `feature/{N}-{slug}`, so check whether any PR's head branch starts with
   `feature/{N}-`:
```bash
gh pr list --state all --json number,headRefName \
  --jq "[.[] | select(.headRefName | startswith(\"feature/${N}-\"))] | length"
```
   - If the result is `0`, this issue has **no PR** — it's your target. Stop
     walking.
   - If the result is `>= 1`, a PR already exists; skip this issue and move to
     the next-oldest.

   If every `agent` issue already has a PR, tell the user there's nothing left to
   start ("Every `agent` issue already has a PR open.") and stop.

3. **Announce the pick.** Print which issue you selected, e.g.
   `Picking up the oldest unstarted issue: #{N} — {title}`.

4. **Run oneshot on it.** Invoke the `oneshot` skill on the selected issue
   number — this drives the full pipeline (worktree on `feature/{N}-{slug}`,
   label lifecycle `agent` → `agent-wip` → `agent-completed`, tests, in-pipeline
   code review, push, and the `agent`-labelled PR):
```
/oneshot {N}
```
   Follow the oneshot skill's instructions end to end; do not duplicate its
   steps here.

## Notes

- Only **one** issue is picked per invocation — the oldest eligible one. Run the
  skill again to grab the next.
- "Oldest" is by issue creation time (`createdAt`), ascending.
- The PR check keys off the `feature/{N}-{slug}` branch convention that
  `oneshot` uses (matched by the `feature/{N}-` prefix). An issue that's
  mid-flight will already have a PR (or be labelled `agent-wip`, which removes
  its `agent` label), so it won't be picked again.
- Step 1's list can still be stale by the time step 4 reaches `oneshot`'s
  own claim (e.g. another `/chopchop` or a direct `/oneshot` invocation
  claimed the same issue in between) — `oneshot`'s SKILL.md step 3 does a
  live-label recheck immediately before claiming and refuses to start a
  second pipeline on an already-claimed issue. If that happens, report it
  to the user and stop; do not fall back to picking a different issue in
  this same invocation.
