# PR Hygiene + automerge/rework Single-PR Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split `/automerge` and `/rework` into single-PR (`automerge-pr`, `rework-pr`) and all-PR (`automerge-all`, `rework-all`) skills, and add a new `hygiene-pr`/`hygiene-all` pair that brings a PR's branch current with `main` and confirms CI is green — called reactively by `automerge-pr`, and independently runnable as its own sweep.

**Architecture:** Six Claude Code skills under `.claude/skills/` (mirrored byte-identical into `agentharness/data/skills/`), each a `SKILL.md` plus the deterministic `gh`/`jq` scripts beside it. `automerge-all`/`rework-all` fan out subagents that each run their `-pr` sibling's `SKILL.md` for one PR; `automerge-all` applies verdicts serially afterward (the one real race — two merges to the same base branch), `rework-all`/`hygiene-all` run fully in parallel (independent branches, no shared resource).

**Tech Stack:** Bash + `jq` for deterministic `gh` orchestration (existing project convention — see `automerge/candidates.sh`, `apply_verdict.sh`), Python (`parse_verdict.py`, unchanged) for verdict parsing, pytest for script tests using a fake `gh` on `PATH` (existing convention — see `tests/test_automerge.py`, `tests/test_rework.py`).

## Global Constraints

- Every `gh`-calling script must detect its repo via `git remote get-url origin` when `GH_REPO` is unset, exactly matching the existing pattern duplicated across `candidates.sh` / `apply_verdict.sh` / `find_candidate.sh` / `finish_revision.sh` (parse `github.com[:/]owner/repo`, strip `.git`). Copy this block verbatim into any new script — do not invent a different detection method.
- Scripts never interpolate PR-derived text (title, body, diff, review output) into a shell command. Write it to a file with the **Write tool** first, then reference the file path — the same rule `automerge/SKILL.md` and `rework/SKILL.md` already state.
- `agentharness/data/skills/` must stay byte-identical to `.claude/skills/` (enforced by `tests/test_packaged_skills.py`, which auto-discovers skill directories — no test changes needed there, just keep both trees in sync).
- Constants live in exactly one file each; every SKILL.md's "Constants" table documents where. Do not restate a threshold's numeric value in a second file's comment.
- Do not run the project's linters/formatters over `.sh` files — none are configured for shell in this repo; match existing style (`set -uo pipefail`, `report()`/`fail()` helper pattern) instead.

---

## File Structure

**New:**
- `.claude/skills/hygiene-pr/SKILL.md`
- `.claude/skills/hygiene-pr/update_and_wait.sh`
- `.claude/skills/hygiene-all/SKILL.md`
- `.claude/skills/automerge-all/SKILL.md`
- `.claude/skills/rework-pr/list_candidates.sh`
- `.claude/skills/rework-all/SKILL.md`
- `tests/test_hygiene.py`
- Byte-identical mirrors of all `.claude/skills/{hygiene-pr,hygiene-all,automerge-pr,automerge-all,rework-pr,rework-all}/` under `agentharness/data/skills/`

**Renamed (`git mv`) + modified:**
- `.claude/skills/automerge/` → `.claude/skills/automerge-pr/` (`SKILL.md`, `candidates.sh` modified; `apply_verdict.sh`, `parse_verdict.py` moved unchanged)
- `.claude/skills/rework/` → `.claude/skills/rework-pr/` (`SKILL.md`, `find_candidate.sh` modified; `finish_revision.sh` modified)
- `tests/test_automerge.py` → `tests/test_automerge_pr.py`
- `tests/test_rework.py` → `tests/test_rework_pr.py`

**Deleted:** `.claude/skills/automerge/`, `.claude/skills/rework/`, and their `agentharness/data/skills/` mirrors (superseded by the renamed `-pr` directories).

**Modified:** `CLAUDE.md` (skill table, lines 69-70).

---

## Task 1: Rename `automerge` → `automerge-pr` (mechanical)

**Files:**
- Rename: `.claude/skills/automerge/` → `.claude/skills/automerge-pr/`
- Rename: `tests/test_automerge.py` → `tests/test_automerge_pr.py`

**Interfaces:**
- Produces: `.claude/skills/automerge-pr/{SKILL.md,candidates.sh,apply_verdict.sh,parse_verdict.py}` — same content as today's `automerge/`, path only.

- [ ] **Step 1: Move the directory**

```bash
git mv .claude/skills/automerge .claude/skills/automerge-pr
```

- [ ] **Step 2: Update the test file's path constant and filename**

```bash
git mv tests/test_automerge.py tests/test_automerge_pr.py
```

In `tests/test_automerge_pr.py`, change:

```python
SKILL_DIR = REPO_ROOT / ".claude" / "skills" / "automerge"
```

to:

```python
SKILL_DIR = REPO_ROOT / ".claude" / "skills" / "automerge-pr"
```

- [ ] **Step 3: Run the suite to confirm the rename didn't break anything**

Run: `pytest tests/test_automerge_pr.py -v`
Expected: all tests PASS (same tests, new path, no logic changed yet).

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor: rename automerge skill to automerge-pr"
```

---

## Task 2: Add `createdAt` to `automerge-pr/candidates.sh`

**Files:**
- Modify: `.claude/skills/automerge-pr/candidates.sh`
- Test: `tests/test_automerge_pr.py`

**Interfaces:**
- Produces: `candidates.sh`'s output candidate objects gain a `createdAt` field (ISO 8601 string). Shape otherwise unchanged: `{candidates: [{number, title, additions, changedFiles, linkedIssue, createdAt}], skipped: [...], truncated: N}`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_automerge_pr.py`, in the `_pr()` helper and a new test:

```python
def _pr(number, **overrides):
    base = {
        "number": number, "title": f"PR {number}", "isDraft": False,
        "mergeable": "MERGEABLE", "reviewDecision": "APPROVED",
        "headRefName": f"feature/{number}-Thing", "additions": 10,
        "deletions": 2, "changedFiles": 2, "body": "", "labels": [],
        "createdAt": "2026-08-01T00:00:00Z",
    }
    base.update(overrides)
    return base


def test_candidate_reports_created_at(gh_stub):
    result = gh_stub([_pr(129, createdAt="2026-08-03T12:00:00Z")])

    assert result["candidates"][0]["createdAt"] == "2026-08-03T12:00:00Z"
```

(The existing `_pr()` already exists in the file — this replaces its body to add the `createdAt` default rather than adding a duplicate function.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_automerge_pr.py::test_candidate_reports_created_at -v`
Expected: FAIL — `KeyError: 'createdAt'` or similar, since `candidates.sh` doesn't request or emit the field yet.

- [ ] **Step 3: Update `candidates.sh`**

In `.claude/skills/automerge-pr/candidates.sh`, change the `--json` field list:

```bash
gh pr list \
  --repo "$REPO" \
  --state open \
  --label "$AGENT_LABEL" \
  --limit 100 \
  --json number,title,isDraft,mergeable,reviewDecision,headRefName,additions,deletions,changedFiles,body,labels,createdAt \
```

and the candidate-object projection:

```jq
candidates: ($ok[:$max] | map({number, title, additions, changedFiles, linkedIssue: linked_issue, createdAt})),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_automerge_pr.py -v`
Expected: all PASS, including the new test.

- [ ] **Step 5: Commit**

```bash
git add tests/test_automerge_pr.py .claude/skills/automerge-pr/candidates.sh
git commit -m "feat: add createdAt to automerge-pr candidates.sh output"
```

---

## Task 3: `hygiene-pr/update_and_wait.sh`

**Files:**
- Create: `.claude/skills/hygiene-pr/update_and_wait.sh`
- Test: `tests/test_hygiene.py`

**Interfaces:**
- Produces: `update_and_wait.sh --pr N` → JSON on stdout: `{"pr": N, "status": "already-clean"|"fixed"|"still-failing"|"conflict"|"pending-timeout", "detail": "<string>"}`. Exit code always `0` (this script only reports, never fails the caller — matches `parse_verdict.py`'s "always exit 0" convention for a report-only tool).
- Consumes: `GH_REPO` (optional, same detection fallback as every other script), `HYGIENE_POLL_INTERVAL_SECONDS` (default `15`), `HYGIENE_POLL_MAX_ATTEMPTS` (default `40`) — both overridable so tests run fast.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_hygiene.py`:

```python
"""Tests for the /hygiene-pr skill script."""
import json
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO_ROOT / ".claude" / "skills" / "hygiene-pr"

GH_STUB = """\
#!/usr/bin/env bash
# Fake `gh` for hygiene-pr tests.
#   `pr view` serves canned JSON from $GH_STUB_VIEW_DIR/{1,2,3,...}.json,
#   advancing one file per call and repeating the last file once exhausted.
#   `pr update-branch` succeeds/fails per $GH_STUB_UPDATE_BRANCH_EXIT.
# Every call is recorded to $GH_STUB_LOG for assertions.
echo "$*" >> "$GH_STUB_LOG"
if [ "$1" = "pr" ] && [ "$2" = "view" ]; then
  n=$(( $(cat "$GH_STUB_COUNTER" 2>/dev/null || echo 0) + 1 ))
  echo "$n" > "$GH_STUB_COUNTER"
  max=$(ls "$GH_STUB_VIEW_DIR" | wc -l | tr -d ' ')
  [ "$n" -gt "$max" ] && n="$max"
  cat "$GH_STUB_VIEW_DIR/$n.json"
  exit 0
fi
if [ "$1" = "pr" ] && [ "$2" = "update-branch" ]; then
  if [ "${GH_STUB_UPDATE_BRANCH_EXIT:-0}" = "0" ]; then
    exit 0
  fi
  echo "${GH_STUB_UPDATE_BRANCH_ERR:-simulated update-branch failure}" >&2
  exit 1
fi
exit 1
"""


@pytest.fixture
def hygiene_runner(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "gh"
    stub.write_text(GH_STUB)
    stub.chmod(0o755)

    view_dir = tmp_path / "views"
    view_dir.mkdir()
    log = tmp_path / "gh.log"
    counter = tmp_path / "counter"

    def run(view_sequence, pr=129, update_branch_exit=0, update_branch_err=None,
             max_attempts=5, interval=0):
        for i, payload in enumerate(view_sequence, start=1):
            (view_dir / f"{i}.json").write_text(json.dumps(payload))
        env = {
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "GH_STUB_VIEW_DIR": str(view_dir),
            "GH_STUB_LOG": str(log),
            "GH_STUB_COUNTER": str(counter),
            "GH_STUB_UPDATE_BRANCH_EXIT": str(update_branch_exit),
            "GH_REPO": "onpaj/harness",
            "HYGIENE_POLL_INTERVAL_SECONDS": str(interval),
            "HYGIENE_POLL_MAX_ATTEMPTS": str(max_attempts),
        }
        if update_branch_err:
            env["GH_STUB_UPDATE_BRANCH_ERR"] = update_branch_err
        proc = subprocess.run(
            [str(SKILL_DIR / "update_and_wait.sh"), "--pr", str(pr)],
            capture_output=True, text=True, env=env,
        )
        assert proc.returncode == 0, proc.stderr
        result = json.loads(proc.stdout)
        result["_gh_calls"] = log.read_text().splitlines() if log.exists() else []
        return result

    return run


def _view(mergeable="MERGEABLE", merge_state="CLEAN", checks=None):
    return {
        "mergeable": mergeable,
        "mergeStateStatus": merge_state,
        "statusCheckRollup": checks if checks is not None else [
            {"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "SUCCESS"}
        ],
    }


def test_already_current_and_green_is_already_clean(hygiene_runner):
    result = hygiene_runner([_view()])

    assert result["status"] == "already-clean"
    assert not any("update-branch" in c for c in result["_gh_calls"])


def test_current_but_red_is_still_failing_without_updating(hygiene_runner):
    checks = [{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "FAILURE"}]
    result = hygiene_runner([_view(checks=checks)])

    assert result["status"] == "still-failing"
    assert not any("update-branch" in c for c in result["_gh_calls"])


def test_behind_updates_then_polls_to_success_is_fixed(hygiene_runner):
    pending = [{"__typename": "CheckRun", "status": "IN_PROGRESS", "conclusion": None}]
    success = [{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "SUCCESS"}]
    result = hygiene_runner([
        _view(merge_state="BEHIND", checks=pending),  # initial read: triggers update
        _view(checks=pending),                         # poll attempt 1: still pending
        _view(checks=success),                          # poll attempt 2: green
    ])

    assert result["status"] == "fixed"
    assert any("update-branch" in c for c in result["_gh_calls"])


def test_behind_updates_then_polls_to_failure_is_still_failing(hygiene_runner):
    pending = [{"__typename": "CheckRun", "status": "IN_PROGRESS", "conclusion": None}]
    failure = [{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "FAILURE"}]
    result = hygiene_runner([
        _view(merge_state="BEHIND", checks=pending),
        _view(checks=failure),
    ])

    assert result["status"] == "still-failing"


def test_conflicting_update_branch_failure_is_conflict(hygiene_runner):
    result = hygiene_runner(
        [_view(mergeable="CONFLICTING", merge_state="DIRTY")],
        update_branch_exit=1, update_branch_err="merge conflict",
    )

    assert result["status"] == "conflict"
    assert "merge conflict" in result["detail"]
    # No polling after a failed update — only the one initial view call.
    assert len([c for c in result["_gh_calls"] if c.startswith("pr view")]) == 1


def test_poll_exhausted_is_pending_timeout(hygiene_runner):
    pending = [{"__typename": "CheckRun", "status": "IN_PROGRESS", "conclusion": None}]
    result = hygiene_runner(
        [_view(merge_state="BEHIND", checks=pending)] + [_view(checks=pending)] * 3,
        max_attempts=2,
    )

    assert result["status"] == "pending-timeout"


def test_no_checks_configured_counts_as_clean(hygiene_runner):
    result = hygiene_runner([_view(checks=[])])

    assert result["status"] == "already-clean"


def test_legacy_status_context_is_understood(hygiene_runner):
    result = hygiene_runner([_view(checks=[{"__typename": "StatusContext", "state": "SUCCESS"}])])

    assert result["status"] == "already-clean"


def test_missing_pr_argument_is_rejected():
    proc = subprocess.run(
        [str(SKILL_DIR / "update_and_wait.sh")], capture_output=True, text=True,
    )
    assert proc.returncode == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_hygiene.py -v`
Expected: FAIL — `.claude/skills/hygiene-pr/update_and_wait.sh` does not exist yet.

- [ ] **Step 3: Write the script**

Create `.claude/skills/hygiene-pr/SKILL.md`'s directory first (`mkdir -p .claude/skills/hygiene-pr`), then create `.claude/skills/hygiene-pr/update_and_wait.sh`:

```bash
#!/usr/bin/env bash
# Bring one PR's branch current with its base branch and wait for CI to
# resolve. Never touches labels, comments, or merge state — only reads, and
# if needed, runs `gh pr update-branch`.
#
#   update_and_wait.sh --pr N
#
# Emits JSON: {"pr": N, "status": "already-clean|fixed|still-failing|
#              conflict|pending-timeout", "detail": "..."}
# Always exits 0 — this script reports, it never fails the caller.
set -uo pipefail

POLL_INTERVAL_SECONDS="${HYGIENE_POLL_INTERVAL_SECONDS:-15}"
POLL_MAX_ATTEMPTS="${HYGIENE_POLL_MAX_ATTEMPTS:-40}"

PR=""
while [ $# -gt 0 ]; do
  case "$1" in
    --pr) PR="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 1 ;;
  esac
done

[ -n "$PR" ] || { echo "--pr is required" >&2; exit 1; }

report() {  # status, detail
  jq -n --argjson pr "$PR" --arg status "$1" --arg detail "$2" \
    '{pr: $pr, status: $status, detail: $detail}'
}

REPO="${GH_REPO:-}"
if [ -z "$REPO" ]; then
  # Same convention as automerge-pr/candidates.sh's detect_repo().
  url=$(git remote get-url origin 2>/dev/null) || { echo "cannot detect repo: no origin remote" >&2; exit 1; }
  case "$url" in
    *github.com*) ;;
    *) echo "cannot detect repo: origin is not a github.com remote" >&2; exit 1 ;;
  esac
  REPO="${url#*github.com[:/]}"
  REPO="${REPO%.git}"
  REPO="${REPO%/}"
  if [ -z "$REPO" ] || [[ "$REPO" != */* ]]; then
    echo "cannot detect repo: could not parse origin URL" >&2; exit 1
  fi
fi

# Normalizes statusCheckRollup (a mix of CheckRun and legacy StatusContext
# objects) into one overall state: "success" | "failure" | "pending" | "none".
CI_STATE_FILTER='
  def check_state:
    if .__typename == "StatusContext" then
      (if .state == "SUCCESS" then "success"
       elif .state == "PENDING" then "pending"
       else "failure" end)
    else
      (if .status != "COMPLETED" then "pending"
       elif (.conclusion == "SUCCESS" or .conclusion == "NEUTRAL" or .conclusion == "SKIPPED") then "success"
       else "failure" end)
    end;
  def ci_state:
    if length == 0 then "none"
    else (map(check_state)) as $s
      | if ($s | any(. == "failure")) then "failure"
        elif ($s | any(. == "pending")) then "pending"
        else "success" end
    end;
'

read_state() {
  gh pr view "$PR" --repo "$REPO" \
    --json mergeable,mergeStateStatus,statusCheckRollup \
  | jq -r "$CI_STATE_FILTER"' [.mergeable, .mergeStateStatus, (.statusCheckRollup | ci_state)] | @tsv'
}

IFS=$'\t' read -r mergeable merge_state ci_state < <(read_state)

is_behind=false
[ "$merge_state" = "BEHIND" ] && is_behind=true
is_conflicting=false
[ "$mergeable" = "CONFLICTING" ] && is_conflicting=true

if ! $is_behind && ! $is_conflicting; then
  case "$ci_state" in
    success|none)
      report "already-clean" "branch is current, checks are $ci_state"; exit 0 ;;
    failure)
      report "still-failing" "branch is current with base, but checks are failing"; exit 0 ;;
    pending)
      : # already current — fall through to the poll loop without updating
      ;;
  esac
else
  if ! update_err=$(gh pr update-branch "$PR" --repo "$REPO" 2>&1); then
    report "conflict" "gh pr update-branch failed: $update_err"; exit 0
  fi
fi

attempt=0
while [ "$attempt" -lt "$POLL_MAX_ATTEMPTS" ]; do
  IFS=$'\t' read -r mergeable merge_state ci_state < <(read_state)
  case "$ci_state" in
    success|none)
      report "fixed" "branch updated/current, checks are $ci_state"; exit 0 ;;
    failure)
      report "still-failing" "branch is current with base, but checks are failing"; exit 0 ;;
  esac
  attempt=$((attempt + 1))
  [ "$attempt" -lt "$POLL_MAX_ATTEMPTS" ] && sleep "$POLL_INTERVAL_SECONDS"
done

report "pending-timeout" "checks still running after $POLL_MAX_ATTEMPTS polls"
```

```bash
chmod +x .claude/skills/hygiene-pr/update_and_wait.sh
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_hygiene.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_hygiene.py .claude/skills/hygiene-pr/update_and_wait.sh
git commit -m "feat: add hygiene-pr/update_and_wait.sh"
```

---

## Task 4: `hygiene-pr/SKILL.md`

**Files:**
- Create: `.claude/skills/hygiene-pr/SKILL.md`

**Interfaces:**
- Consumes: `update_and_wait.sh` from Task 3.
- Produces: the `/hygiene-pr` skill, invoked standalone or by `hygiene-all`/`automerge-pr`.

- [ ] **Step 1: Write the SKILL.md**

```markdown
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
```

- [ ] **Step 2: Verify frontmatter parses and the file is well-formed**

Run: `python3 -c "import re,sys; t=open('.claude/skills/hygiene-pr/SKILL.md').read(); assert t.startswith('---\nname: hygiene-pr'), 'frontmatter missing'"`
Expected: no output (assertion passes).

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/hygiene-pr/SKILL.md
git commit -m "feat: add hygiene-pr SKILL.md"
```

---

## Task 5: `hygiene-all/SKILL.md`

**Files:**
- Create: `.claude/skills/hygiene-all/SKILL.md`

**Interfaces:**
- Consumes: `.claude/skills/automerge-pr/candidates.sh` (Task 2, for the eligible-PR query) and the `hygiene-pr` skill (Task 4, fanned out per PR).

- [ ] **Step 1: Write the SKILL.md**

```markdown
---
name: hygiene-all
description: Sweep every open agent PR, bringing each current with its base branch and confirming CI passes, without merging or reviewing any of them. Use when the user says "hygiene-all", "clean up the PR backlog's branches", "check CI across all open PRs", or wants the backlog kept current independent of /automerge-all ever running.
---

You keep the whole open-PR backlog current with its base branch and confirm
CI status across all of it — independent of review or merge decisions. This
is safe to run on its own schedule; it never labels, comments, or merges
anything.

## 1. Find the candidates

```bash
.claude/skills/automerge-pr/candidates.sh
```

This is the same eligibility query `/automerge-all` uses (draft, conflicted-
in-the-textual sense via `mergeable`, and already-`needs-work` PRs are
filtered — those aren't this skill's problem to fix). If `candidates` is
empty, print `No agent PRs to check.`, list `skipped` with reasons, and
stop.

## 2. Check each candidate — one subagent per PR, fully in parallel

Spawn **one subagent per candidate PR, all in a single message**, so they
run concurrently — there is no shared resource two `hygiene-pr` runs on
different PRs can collide on. Give each subagent exactly this prompt, with
`{N}` replaced by the PR number:

> Follow `.claude/skills/hygiene-pr/SKILL.md` for PR #{N} in this
> repository. Skip its step 1 (you already have the PR number). Run its
> step 2 and report its step 3's output exactly: the PR number, the
> `status` field, and the `detail` field, as your entire final message —
> nothing else.

## 3. Report

Print a table of every PR: number, status, detail. Then list the `skipped`
entries from step 1 with their reasons.
```

- [ ] **Step 2: Verify frontmatter is well-formed**

Run: `python3 -c "t=open('.claude/skills/hygiene-all/SKILL.md').read(); assert t.startswith('---\nname: hygiene-all')"`
Expected: no output.

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/hygiene-all/SKILL.md
git commit -m "feat: add hygiene-all SKILL.md"
```

---

## Task 6: `automerge-pr/SKILL.md` — hygiene integration + PR-number parameter + orchestrated mode

**Files:**
- Modify: `.claude/skills/automerge-pr/SKILL.md`

**Interfaces:**
- Consumes: `hygiene-pr` skill (Task 4), `automerge-pr/candidates.sh` (Task 2), `automerge-pr/apply_verdict.sh`, `automerge-pr/parse_verdict.py` (unchanged from today).
- Produces: the `/automerge-pr` skill — standalone (applies its own verdict) and orchestrated (called by `automerge-all`, emits a verdict file instead).

- [ ] **Step 1: Rewrite `.claude/skills/automerge-pr/SKILL.md`**

Replace the whole file with:

```markdown
---
name: automerge-pr
description: Review one PR — bringing it current with main and confirming CI first — and merge it if the review is confident, comment if not, or flag needs-work if it can't even be reviewed. Use when the user says "automerge-pr", "review and merge PR N", "check if PR N is ready to merge", or gives a specific PR number to clear.
---

You take one PR from "open" to a decision: merged, commented-and-left-open,
or flagged `needs-work` — after first making sure it's actually current
with `main` and its CI is green. Called directly for one PR, or by
`/automerge-all` as part of a full-backlog sweep.

**All deterministic work is done by the scripts beside this file.** Do not
re-implement their logic, re-derive the score thresholds, or hand-write
`gh` commands they already own. Your only judgement call is the review
itself.

## 1. Resolve the target PR

If a PR number was given in your invocation, use it as `{N}`. Otherwise,
find the oldest (lowest-numbered) open `agent` PR:

```bash
.claude/skills/automerge-pr/candidates.sh
```

Take the lowest `.number` from `.candidates`. If `candidates` is empty,
print `No agent PRs ready to review.`, list `skipped` with reasons, and
stop.

## 2. Bring it current and confirm CI — always call `hygiene-pr`

```bash
.claude/skills/hygiene-pr/update_and_wait.sh --pr {N}
```

This single call is cheap when there's nothing to do: if the branch is
already current and checks are green, it reports `already-clean`
immediately with no `gh pr update-branch` call and no polling. There is no
separate "is it already fine" check to do yourself — this call *is* that
check, plus the fix, in one step.

Branch on its `status`:

- **`already-clean` or `fixed`** → continue to step 3 (review).
- **`still-failing` or `conflict`** → **auto-reject, skip the review
  entirely.** Write this block to `/tmp/automerge-hygiene-{N}.md` using the
  **Write tool**:

  ```
  Hygiene check failed for this PR before code review.

  pr: {N}
  score: 0
  verdict: REJECT
  risk: high
  reasons:
    - {hygiene status}: {hygiene detail, verbatim from update_and_wait.sh}
  concerns: needs a human, or /rework-pr once flagged, to resolve
  ```

  Then apply it:

  ```bash
  .claude/skills/automerge-pr/apply_verdict.sh \
    --pr {N} --action needs-work --review-file /tmp/automerge-hygiene-{N}.md
  ```

  Report this PR (number, hygiene status, action: `needs-work`) and stop —
  do not proceed to step 3 for this PR. This block matches the same
  `verdict: REJECT` shape a code-review rejection produces, so
  `rework-pr/find_candidate.sh`'s revision-attempt cap counts it the same
  way.
- **`pending-timeout`** → report this PR as skipped
  (`CI checks pending, retry later`) and stop.

## 3. Review

Spawn **one `code-reviewer` subagent** with exactly this prompt, `{N}`
replaced by the PR number:

> Review pull request #{N} in this repository and score how confident you are
> that it can be merged to `master` with no human looking at it.
>
> You are READ-ONLY. You must not run `gh pr merge`, `gh pr close`,
> `gh pr edit`, `git push`, or any other state-changing command. Gather context
> with:
> - `gh pr view {N} --json title,body,headRefName,additions,deletions,changedFiles`
> - `gh pr diff {N}`
> - `gh issue view <issue> --json title,body` for the issue the PR body links
> - `Read` and `Grep` on the repo, to check the change fits the code around it
>
> You cannot run the test suite, and you must not assume the code works because
> it looks plausible.
>
> Start from 100 and deduct:
> - -40 the diff does something the linked issue did not ask for
> - -30 no linked issue found in the PR body
> - -25 new behaviour added with no accompanying test
> - -30 touches concurrency-critical code (`state_manager.py`, blob-lease or claim logic)
> - -30 touches auth, secrets handling, or `.github/workflows/`
> - -100 hardcoded secret, credential, or leftover debug statement
> - -20 diff exceeds 400 added lines or 10 changed files
> - -50 the PR description claims work the diff does not contain
> - -25 anything whose correctness you cannot verify from the diff alone
>
> That last one is not optional. If you cannot tell whether the change is
> correct, that is low confidence and the score must show it. Do not round up
> toward a merge because the change looks tidy.
>
> End your output with exactly this block and nothing after it:
>
> ```
> pr: {N}
> score: <0-100 integer>
> verdict: <MERGE if score >= 80, COMMENT if 40-79, REJECT if < 40>
> risk: <low|medium|high>
> reasons:
>   - <specific fact about this diff>
>   - <specific fact about this diff>
> concerns: <none, or what a human should look at>
> ```
>
> Each reason must be a specific fact about this diff. "Code looks good" is not
> a reason.

## 4. Parse the verdict

Write the subagent's full output to `/tmp/automerge-review-{N}.md` using the
**Write tool** — never interpolate a subagent's output into a shell command.
Then:

```bash
.claude/skills/automerge-pr/parse_verdict.py < /tmp/automerge-review-{N}.md
```

A malformed or self-contradictory review comes back `"valid": false` with
`"action": "comment"` — that is correct and final. **Never override it into
a merge.**

## 5. Apply the verdict

Determine your mode from your invocation prompt:

- **Standalone** (no explicit instruction to withhold the merge): apply
  immediately.

  ```bash
  .claude/skills/automerge-pr/apply_verdict.sh \
    --pr {N} --action {action} --review-file /tmp/automerge-review-{N}.md --issue {issue}
  ```

  Use the `linkedIssue` field from step 1's candidate object (or the
  `linkedIssue` the caller gave you if invoked with an explicit PR number
  and no candidates.sh lookup was needed — fetch it via
  `gh pr view {N} --json body` and the same `Closes #(\d+)` pattern
  `candidates.sh` uses, if you don't already have it). Pass `--issue` when
  non-null, omit it when null.

- **Orchestrated** (your invocation explicitly says "ORCHESTRATED MODE" —
  this is how `/automerge-all` calls you): do **not** call
  `apply_verdict.sh`. Instead write the parsed verdict JSON from step 4 to
  the path your invocation specifies (or `/tmp/automerge-verdict-{N}.json`
  if none given) using the **Write tool**, and end your entire output with
  exactly one line: `VERDICT_FILE: {that path}`.

## 6. Report

State: PR number, hygiene outcome (`none` if step 2 wasn't reached because
you took an explicit-PR-number fast path — this should not happen, step 2
always runs — otherwise the `status` from step 2), score, verdict, action
taken (or `deferred to caller` in orchestrated mode).

## Constants

Do not restate these values elsewhere; each lives in exactly one file.

| Constant | Where it lives |
|----------|----------------|
| `MERGE_THRESHOLD`, `NEEDS_WORK_THRESHOLD` | `parse_verdict.py` |
| `MAX_CANDIDATES`, `AGENT_LABEL` | `candidates.sh` |
| `MERGED_ISSUE_LABEL`, `NEEDS_WORK_LABEL` | `apply_verdict.sh` |
| `HYGIENE_POLL_INTERVAL_SECONDS`, `HYGIENE_POLL_MAX_ATTEMPTS` | `hygiene-pr/update_and_wait.sh` |

## Limits worth knowing

This skill merges without running the test suite beyond whatever CI already
ran — every score comes from reading a diff, and CI passing only means
GitHub's own checks were green, not that this skill re-verified them
locally. It is deliberately conservative (a high merge threshold defined
once in `parse_verdict.py`, uncertainty costs score), but it can merge a
change that reads correctly and is not. There is also no confirmation
prompt. Watch the first few runs.

The reviewer subagent's READ-ONLY instruction is a prompt constraint, not an
enforced sandbox — it currently has Bash access and the same `gh`
credentials as this skill. A subagent that follows a malicious instruction
embedded in a PR's diff or title could act independently of the score it
reports. Until a Bash-less or credential-scoped reviewer ships, treat every
merge this skill performs as something a compromised or confused subagent
could have influenced beyond its stated score.

A PR that lands in the `comment` band gets a fresh review comment every time
this skill runs against it, until it's merged or manually labelled
`needs-work` — there's no dedup on repeated runs yet.

`hygiene-pr` only resolves conflicts it can fast-forward/merge cleanly. A
genuinely `CONFLICTING` PR reports `conflict` here and gets flagged
`needs-work` without ever reaching review — `/rework-pr` is what actually
resolves real conflicts.
```

- [ ] **Step 2: Verify the reviewer prompt's thresholds still match `parse_verdict.py`**

Run: `pytest tests/test_automerge_pr.py::test_skill_md_prompt_thresholds_match_parser_constants -v`
Expected: PASS (the prompt block above is copied verbatim from today's file, so the existing drift guard still holds).

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/automerge-pr/SKILL.md
git commit -m "feat: wire hygiene-pr into automerge-pr, add PR-number param and orchestrated mode"
```

---

## Task 7: `automerge-all/SKILL.md`

**Files:**
- Create: `.claude/skills/automerge-all/SKILL.md`

**Interfaces:**
- Consumes: `automerge-pr/candidates.sh` (Task 2), the `automerge-pr` skill in orchestrated mode (Task 6), `automerge-pr/apply_verdict.sh` (unchanged).

- [ ] **Step 1: Write the SKILL.md**

```markdown
---
name: automerge-all
description: Review every open agent-created PR with a fresh automerge-pr run each and autonomously squash-merge the high-confidence ones. Use when the user says "automerge-all", "automerge", "merge ready PRs", "review open PRs", or asks to clear the PR backlog without reviewing each one by hand.
---

You autonomously clear the pipeline's PR backlog by running `/automerge-pr`
against every open candidate, reviews in parallel, merges applied one at a
time so two merges never race on `master`.

## 1. Find the candidates

```bash
.claude/skills/automerge-pr/candidates.sh
```

If `candidates` is empty, print `No agent PRs ready to review.`, list
`skipped` with reasons, and stop.

## 2. Review each candidate — one subagent per PR, in parallel, orchestrated mode

Spawn **one subagent per candidate PR, all in a single message**, so they
run concurrently — fresh context per PR. Give each subagent exactly this
prompt, with `{N}` replaced by the PR number:

> Follow `.claude/skills/automerge-pr/SKILL.md` for PR #{N} in this
> repository. Skip its step 1 (you already have the PR number: {N}).
>
> **ORCHESTRATED MODE**: when you reach step 5 (apply the verdict), do NOT
> call `apply_verdict.sh` for a review verdict. Instead write the parsed
> verdict JSON from step 4 to `/tmp/automerge-verdict-{N}.json` and end your
> entire final message with exactly one line: `VERDICT_FILE:
> /tmp/automerge-verdict-{N}.json`.
>
> This does NOT apply to step 2's hygiene auto-reject — if step 2 auto-rejects
> this PR (`still-failing` or `conflict`), complete that step's
> `apply_verdict.sh --action needs-work` call as written, and instead end
> your final message with exactly one line:
> `HYGIENE_REJECTED: {status} — {detail}`.
>
> If step 2 reports `pending-timeout`, end your final message with exactly
> one line: `SKIPPED: CI checks pending, retry later`.

## 3. Collect results

For each subagent's final line:

- `VERDICT_FILE: {path}` → read the JSON at that path, queue it for step 4.
- `HYGIENE_REJECTED: ...` or `SKIPPED: ...` → record it for the report; no
  further action, this PR is already resolved or intentionally untouched.

## 4. Apply the queued verdicts — serially

Process the queued verdicts one at a time, **in ascending PR number**, so
two merges never race on `master`:

```bash
.claude/skills/automerge-pr/apply_verdict.sh \
  --pr {N} --action {action} --review-file /tmp/automerge-review-{N}.md --issue {issue}
```

(The `review-file` path is whatever the subagent wrote to in its own step
4 — `/tmp/automerge-review-{N}.md` per `automerge-pr/SKILL.md`.) Use the
`linkedIssue` from step 1's candidate object; pass `--issue` when non-null.
A non-zero exit means that PR failed. **Continue to the next PR
regardless** — one failure never aborts the batch.

## 5. Report

Print a table of every PR: number, hygiene outcome, score (if reviewed),
verdict, action taken. Then list:

- `skipped` from step 1, with reasons
- every `HYGIENE_REJECTED` and `SKIPPED` PR from step 3
- any PR whose review was unparseable
- any `apply_verdict.sh` failure, with its `detail`
- if `truncated` > 0, state exactly how many PRs were left unprocessed

The user reads only this report. It must say what was *not* done as clearly
as what was.

## Constants

Do not restate these values elsewhere; each lives in exactly one file.

| Constant | Where it lives |
|----------|----------------|
| `MERGE_THRESHOLD`, `NEEDS_WORK_THRESHOLD` | `automerge-pr/parse_verdict.py` |
| `MAX_CANDIDATES`, `AGENT_LABEL` | `automerge-pr/candidates.sh` |
| `MERGED_ISSUE_LABEL`, `NEEDS_WORK_LABEL` | `automerge-pr/apply_verdict.sh` |

## Limits worth knowing

Same limits as `/automerge-pr` (no test-suite execution, prompt-only
READ-ONLY constraint, no confirmation prompt, no dedup on repeated
`comment`-band reviews) — see that skill's *Limits* section, not restated
here.

Verdict application happens serially even though review happens in
parallel — a PR flagged `needs-work` on hygiene grounds during the parallel
phase is already resolved by the time step 4 runs; only real review
verdicts (`merge`/`comment`/`needs-work` from a completed review) go
through the serial queue.
```

- [ ] **Step 2: Commit**

```bash
git add .claude/skills/automerge-all/SKILL.md
git commit -m "feat: add automerge-all SKILL.md"
```

---

## Task 8: Rename `rework` → `rework-pr` (mechanical)

**Files:**
- Rename: `.claude/skills/rework/` → `.claude/skills/rework-pr/`
- Rename: `tests/test_rework.py` → `tests/test_rework_pr.py`

- [ ] **Step 1: Move the directory**

```bash
git mv .claude/skills/rework .claude/skills/rework-pr
```

- [ ] **Step 2: Rename the test file and update its path constant**

```bash
git mv tests/test_rework.py tests/test_rework_pr.py
```

In `tests/test_rework_pr.py`, change:

```python
SKILL_DIR = REPO_ROOT / ".claude" / "skills" / "rework"
```

to:

```python
SKILL_DIR = REPO_ROOT / ".claude" / "skills" / "rework-pr"
```

- [ ] **Step 3: Run the suite to confirm the rename didn't break anything**

Run: `pytest tests/test_rework_pr.py -v`
Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor: rename rework skill to rework-pr"
```

---

## Task 9: `rework-pr/find_candidate.sh` — agent-wip claim skip, live-label re-check, stop skipping CONFLICTING

**Files:**
- Modify: `.claude/skills/rework-pr/find_candidate.sh`
- Test: `tests/test_rework_pr.py`

**Interfaces:**
- Produces: `find_candidate.sh`'s eligibility walk now: (1) still skips `draft` and `UNKNOWN` mergeability without fetching comments; (2) skips any PR already carrying `agent-wip`, without fetching comments; (3) re-checks the live `.labels` field for `needs-work`+`agent` and skips with reason `"stale search match (no longer carries needs-work+agent live)"` if either is missing; (4) no longer treats `CONFLICTING` as a skip reason at all — such PRs proceed to the comment-count/cap check like any other; (5) `--json` field list gains `labels`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_rework_pr.py`:

```python
def test_conflicting_pr_is_no_longer_skipped(candidate_runner):
    # rework-pr now resolves real conflicts itself (via merge, see SKILL.md
    # step 5) — CONFLICTING is eligible, not a permanent skip.
    result = candidate_runner(
        [_needs_work_pr(129, "2026-08-01T00:00:00Z", mergeable="CONFLICTING")],
        {129: []},
    )

    assert result["candidate"]["number"] == 129
    assert result["skipped"] == []


def test_pr_claimed_by_agent_wip_is_skipped_without_fetching_comments(candidate_runner):
    result = candidate_runner(
        [_needs_work_pr(129, "2026-08-01T00:00:00Z",
                         labels=[{"name": "needs-work"}, {"name": "agent"}, {"name": "agent-wip"}])],
        {129: []},
    )

    assert result["candidate"] is None
    assert result["skipped"] == [
        {"number": 129, "reason": "claimed by an in-progress rework-pr run"}
    ]
    assert not any("issues/129/comments" in call for call in result["_gh_calls"])


def test_stale_search_match_missing_needs_work_label_live_is_skipped(candidate_runner):
    # gh pr list --label filters via a search index that can lag; the live
    # .labels field is the source of truth.
    result = candidate_runner(
        [_needs_work_pr(129, "2026-08-01T00:00:00Z", labels=[{"name": "agent"}])],
        {129: []},
    )

    assert result["candidate"] is None
    assert result["skipped"] == [
        {"number": 129, "reason": "stale search match (no longer carries needs-work+agent live)"}
    ]


def test_stale_search_match_missing_agent_label_live_is_skipped(candidate_runner):
    result = candidate_runner(
        [_needs_work_pr(129, "2026-08-01T00:00:00Z", labels=[{"name": "needs-work"}])],
        {129: []},
    )

    assert result["candidate"] is None
    assert result["skipped"][0]["reason"] == "stale search match (no longer carries needs-work+agent live)"


def test_live_labels_confirmed_pr_is_still_a_candidate(candidate_runner):
    result = candidate_runner(
        [_needs_work_pr(129, "2026-08-01T00:00:00Z",
                         labels=[{"name": "needs-work"}, {"name": "agent"}])],
        {129: []},
    )

    assert result["candidate"]["number"] == 129
```

Also update the `_needs_work_pr()` helper (already in the file) to include a
`labels` default so existing tests that don't pass `labels` explicitly keep
passing once the live-label check ships — change:

```python
def _needs_work_pr(number, created_at, **overrides):
    base = {
        "number": number, "title": f"PR {number}", "createdAt": created_at,
        "headRefName": f"feature/{number}-Thing", "body": "",
        "isDraft": False, "mergeable": "MERGEABLE",
        "labels": [{"name": "needs-work"}, {"name": "agent"}],
    }
    base.update(overrides)
    return base
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_rework_pr.py -v`
Expected: several FAIL — the `CONFLICTING` test fails because it's still
skipped; the `agent-wip` and stale-label tests fail because the script
doesn't check `.labels` at all yet; pre-existing tests that relied on the
default `_needs_work_pr()` `labels: []` may also now behave differently
once you add the live-label check in Step 3 — that's expected and
addressed by the helper's new default above.

- [ ] **Step 3: Update `find_candidate.sh`**

Full replacement for `.claude/skills/rework-pr/find_candidate.sh`:

```bash
#!/usr/bin/env bash
# Find the oldest open `needs-work` PR that hasn't hit the revision-attempt
# cap and isn't already claimed by an in-progress rework-pr run.
#
# Emits JSON: {"candidate": {...}|null, "skipped": [...]}
set -euo pipefail

NEEDS_WORK_LABEL="needs-work"
AGENT_WIP_LABEL="agent-wip"
MAX_REVISION_ATTEMPTS=3
# /automerge-pr only ever labels PRs that already carry `agent` (see
# automerge-pr/candidates.sh's own `--label agent` filter), so this keeps
# eligibility here to "PRs /automerge-pr itself rejected" rather than any
# needs-work-labelled PR from any source (human-labelled, a fork PR, etc.).
AGENT_LABEL="agent"

REPO="${GH_REPO:-}"
if [ -z "$REPO" ]; then
  url=$(git remote get-url origin 2>/dev/null) || { echo "cannot detect repo: no origin remote" >&2; exit 1; }
  case "$url" in
    *github.com*) ;;
    *) echo "cannot detect repo: origin is not a github.com remote" >&2; exit 1 ;;
  esac
  REPO="${url#*github.com[:/]}"
  REPO="${REPO%.git}"
  REPO="${REPO%/}"
  if [ -z "$REPO" ] || [[ "$REPO" != */* ]]; then
    echo "cannot detect repo: could not parse origin URL" >&2; exit 1
  fi
fi

prs_json=$(gh pr list \
  --repo "$REPO" \
  --state open \
  --label "$NEEDS_WORK_LABEL" \
  --label "$AGENT_LABEL" \
  --limit 100 \
  --json number,title,createdAt,headRefName,body,isDraft,mergeable,labels)

sorted_numbers=$(echo "$prs_json" | jq -r 'sort_by(.createdAt) | .[].number')

candidate="null"
skipped="[]"

for n in $sorted_numbers; do
  pr_obj=$(echo "$prs_json" | jq --argjson n "$n" '.[] | select(.number == $n)')
  is_draft=$(echo "$pr_obj" | jq -r '.isDraft')
  mergeable=$(echo "$pr_obj" | jq -r '.mergeable')
  has_needs_work=$(echo "$pr_obj" | jq --arg l "$NEEDS_WORK_LABEL" '[.labels[]?.name] | any(. == $l)')
  has_agent=$(echo "$pr_obj" | jq --arg l "$AGENT_LABEL" '[.labels[]?.name] | any(. == $l)')
  has_agent_wip=$(echo "$pr_obj" | jq --arg l "$AGENT_WIP_LABEL" '[.labels[]?.name] | any(. == $l)')

  # Draft/unresolved-mergeability PRs are out of scope. CONFLICTING is no
  # longer skipped here — rework-pr's own merge-and-resolve step (SKILL.md
  # step 5) is what handles a genuinely conflicting PR.
  if [ "$is_draft" = "true" ]; then
    skipped=$(echo "$skipped" | jq --argjson n "$n" \
      '. + [{number: $n, reason: "draft"}]')
    continue
  fi
  if [ "$mergeable" = "UNKNOWN" ]; then
    skipped=$(echo "$skipped" | jq --argjson n "$n" \
      '. + [{number: $n, reason: "UNKNOWN (mergeability not computed, retry)"}]')
    continue
  fi
  if [ "$has_agent_wip" = "true" ]; then
    skipped=$(echo "$skipped" | jq --argjson n "$n" \
      '. + [{number: $n, reason: "claimed by an in-progress rework-pr run"}]')
    continue
  fi
  # gh pr list --label filters via GitHub's search index, which can lag
  # behind live label state for a short window after a label change. The
  # live .labels field (already in hand from the query above) is the
  # source of truth.
  if [ "$has_needs_work" != "true" ] || [ "$has_agent" != "true" ]; then
    skipped=$(echo "$skipped" | jq --argjson n "$n" \
      '. + [{number: $n, reason: "stale search match (no longer carries needs-work+agent live)"}]')
    continue
  fi

  # --paginate: GitHub defaults to 30 comments/page, oldest first, so on any
  # PR with more than 30 comments the most recent `verdict: REJECT` blocks
  # would otherwise sit on pages that are never fetched, undercounting
  # attempts and letting the cap never trip.
  comments_json=$(gh api --paginate "repos/$REPO/issues/$n/comments")
  attempts=$(echo "$comments_json" \
    | jq '[.[].body // "" | select(test("verdict:\\s*REJECT"))] | length')

  if [ "$attempts" -ge "$MAX_REVISION_ATTEMPTS" ]; then
    skipped=$(echo "$skipped" | jq --argjson n "$n" --argjson a "$attempts" \
      '. + [{number: $n, reason: "revision cap reached (\($a) attempts)"}]')
    continue
  fi

  candidate=$(echo "$pr_obj" | jq --argjson a "$attempts" '
    def linked_issue:
      ([(.body // "") | scan("[Cc]loses #([0-9]+)")]) as $matches
      | if ($matches | length) == 0 then null else ($matches[0][0] | tonumber) end;
    {number, title, headRefName, attempts: $a, linkedIssue: linked_issue}
  ')
  break
done

jq -n --argjson candidate "$candidate" --argjson skipped "$skipped" \
  '{candidate: $candidate, skipped: $skipped}'
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_rework_pr.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_rework_pr.py .claude/skills/rework-pr/find_candidate.sh
git commit -m "feat: agent-wip claim skip, live-label recheck, stop skipping CONFLICTING in find_candidate.sh"
```

---

## Task 10: `rework-pr/finish_revision.sh` — release `agent-wip`

**Files:**
- Modify: `.claude/skills/rework-pr/finish_revision.sh`
- Test: `tests/test_rework_pr.py`

**Interfaces:**
- Produces: `finish_revision.sh` now removes both `needs-work` and `agent-wip` on success, reporting a failure if either removal fails.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_rework_pr.py`:

```python
def test_success_removes_both_needs_work_and_agent_wip_labels(finish_runner):
    proc, calls = finish_runner()

    assert proc.returncode == 0
    joined = "\n".join(calls)
    assert "pr edit 129" in joined and "needs-work" in joined
    assert "agent-wip" in joined


def test_agent_wip_removal_failure_reports_failed(finish_runner):
    proc, calls = finish_runner(fail_on="agent-wip")

    assert proc.returncode == 1
    payload = json.loads(proc.stdout)
    assert payload["status"] == "failed"
    assert "agent-wip" in payload["detail"]
    # The comment and the needs-work removal already happened by the time
    # the agent-wip removal runs — those must not be undone or hidden.
    joined = "\n".join(calls)
    assert "pr comment 129" in joined
    assert "needs-work" in joined
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_rework_pr.py -v`
Expected: FAIL — `finish_revision.sh` never mentions `agent-wip` yet, so
`"agent-wip" in joined` is false and `fail_on="agent-wip"` never matches
anything (the script exits 0 without ever calling a command containing that
string).

- [ ] **Step 3: Update `finish_revision.sh`**

```bash
#!/usr/bin/env bash
# Remove needs-work and agent-wip, and post the audit comment, for one
# revised PR.
#
#   finish_revision.sh --pr N --summary-file PATH
#
# Only call this after the revision has been committed and pushed
# successfully — a failed revision must not look resolved.
set -uo pipefail

NEEDS_WORK_LABEL="needs-work"
AGENT_WIP_LABEL="agent-wip"

PR=""; SUMMARY_FILE=""

while [ $# -gt 0 ]; do
  case "$1" in
    --pr)            PR="$2"; shift 2 ;;
    --summary-file)  SUMMARY_FILE="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 1 ;;
  esac
done

report() {  # status, detail
  jq -n --argjson pr "${PR:-null}" --arg status "$1" --arg detail "$2" \
    '{pr: $pr, status: $status, detail: $detail}'
}

fail() { report "failed" "$1"; exit 1; }

[ -n "$PR" ] || { echo "--pr is required" >&2; exit 1; }
[ -n "$SUMMARY_FILE" ] && [ -f "$SUMMARY_FILE" ] || { echo "--summary-file must exist" >&2; exit 1; }

REPO="${GH_REPO:-}"
if [ -z "$REPO" ]; then
  url=$(git remote get-url origin 2>/dev/null) || fail "cannot detect repo: no origin remote"
  case "$url" in
    *github.com*) ;;
    *) fail "cannot detect repo: origin is not a github.com remote" ;;
  esac
  REPO="${url#*github.com[:/]}"
  REPO="${REPO%.git}"
  REPO="${REPO%/}"
  [ -n "$REPO" ] && [[ "$REPO" == */* ]] || fail "cannot detect repo: could not parse origin URL"
fi

# Post the audit comment before touching either label, so the trail exists
# even if a label edit below fails.
gh pr comment "$PR" --repo "$REPO" --body-file "$SUMMARY_FILE" \
  || fail "could not post revision summary comment"

gh pr edit "$PR" --repo "$REPO" --remove-label "$NEEDS_WORK_LABEL" \
  || fail "revision summary posted, but could not remove $NEEDS_WORK_LABEL label"

gh pr edit "$PR" --repo "$REPO" --remove-label "$AGENT_WIP_LABEL" \
  || fail "revision summary posted and $NEEDS_WORK_LABEL removed, but could not remove $AGENT_WIP_LABEL label"

report "ok" "revision summary posted, $NEEDS_WORK_LABEL and $AGENT_WIP_LABEL removed"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_rework_pr.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_rework_pr.py .claude/skills/rework-pr/finish_revision.sh
git commit -m "feat: release agent-wip claim in finish_revision.sh"
```

---

## Task 11: `rework-pr/list_candidates.sh`

**Files:**
- Create: `.claude/skills/rework-pr/list_candidates.sh`
- Test: `tests/test_rework_pr.py`

**Interfaces:**
- Produces: `list_candidates.sh` → JSON: `{"candidates": [{number, title, headRefName, attempts, linkedIssue, createdAt}], "skipped": [...], "truncated": N}` — same eligibility rules as `find_candidate.sh` (Task 9), but collects every eligible PR (oldest first, capped at `MAX_CANDIDATES=20` — same bound and same reasoning as `automerge-pr/candidates.sh`: an unbounded fan-out would spawn an unbounded number of parallel subagents) instead of stopping at the first one.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_rework_pr.py`:

```python
# === list_candidates.sh tests ===


@pytest.fixture
def list_candidate_runner(tmp_path):
    """Same fake `gh` as candidate_runner, but drives list_candidates.sh."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "gh"
    stub.write_text(GH_STUB)
    stub.chmod(0o755)

    comments_dir = tmp_path / "comments"
    comments_dir.mkdir()

    def run(pr_list, comments_by_number=None):
        payload = tmp_path / "prs.json"
        payload.write_text(json.dumps(pr_list))
        for number, bodies in (comments_by_number or {}).items():
            comment_objs = [{"body": b} for b in bodies]
            (comments_dir / f"{number}.json").write_text(json.dumps(comment_objs))
        env = {
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "GH_STUB_PR_LIST_JSON": str(payload),
            "GH_STUB_COMMENTS_DIR": str(comments_dir),
            "GH_STUB_LOG": str(tmp_path / "gh.log"),
            "GH_REPO": "onpaj/harness",
        }
        proc = subprocess.run(
            [str(SKILL_DIR / "list_candidates.sh")],
            capture_output=True, text=True, env=env,
        )
        assert proc.returncode == 0, proc.stderr
        return json.loads(proc.stdout)

    return run


def test_all_eligible_prs_are_returned_oldest_first(list_candidate_runner):
    result = list_candidate_runner(
        [
            _needs_work_pr(200, "2026-08-05T00:00:00Z"),
            _needs_work_pr(129, "2026-08-01T00:00:00Z"),
        ],
        {129: [], 200: []},
    )

    assert [c["number"] for c in result["candidates"]] == [129, 200]
    assert result["skipped"] == []


def test_list_still_excludes_agent_wip_and_stale_and_cap(list_candidate_runner):
    result = list_candidate_runner(
        [
            _needs_work_pr(1, "2026-08-01T00:00:00Z",
                            labels=[{"name": "needs-work"}, {"name": "agent"}, {"name": "agent-wip"}]),
            _needs_work_pr(2, "2026-08-02T00:00:00Z", labels=[{"name": "agent"}]),
            _needs_work_pr(3, "2026-08-03T00:00:00Z"),
            _needs_work_pr(4, "2026-08-04T00:00:00Z"),
        ],
        {2: [], 3: [REJECT_COMMENT] * 3, 4: []},
    )

    assert [c["number"] for c in result["candidates"]] == [4]
    reasons = {s["number"]: s["reason"] for s in result["skipped"]}
    assert reasons[1] == "claimed by an in-progress rework-pr run"
    assert "stale search match" in reasons[2]
    assert "revision cap reached" in reasons[3]


def test_list_includes_conflicting_prs(list_candidate_runner):
    result = list_candidate_runner(
        [_needs_work_pr(129, "2026-08-01T00:00:00Z", mergeable="CONFLICTING")],
        {129: []},
    )

    assert [c["number"] for c in result["candidates"]] == [129]


def test_empty_needs_work_list_yields_empty_candidates(list_candidate_runner):
    result = list_candidate_runner([])

    assert result["candidates"] == []
    assert result["skipped"] == []


def test_truncates_at_twenty_and_reports_the_remainder(list_candidate_runner):
    prs = [_needs_work_pr(n, f"2026-08-01T00:00:{n:02d}Z") for n in range(1, 26)]
    result = list_candidate_runner(prs, {n: [] for n in range(1, 26)})

    assert len(result["candidates"]) == 20
    assert result["truncated"] == 5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_rework_pr.py -v`
Expected: FAIL — `.claude/skills/rework-pr/list_candidates.sh` does not exist.

- [ ] **Step 3: Write the script**

Create `.claude/skills/rework-pr/list_candidates.sh`:

```bash
#!/usr/bin/env bash
# List every open `needs-work` PR eligible for /rework-pr — same
# eligibility rules as find_candidate.sh, but returns all of them
# (oldest first) instead of stopping at the first.
#
# Emits JSON: {"candidates": [...], "skipped": [...]}
set -euo pipefail

NEEDS_WORK_LABEL="needs-work"
AGENT_WIP_LABEL="agent-wip"
MAX_REVISION_ATTEMPTS=3
AGENT_LABEL="agent"
# Same bound and reasoning as automerge-pr/candidates.sh's MAX_CANDIDATES:
# rework-all spawns one subagent per candidate, so this caps how many run
# in parallel in one invocation.
MAX_CANDIDATES=20

REPO="${GH_REPO:-}"
if [ -z "$REPO" ]; then
  url=$(git remote get-url origin 2>/dev/null) || { echo "cannot detect repo: no origin remote" >&2; exit 1; }
  case "$url" in
    *github.com*) ;;
    *) echo "cannot detect repo: origin is not a github.com remote" >&2; exit 1 ;;
  esac
  REPO="${url#*github.com[:/]}"
  REPO="${REPO%.git}"
  REPO="${REPO%/}"
  if [ -z "$REPO" ] || [[ "$REPO" != */* ]]; then
    echo "cannot detect repo: could not parse origin URL" >&2; exit 1
  fi
fi

prs_json=$(gh pr list \
  --repo "$REPO" \
  --state open \
  --label "$NEEDS_WORK_LABEL" \
  --label "$AGENT_LABEL" \
  --limit 100 \
  --json number,title,createdAt,headRefName,body,isDraft,mergeable,labels)

sorted_numbers=$(echo "$prs_json" | jq -r 'sort_by(.createdAt) | .[].number')

candidates="[]"
skipped="[]"
candidate_count=0
truncated=0

for n in $sorted_numbers; do
  pr_obj=$(echo "$prs_json" | jq --argjson n "$n" '.[] | select(.number == $n)')
  is_draft=$(echo "$pr_obj" | jq -r '.isDraft')
  mergeable=$(echo "$pr_obj" | jq -r '.mergeable')
  has_needs_work=$(echo "$pr_obj" | jq --arg l "$NEEDS_WORK_LABEL" '[.labels[]?.name] | any(. == $l)')
  has_agent=$(echo "$pr_obj" | jq --arg l "$AGENT_LABEL" '[.labels[]?.name] | any(. == $l)')
  has_agent_wip=$(echo "$pr_obj" | jq --arg l "$AGENT_WIP_LABEL" '[.labels[]?.name] | any(. == $l)')

  if [ "$is_draft" = "true" ]; then
    skipped=$(echo "$skipped" | jq --argjson n "$n" \
      '. + [{number: $n, reason: "draft"}]')
    continue
  fi
  if [ "$mergeable" = "UNKNOWN" ]; then
    skipped=$(echo "$skipped" | jq --argjson n "$n" \
      '. + [{number: $n, reason: "UNKNOWN (mergeability not computed, retry)"}]')
    continue
  fi
  if [ "$has_agent_wip" = "true" ]; then
    skipped=$(echo "$skipped" | jq --argjson n "$n" \
      '. + [{number: $n, reason: "claimed by an in-progress rework-pr run"}]')
    continue
  fi
  if [ "$has_needs_work" != "true" ] || [ "$has_agent" != "true" ]; then
    skipped=$(echo "$skipped" | jq --argjson n "$n" \
      '. + [{number: $n, reason: "stale search match (no longer carries needs-work+agent live)"}]')
    continue
  fi

  # Past the cap: stop spending an API call on this PR's comment history —
  # it just counts toward `truncated`, same semantics as candidates.sh's
  # own slice-then-count.
  if [ "$candidate_count" -ge "$MAX_CANDIDATES" ]; then
    truncated=$((truncated + 1))
    continue
  fi

  comments_json=$(gh api --paginate "repos/$REPO/issues/$n/comments")
  attempts=$(echo "$comments_json" \
    | jq '[.[].body // "" | select(test("verdict:\\s*REJECT"))] | length')

  if [ "$attempts" -ge "$MAX_REVISION_ATTEMPTS" ]; then
    skipped=$(echo "$skipped" | jq --argjson n "$n" --argjson a "$attempts" \
      '. + [{number: $n, reason: "revision cap reached (\($a) attempts)"}]')
    continue
  fi

  entry=$(echo "$pr_obj" | jq --argjson a "$attempts" '
    def linked_issue:
      ([(.body // "") | scan("[Cc]loses #([0-9]+)")]) as $matches
      | if ($matches | length) == 0 then null else ($matches[0][0] | tonumber) end;
    {number, title, headRefName, createdAt, attempts: $a, linkedIssue: linked_issue}
  ')
  candidates=$(echo "$candidates" | jq --argjson e "$entry" '. + [$e]')
  candidate_count=$((candidate_count + 1))
done

jq -n --argjson candidates "$candidates" --argjson skipped "$skipped" --argjson truncated "$truncated" \
  '{candidates: $candidates, skipped: $skipped, truncated: $truncated}'
```

```bash
chmod +x .claude/skills/rework-pr/list_candidates.sh
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_rework_pr.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_rework_pr.py .claude/skills/rework-pr/list_candidates.sh
git commit -m "feat: add rework-pr/list_candidates.sh for rework-all"
```

---

## Task 12: `rework-pr/SKILL.md` — claim, merge-not-rebase sync, push-retry, PR-number parameter

**Files:**
- Modify: `.claude/skills/rework-pr/SKILL.md`

**Interfaces:**
- Consumes: `find_candidate.sh` (Task 9), `finish_revision.sh` (Task 10).
- Produces: the `/rework-pr` skill, accepting an optional PR number.

- [ ] **Step 1: Rewrite `.claude/skills/rework-pr/SKILL.md`**

```markdown
---
name: rework-pr
description: Revise one open needs-work PR — claim it, bring it current with the default branch, fix what its review or CI-failure comments describe, and push. Use when the user says "rework-pr", "revise PR N", "fix up this needs-work PR", or gives a specific PR number to rework.
---

You revise one PR that's labelled `needs-work` — whether that came from
`/automerge-pr`'s code review or its hygiene auto-reject — read what it
says is wrong, fix the code, and push. Called directly for one PR, or by
`/rework-all` as part of a full-backlog sweep.

**All deterministic work is done by the scripts beside this file.** Do not
re-implement their logic or hand-write the `gh` commands they already own.
Your judgement calls are: reading the review/CI feedback and fixing the
code, and resolving any real conflict when syncing with the default branch.

One PR per invocation. Run this skill again for the next one.

## 1. Resolve the target PR

If a PR number was given in your invocation, use it as `{N}` and skip to
step 2 (still confirm it's `OPEN` there — an explicit number bypasses
candidate *search*, not the open-state check). Otherwise:

```bash
.claude/skills/rework-pr/find_candidate.sh > /tmp/rework-candidate.json
```

Writes `{"candidate": {...}|null, "skipped": [...]}` to
`/tmp/rework-candidate.json`. Do not second-guess the cap, the live-label
check, or the `agent-wip` skip — read fields with `jq`, never interpolate
PR-derived text (like `headRefName`) directly into a shell string.

If `candidate` is `null`
(`jq -e '.candidate == null' /tmp/rework-candidate.json`), print
`No needs-work PRs ready to revise.`, list `skipped` with reasons, and
stop. Otherwise set `{N}` from `.candidate.number`.

## 2. Confirm it's open, then claim it

```bash
gh pr view {N} --json state --jq .state
```

If the result is not `OPEN`, report this PR as skipped (not pushed to) and
**stop** — do not proceed to step 3 or beyond.

Otherwise, claim it immediately, before any branch work starts. The label
may not exist in the repo yet — create it best-effort first, the same
pattern `apply_verdict.sh` already uses for `needs-work`/`agent-merged`:

```bash
gh label create agent-wip --color fbca04 \
  --description "Claimed by an in-progress /rework-pr run" >/dev/null 2>&1 || true
gh pr edit {N} --add-label agent-wip
```

**From this point on, every exit path (not-open — already handled above,
unresolved conflict in step 4, exhausted push retries in step 6, or
success) must release this claim**:

```bash
gh pr edit {N} --remove-label agent-wip
```

Do this even on a path that also leaves `needs-work` in place — the claim
and the `needs-work` label are independent; releasing the claim just makes
this PR visible to the next `find_candidate.sh`/`list_candidates.sh` run
again.

## 3. Check out the PR's branch

The PR's branch already exists — it was created by `oneshot`. Reuse its
worktree convention:

```bash
HEAD_REF=$(jq -r '.candidate.headRefName // empty' /tmp/rework-candidate.json)
# If you took the explicit-PR-number path in step 1, HEAD_REF came from
# `gh pr view {N} --json headRefName --jq .headRefName` instead.
WORKTREE="../worktrees/$(echo "$HEAD_REF" | sed 's#/#-#')"

if [ -d "$WORKTREE" ]; then
  git -C "$WORKTREE" fetch origin "$HEAD_REF"
  git -C "$WORKTREE" reset --hard "origin/$HEAD_REF"
else
  git worktree add "$WORKTREE" "$HEAD_REF"
fi
```

All edits, commits, and the push happen inside `$WORKTREE` — never against
the primary checkout.

## 4. Sync with the default branch — merge, not rebase

```bash
DEFAULT_BRANCH=$(gh repo view --json defaultBranchRef --jq .defaultBranchRef.name)
git -C "$WORKTREE" fetch origin "$DEFAULT_BRANCH"
git -C "$WORKTREE" merge "origin/$DEFAULT_BRANCH" --no-edit
```

Use `merge`, never `rebase`, here: these branches are periodically synced
via merge commits already in their history, and replaying their original
linear commits with `git rebase` manufactures false conflicts on history a
plain `git merge` reconciles cleanly. `defaultBranchRefName` is **not** a
valid `gh repo view` field — always use `defaultBranchRef.name`.

If the merge reports conflicts, resolve them as a judgement call — same
tier as reading review feedback in step 5. If a conflict's intent is
genuinely unclear (e.g. the same line changed two incompatible ways for
reasons you can't determine from context), abort the merge
(`git -C "$WORKTREE" merge --abort`), release the `agent-wip` claim (step
2's release command), report this PR as skipped with the reason, and
**stop** — do not proceed to step 5.

Because merge only adds commits and never rewrites history, the push in
step 6 stays a plain `git push` — no `--force-with-lease` needed.

## 5. Read the feedback and revise the code

Gather the PR's full review history before touching any code — not just
the latest `/automerge-pr` block, so context from earlier rounds or a
human's inline notes is not lost:

```bash
gh pr view {N} --json title,body,comments,reviews
gh api repos/{owner}/{repo}/pulls/{N}/comments
gh pr diff {N}
```

This includes any hygiene auto-reject comment `/automerge-pr` posted
(`Hygiene check failed for this PR before code review...`) — treat a CI
failure it describes the same way you'd treat a code-review finding: read
it, identify the concrete problem, fix it directly in `$WORKTREE`. If the
feedback is too vague to act on directly, make a good-faith improvement
rather than aborting.

## 6. Commit and push, with retry

Stage only the files you actually changed — never `git add -A`.

```bash
git -C "$WORKTREE" add <files>
git -C "$WORKTREE" commit -m "fix: address /automerge-pr review feedback"
```

Attempt the push, retrying on a non-fast-forward rejection (something else
wrote to the branch mid-run — not necessarily this skill):

```bash
attempt=1
while [ "$attempt" -le 3 ]; do
  if git -C "$WORKTREE" push origin "HEAD:$HEAD_REF"; then
    break
  fi
  if [ "$attempt" -eq 3 ]; then
    # Exhausted retries — stop. Do not call finish_revision.sh: needs-work
    # must stay on a PR whose fix did not actually land.
    gh pr edit {N} --remove-label agent-wip
    echo "push failed after 3 attempts; report what landed on the branch that this run did not push"
    exit 1
  fi
  git -C "$WORKTREE" fetch origin "$HEAD_REF"
  # Same judgement rule as step 4: merge in what's there, resolve any real
  # conflict, abort+stop (release the claim first) if intent is unclear.
  git -C "$WORKTREE" merge "origin/$HEAD_REF" --no-edit
  attempt=$((attempt + 1))
done
```

If the push never succeeds within 3 attempts, this is not a one-off race
anymore — stop (as the block above does), and your report must state what
landed on the branch that this run did not push itself.

## 7. Finish

Write a short summary of what you changed to a file using the **Write
tool** — never interpolate it into a shell command — then:

```bash
.claude/skills/rework-pr/finish_revision.sh --pr {N} --summary-file /tmp/rework-{N}-summary.md
```

This posts the summary as a PR comment, removes `needs-work`, **and
releases the `agent-wip` claim**. On success, remove the worktree:

```bash
git worktree remove "$WORKTREE"
```

## 8. Report

State which PR you revised, what you changed, whether you had to resolve a
merge conflict in step 4 or retry the push in step 6, and the `skipped`
list from step 1 (if you took that path) with reasons — a PR sitting at
the revision cap needs a human to look at it.

## Constants

Do not restate these values elsewhere; each lives in exactly one file.

| Constant | Where it lives |
|----------|----------------|
| `MAX_REVISION_ATTEMPTS` | `find_candidate.sh`, `list_candidates.sh` |
| `NEEDS_WORK_LABEL` | `find_candidate.sh`, `list_candidates.sh`, `finish_revision.sh` (must match `automerge-pr/apply_verdict.sh`'s copy) |
| `AGENT_WIP_LABEL` | `find_candidate.sh`, `list_candidates.sh`, `finish_revision.sh` (must match this file's own `agent-wip` literal in steps 2 and 6) |
| push retry cap (`3`) | this file, step 6 — no script owns it |

## Limits worth knowing

This skill's revision is not independently reviewed before `needs-work`
comes off — the next signal is whatever `/automerge-pr` says next time it
runs. A confidently-wrong revision looks identical to a correct one until
then. There is no confirmation prompt. Watch the first few runs.

The revision-attempt cap counts prior `/automerge-pr` rejections (`verdict:
REJECT` comments, whether from a code review or a hygiene auto-reject), not
`/rework-pr` runs — a PR a human re-labelled `needs-work` by hand always
looks like zero prior attempts to this skill.

The `agent-wip` claim only protects against other `rework-pr` runs. It does
not stop `hygiene-pr` from running `gh pr update-branch` on this PR
concurrently, or `automerge-pr` from reactively calling `hygiene-pr` on it
mid-revision. Running `/rework-all` at the same time as `/hygiene-all` or
`/automerge-all` on overlapping PRs is not covered by this design; treat
that combination as running one family at a time until a real conflict is
observed.

Push retries are capped at 3, not unbounded — a PR under sustained
concurrent writes from something other than this skill will still end up
`needs-work` for a human after the third rejected push.
```

- [ ] **Step 2: Verify frontmatter is well-formed**

Run: `python3 -c "t=open('.claude/skills/rework-pr/SKILL.md').read(); assert t.startswith('---\nname: rework-pr')"`
Expected: no output.

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/rework-pr/SKILL.md
git commit -m "feat: agent-wip claim, merge-sync, push-retry, and PR-number param in rework-pr"
```

---

## Task 13: `rework-all/SKILL.md`

**Files:**
- Create: `.claude/skills/rework-all/SKILL.md`

**Interfaces:**
- Consumes: `rework-pr/list_candidates.sh` (Task 11), the `rework-pr` skill (Task 12, fanned out per PR, no special mode needed).

- [ ] **Step 1: Write the SKILL.md**

```markdown
---
name: rework-all
description: Revise every open needs-work PR under the revision-attempt cap, one rework-pr run per PR, fully in parallel. Use when the user says "rework-all", "revise all needs-work PRs", "clear the needs-work backlog", or asks to act on every rejected agent PR at once.
---

You autonomously revise every open `needs-work` PR that hasn't hit the
revision-attempt cap, running `/rework-pr` against each one. Unlike
`/automerge-all`, there is no serialization step here: each PR lives on its
own branch/worktree, and the `agent-wip` claim `/rework-pr` takes (its
SKILL.md step 2) prevents any two subagents from converging on the same
PR even if the candidate list is momentarily stale — so the whole batch
runs fully in parallel, start to finish.

## 1. Find the candidates

```bash
.claude/skills/rework-pr/list_candidates.sh
```

Capped at 20 PRs per run (`MAX_CANDIDATES` in `list_candidates.sh`) — the
same fan-out safety bound `/automerge-all` uses. If `candidates` is empty,
print `No needs-work PRs ready to revise.`, list `skipped` with reasons,
and stop.

## 2. Revise each candidate — one subagent per PR, fully in parallel

Spawn **one subagent per candidate PR, all in a single message**, so they
run concurrently. Give each subagent exactly this prompt, with `{N}`
replaced by the PR number:

> Follow `.claude/skills/rework-pr/SKILL.md` for PR #{N} in this
> repository, end to end, including its own commit and push. Skip its
> step 1 (you already have the PR number: {N}). Report exactly what its
> step 8 asks for as your entire final message.

## 3. Report

Print a table of every PR: number, summary of what was changed (or why it
was skipped: not-open, conflict resolution declined, push retries
exhausted). Then list the `skipped` entries from step 1 with their reasons,
and if `truncated` > 0, state exactly how many eligible PRs were left
unprocessed this run — a PR sitting at the revision cap needs a human to
look at it either way.

## Constants

Do not restate these values elsewhere; each lives in exactly one file.

| Constant | Where it lives |
|----------|----------------|
| `MAX_REVISION_ATTEMPTS`, `AGENT_WIP_LABEL`, `MAX_CANDIDATES` | `rework-pr/list_candidates.sh` |

## Limits worth knowing

If two candidates from step 1 happen to touch the same underlying issue (not
the same PR — the `agent-wip` claim already rules that out) in ways that
interact outside git (e.g. both regenerating the same generated file via an
external tool), running them fully in parallel could still produce
surprising results. This is not covered by this design; it hasn't been
observed and isn't fixed here.
```

- [ ] **Step 2: Commit**

```bash
git add .claude/skills/rework-all/SKILL.md
git commit -m "feat: add rework-all SKILL.md"
```

---

## Task 14: Package mirrors, delete old directories, update CLAUDE.md

**Files:**
- Create: `agentharness/data/skills/{hygiene-pr,hygiene-all,automerge-pr,automerge-all,rework-pr,rework-all}/` (byte-identical mirrors)
- Delete: `agentharness/data/skills/automerge/`, `agentharness/data/skills/rework/`
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: every skill directory from Tasks 1–13.
- Produces: `tests/test_packaged_skills.py` passing against the new skill set (no changes to that test file — it auto-discovers directories).

- [ ] **Step 1: Remove the stale packaged copies and re-mirror everything**

```bash
git rm -r agentharness/data/skills/automerge agentharness/data/skills/rework
mkdir -p agentharness/data/skills
for skill in hygiene-pr hygiene-all automerge-pr automerge-all rework-pr rework-all; do
  rm -rf "agentharness/data/skills/$skill"
  cp -r ".claude/skills/$skill" "agentharness/data/skills/$skill"
done
git add agentharness/data/skills
```

- [ ] **Step 2: Run the packaging test to verify the mirror is exact**

Run: `pytest tests/test_packaged_skills.py -v`
Expected: all PASS — `test_ships_the_full_skill_set` and
`test_packaged_skills_match_their_source` confirm both trees agree.

- [ ] **Step 3: Update `CLAUDE.md`'s skill table**

In `CLAUDE.md`, replace the two-row block:

```markdown
| `/automerge` | PR backlog | Reviews every open `agent` PR with a fresh subagent each, squash-merges those scoring above its configured threshold, comments on the rest |
| `/rework` | after an `/automerge` rejection | Picks the oldest `needs-work` PR under the revision-attempt cap, revises it using the review that rejected it, and pushes the fix |
```

with:

```markdown
| `/hygiene-pr {N}` | keeping one PR current | Brings one PR's branch up to date with its base and confirms CI passes, without labeling, commenting, reviewing, or merging |
| `/hygiene-all` | PR backlog | Runs `/hygiene-pr` against every open `agent` PR in parallel — a standalone currency/CI sweep, independent of review or merge |
| `/automerge-pr {N}` | one PR | Brings it current via `/hygiene-pr`, reviews it with a fresh subagent, and merges/comments/flags `needs-work` based on the score |
| `/automerge-all` | PR backlog | Runs `/automerge-pr`'s review against every open `agent` PR in parallel, applies verdicts serially so merges never race |
| `/rework-pr {N}` | one `needs-work` PR | Claims it, syncs with the default branch, revises it using the review or CI-failure feedback that flagged it, and pushes the fix |
| `/rework-all` | `needs-work` backlog | Runs `/rework-pr` against every eligible `needs-work` PR in parallel — safe because each PR's `agent-wip` claim prevents overlap |
```

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: mirror new PR-hygiene skills into agentharness/data/skills, update CLAUDE.md skill table"
```

---

## Task 15: Full suite verification

**Files:** none (verification only)

- [ ] **Step 1: Run the entire test suite**

Run: `pytest tests/ -v`
Expected: all tests PASS, no `test_automerge.py` / `test_rework.py`
collection errors (they no longer exist), `test_hygiene.py`,
`test_automerge_pr.py`, `test_rework_pr.py`, and `test_packaged_skills.py`
all green.

- [ ] **Step 2: Confirm no orphaned references to the old skill names remain**

Run: `grep -rln "\.claude/skills/automerge/\|\.claude/skills/rework/" .claude/ agentharness/ CLAUDE.md tests/ 2>/dev/null || echo "none found"`
Expected: `none found` — every reference now points at `automerge-pr`,
`automerge-all`, `rework-pr`, `rework-all`, `hygiene-pr`, or `hygiene-all`.

- [ ] **Step 3: Confirm the old skill directories are gone from both trees**

Run: `ls .claude/skills/ agentharness/data/skills/`
Expected: both listings show `hygiene-pr`, `hygiene-all`, `automerge-pr`,
`automerge-all`, `rework-pr`, `rework-all` and no bare `automerge`/`rework`
entries.

No commit for this task — it's verification of Tasks 1–14's cumulative
state.
