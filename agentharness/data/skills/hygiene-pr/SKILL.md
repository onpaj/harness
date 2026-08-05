---
name: hygiene-pr
description: Bring one PR's branch current with its base branch and confirm CI passes, without touching labels, comments, or review state. Use when the user says "hygiene-pr", "update this PR's branch", "check if PR N is current and green", or asks to fix one PR's staleness/CI without merging or reviewing it.
---

You bring one PR up to date with its base branch and confirm CI is green —
nothing more. You never label, comment, review, or merge. If you can't fix
it, you report why and stop; the caller (a human, `hygiene-all`, or
`automerge-pr`) decides what to do next.

**All deterministic work is done by the script beside this file.**

## 1. Resolve the target PR

If a PR number was given in your invocation, use it. Otherwise, find the
oldest open `agent`-labelled PR by number using the same eligibility query
`automerge-all` uses:

```bash
.claude/skills/automerge-pr/candidates.sh
```

Take the lowest `.number` from `.candidates`. If `candidates` is empty,
print `No agent PRs to check.` and stop.

## 2. Run the check

```bash
.claude/skills/hygiene-pr/update_and_wait.sh --pr {N}
```

This single call does everything: reads the PR's current mergeable/behind/
CI state, updates the branch only if it's actually behind or conflicting,
and polls CI to resolution if needed — all with no side effects beyond that
`gh pr update-branch` call. Parse its JSON output.

## 3. Report

State the PR number and the `status` field verbatim
(`already-clean` / `fixed` / `still-failing` / `conflict` /
`pending-timeout`), plus the `detail` field. That is the entire output of
this skill — no further action.

## Constants

| Constant | Where it lives |
|----------|----------------|
| `HYGIENE_POLL_INTERVAL_SECONDS`, `HYGIENE_POLL_MAX_ATTEMPTS` | `update_and_wait.sh` (env-overridable) |

## Limits worth knowing

The poll window is bounded — a PR whose CI genuinely takes longer than
`HYGIENE_POLL_MAX_ATTEMPTS × HYGIENE_POLL_INTERVAL_SECONDS` reports
`pending-timeout`, not failure. Run this skill again later to re-check.

`conflict` means `gh pr update-branch` could not resolve a real merge
conflict — that needs judgement. This skill does not attempt one; a human
or `/rework-pr` (which does real conflict resolution as part of revising a
PR) is the next step.
