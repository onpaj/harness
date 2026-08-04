# /rework — Autonomous Revision of `needs-work` PRs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `/rework` skill that picks up the oldest open PR labelled `needs-work` (one `/automerge` itself rejected), revises it in place using the review that rejected it, and pushes the fix — clearing it for `/automerge` to reconsider next time it runs.

**Architecture:** Two deterministic bash+`gh`+`jq` scripts (`find_candidate.sh`, `finish_revision.sh`) beside a `SKILL.md` that carries the one judgement step — reading a review and fixing the code — the same split `/automerge` already established. `find_candidate.sh` selects the oldest eligible PR under a revision-attempt cap; `finish_revision.sh` removes the label and posts the audit comment after a successful push.

**Tech Stack:** bash, `gh` CLI, `jq`; pytest for script tests (stub `gh` on `PATH`, no network).

## Global Constraints

- Constants live in exactly one file each: `MAX_REVISION_ATTEMPTS = 3` in `find_candidate.sh`; `NEEDS_WORK_LABEL = "needs-work"` is duplicated (by necessity, matching `automerge/apply_verdict.sh`'s existing copy) across `find_candidate.sh` and `finish_revision.sh` — keep all three in sync if the label name ever changes.
- Repo detection follows the exact convention already used by `automerge/candidates.sh` and `applicationinsightsscan/gh-api.sh`: parse `origin` directly, override with `GH_REPO=owner/repo`.
- Never interpolate PR-derived or model-authored text into a shell command — write it to a file first, pass it with `--body-file` / `--summary-file`.
- Never silently swallow a `gh`/API error — let it propagate (script failure, real stderr), per this repo's error-handling convention (already followed in `automerge`'s scripts).
- Stage only files actually changed (`git add <files>`), never `git add -A`.
- `agentharness/data/skills/` must mirror `.claude/skills/` byte-for-byte, no symlinks (`tests/test_packaged_skills.py` enforces this already).
- Coverage target 80% per the repo standard, measured on the new scripts.

---

### Task 1: Candidate selection — `find_candidate.sh`

**Files:**
- Create: `.claude/skills/rework/find_candidate.sh`
- Test: `tests/test_rework.py` (new file)

**Interfaces:**
- Produces: a CLI script invoked with no arguments, reading `GH_REPO` (optional) from the environment, writing JSON to stdout:
  `{"candidate": {"number": int, "title": str, "headRefName": str, "attempts": int, "linkedIssue": int|null} | null, "skipped": [{"number": int, "reason": str}]}`
- Consumed by: Task 3's `SKILL.md` (step 1) and, in production, by whichever session invokes `/rework`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_rework.py`:

```python
"""Tests for the /rework skill scripts."""
import json
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO_ROOT / ".claude" / "skills" / "rework"


# === find_candidate.sh tests ===

GH_STUB = """\
#!/usr/bin/env bash
# Fake `gh` for tests: serves `pr list` from a canned file, and
# `api repos/.../issues/N/comments` from per-PR canned comment files.
if [ "$1" = "pr" ] && [ "$2" = "list" ]; then
  cat "$GH_STUB_PR_LIST_JSON"
  exit 0
fi
if [ "$1" = "api" ]; then
  n=$(echo "$2" | grep -oE 'issues/[0-9]+/comments' | grep -oE '[0-9]+')
  file="$GH_STUB_COMMENTS_DIR/$n.json"
  if [ -f "$file" ]; then cat "$file"; else echo "[]"; fi
  exit 0
fi
exit 1
"""


@pytest.fixture
def candidate_runner(tmp_path):
    """Put a fake `gh` on PATH; returns a function to run find_candidate.sh
    against a canned PR list and per-PR comment bodies."""
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
            "GH_REPO": "onpaj/harness",
        }
        proc = subprocess.run(
            [str(SKILL_DIR / "find_candidate.sh")],
            capture_output=True, text=True, env=env,
        )
        assert proc.returncode == 0, proc.stderr
        return json.loads(proc.stdout)

    return run


def _needs_work_pr(number, created_at, **overrides):
    base = {
        "number": number, "title": f"PR {number}", "createdAt": created_at,
        "headRefName": f"feature/{number}-Thing", "body": "",
    }
    base.update(overrides)
    return base


REJECT_COMMENT = (
    "Reviewed the diff.\n\npr: 129\nscore: 10\nverdict: REJECT\nrisk: high\n"
    "reasons:\n  - broken\nconcerns: fix it\n"
)
OTHER_COMMENT = "Just a human note, nothing structured here."


def test_pr_with_no_reject_comments_is_the_candidate(candidate_runner):
    result = candidate_runner(
        [_needs_work_pr(129, "2026-08-01T00:00:00Z")],
        {129: [OTHER_COMMENT]},
    )

    assert result["candidate"]["number"] == 129
    assert result["candidate"]["attempts"] == 0
    assert result["skipped"] == []


def test_pr_one_under_cap_is_still_the_candidate(candidate_runner):
    result = candidate_runner(
        [_needs_work_pr(129, "2026-08-01T00:00:00Z")],
        {129: [REJECT_COMMENT, REJECT_COMMENT]},
    )

    assert result["candidate"]["number"] == 129
    assert result["candidate"]["attempts"] == 2
    assert result["skipped"] == []


def test_pr_at_cap_is_skipped_not_candidate(candidate_runner):
    result = candidate_runner(
        [_needs_work_pr(129, "2026-08-01T00:00:00Z")],
        {129: [REJECT_COMMENT, REJECT_COMMENT, REJECT_COMMENT]},
    )

    assert result["candidate"] is None
    assert result["skipped"] == [
        {"number": 129, "reason": "revision cap reached (3 attempts)"}
    ]


def test_oldest_eligible_pr_wins_the_other_is_untouched(candidate_runner):
    result = candidate_runner(
        [
            _needs_work_pr(200, "2026-08-05T00:00:00Z"),
            _needs_work_pr(129, "2026-08-01T00:00:00Z"),
        ],
        {129: [], 200: []},
    )

    assert result["candidate"]["number"] == 129
    assert result["skipped"] == []


def test_no_needs_work_prs_yields_null_candidate(candidate_runner):
    result = candidate_runner([])

    assert result["candidate"] is None
    assert result["skipped"] == []


def test_every_pr_at_cap_yields_null_candidate_and_full_skip_list(candidate_runner):
    result = candidate_runner(
        [
            _needs_work_pr(129, "2026-08-01T00:00:00Z"),
            _needs_work_pr(200, "2026-08-02T00:00:00Z"),
        ],
        {
            129: [REJECT_COMMENT] * 3,
            200: [REJECT_COMMENT] * 3,
        },
    )

    assert result["candidate"] is None
    assert {s["number"] for s in result["skipped"]} == {129, 200}


def test_candidate_reports_linked_issue(candidate_runner):
    result = candidate_runner(
        [_needs_work_pr(129, "2026-08-01T00:00:00Z", body="Closes #118\n")],
        {129: []},
    )

    assert result["candidate"]["linkedIssue"] == 118


def test_candidate_reports_null_linked_issue_when_absent(candidate_runner):
    result = candidate_runner(
        [_needs_work_pr(129, "2026-08-01T00:00:00Z", body="no link here")],
        {129: []},
    )

    assert result["candidate"]["linkedIssue"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_rework.py -v`
Expected: every test fails — `find_candidate.sh` does not exist yet, so `subprocess.run` raises `FileNotFoundError` (surfaced by pytest as an error, not a plain assertion failure).

- [ ] **Step 3: Write `find_candidate.sh`**

Create `.claude/skills/rework/find_candidate.sh` (mode `0755`):

```bash
#!/usr/bin/env bash
# Find the oldest open `needs-work` PR that hasn't hit the revision-attempt
# cap.
#
# Emits JSON: {"candidate": {...}|null, "skipped": [...]}
set -euo pipefail

NEEDS_WORK_LABEL="needs-work"
MAX_REVISION_ATTEMPTS=3

REPO="${GH_REPO:-}"
if [ -z "$REPO" ]; then
  # Same convention as .claude/skills/applicationinsightsscan/gh-api.sh's
  # detect_repo() and automerge/candidates.sh: parse `origin` directly.
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
  --limit 100 \
  --json number,title,createdAt,headRefName,body)

sorted_numbers=$(echo "$prs_json" | jq -r 'sort_by(.createdAt) | .[].number')

candidate="null"
skipped="[]"

for n in $sorted_numbers; do
  comments_json=$(gh api "repos/$REPO/issues/$n/comments")
  attempts=$(echo "$comments_json" \
    | jq '[.[].body // "" | select(test("verdict:\\s*REJECT"))] | length')

  if [ "$attempts" -ge "$MAX_REVISION_ATTEMPTS" ]; then
    skipped=$(echo "$skipped" | jq --argjson n "$n" --argjson a "$attempts" \
      '. + [{number: $n, reason: "revision cap reached (\($a) attempts)"}]')
    continue
  fi

  pr_obj=$(echo "$prs_json" | jq --argjson n "$n" '.[] | select(.number == $n)')
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

Make it executable:

```bash
chmod +x .claude/skills/rework/find_candidate.sh
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_rework.py -v`
Expected: all 9 tests pass.

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/rework/find_candidate.sh tests/test_rework.py
git commit -m "feat: add /rework candidate selection script"
```

---

### Task 2: Finishing a revision — `finish_revision.sh`

**Files:**
- Create: `.claude/skills/rework/finish_revision.sh`
- Modify: `tests/test_rework.py` (append)

**Interfaces:**
- Consumes: nothing from Task 1 — this script is independent of `find_candidate.sh` at runtime, invoked separately by `SKILL.md` after a push succeeds.
- Produces: CLI `finish_revision.sh --pr N --summary-file PATH`, reading `GH_REPO` (optional), writing JSON to stdout: `{"pr": int, "status": "ok"|"failed", "detail": str}`, exit `0` on success, `1` on failure.
- Consumed by: Task 3's `SKILL.md` (step 6).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_rework.py`:

```python
# === finish_revision.sh tests ===

GH_RECORDER = """\
#!/usr/bin/env bash
echo "$*" >> "$GH_LOG"
if [ -n "${GH_FAIL_ON:-}" ] && [[ "$*" == *"$GH_FAIL_ON"* ]]; then
  echo "${GH_FAIL_MESSAGE:-simulated gh failure}" >&2
  exit 1
fi
exit 0
"""


@pytest.fixture
def finish_runner(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "gh"
    stub.write_text(GH_RECORDER)
    stub.chmod(0o755)

    log = tmp_path / "gh.log"
    summary = tmp_path / "summary.md"
    summary.write_text("Fixed the missing test and clarified the retry loop.\n")

    def run(pr=129, fail_on=None, fail_message=None):
        env = {
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "GH_LOG": str(log),
            "GH_REPO": "onpaj/harness",
        }
        if fail_on:
            env["GH_FAIL_ON"] = fail_on
        if fail_message:
            env["GH_FAIL_MESSAGE"] = fail_message
        cmd = [
            str(SKILL_DIR / "finish_revision.sh"),
            "--pr", str(pr), "--summary-file", str(summary),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
        calls = log.read_text().splitlines() if log.exists() else []
        log.write_text("")
        return proc, calls

    return run


def test_success_comments_then_removes_label(finish_runner):
    proc, calls = finish_runner()

    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["status"] == "ok"
    assert payload["pr"] == 129
    # Order matters: the audit comment must land before the label edit.
    assert "pr comment 129" in calls[0]
    assert "pr edit 129" in calls[1] and "needs-work" in calls[1]


def test_label_removal_failure_reports_failed_but_comment_still_posted(finish_runner):
    proc, calls = finish_runner(fail_on="pr edit")

    assert proc.returncode == 1
    payload = json.loads(proc.stdout)
    assert payload["status"] == "failed"
    assert payload["pr"] == 129
    assert "could not remove" in payload["detail"]
    assert "pr comment 129" in "\n".join(calls)


def test_comment_failure_reports_failed_and_label_is_never_touched(finish_runner):
    proc, calls = finish_runner(fail_on="pr comment")

    assert proc.returncode == 1
    payload = json.loads(proc.stdout)
    assert payload["status"] == "failed"
    assert len(calls) == 1
    assert "pr comment 129" in calls[0]
    assert "pr edit" not in "\n".join(calls)


def test_missing_pr_argument_is_rejected():
    proc = subprocess.run(
        [str(SKILL_DIR / "finish_revision.sh"), "--summary-file", "/dev/null"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 1


def test_missing_summary_file_is_rejected(tmp_path):
    proc = subprocess.run(
        [str(SKILL_DIR / "finish_revision.sh"), "--pr", "129",
         "--summary-file", str(tmp_path / "does-not-exist.md")],
        capture_output=True, text=True,
    )
    assert proc.returncode == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_rework.py -v -k finish`
Expected: all 5 new tests fail — `finish_revision.sh` does not exist yet.

- [ ] **Step 3: Write `finish_revision.sh`**

Create `.claude/skills/rework/finish_revision.sh` (mode `0755`):

```bash
#!/usr/bin/env bash
# Remove needs-work and post the audit comment for one revised PR.
#
#   finish_revision.sh --pr N --summary-file PATH
#
# Only call this after the revision has been committed and pushed
# successfully — a failed revision must not look resolved.
set -uo pipefail

NEEDS_WORK_LABEL="needs-work"

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

# Post the audit comment before touching the label, so the trail exists even
# if the label edit below fails.
gh pr comment "$PR" --repo "$REPO" --body-file "$SUMMARY_FILE" \
  || fail "could not post revision summary comment"

gh pr edit "$PR" --repo "$REPO" --remove-label "$NEEDS_WORK_LABEL" \
  || fail "revision summary posted, but could not remove $NEEDS_WORK_LABEL label"

report "ok" "revision summary posted, $NEEDS_WORK_LABEL removed"
```

Make it executable:

```bash
chmod +x .claude/skills/rework/finish_revision.sh
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_rework.py -v`
Expected: all 14 tests (9 from Task 1 + 5 from this task) pass.

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/rework/finish_revision.sh tests/test_rework.py
git commit -m "feat: add /rework revision-finishing script"
```

---

### Task 3: Orchestration — `SKILL.md`

**Files:**
- Create: `.claude/skills/rework/SKILL.md`

**Interfaces:**
- Consumes: `find_candidate.sh`'s output shape (Task 1) and `finish_revision.sh`'s CLI (Task 2), both exactly as produced above.
- Produces: the `/rework` skill's entry point — no code interface, this is the prose a session follows.

- [ ] **Step 1: Write `SKILL.md`**

Create `.claude/skills/rework/SKILL.md`:

```markdown
---
name: rework
description: Pick up the oldest open PR labelled `needs-work` — one /automerge itself rejected — revise it using the review that rejected it, and push the fix. Use when the user says "rework", "revise needs-work PRs", "fix up the needs-work backlog", or asks to act on a rejected agent PR.
---

You autonomously revise one PR that `/automerge` already rejected. You find
the oldest eligible `needs-work` PR, read the review that rejected it, fix
the code it describes, and push the fix — clearing the way for `/automerge`
to reconsider it next time it runs.

**All deterministic work is done by the scripts beside this file.** Do not
re-implement their logic or hand-write the `gh` commands they already own.
Your only judgement call is reading the review and fixing the code.

One PR per invocation. Run this skill again for the next one.

## 1. Find the candidate

```bash
.claude/skills/rework/find_candidate.sh
```

Returns `{"candidate": {...}|null, "skipped": [...]}`. `candidate` is the
oldest open `needs-work` PR that has not hit the revision-attempt cap;
`skipped` lists PRs that have and will never be picked. Do not second-guess
the cap or try to rescue a skipped PR.

If `candidate` is `null`, print `No needs-work PRs ready to revise.`, list
`skipped` with reasons, and stop.

## 2. Check out the PR's branch

The PR's branch already exists — it was created by `oneshot`. Reuse its
worktree convention rather than creating a new branch:

```bash
HEAD_REF="{candidate.headRefName}"
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

## 3. Read the feedback

Gather the PR's full review history before touching any code — not just the
latest `/automerge` block, so context from earlier rounds or a human's inline
notes is not lost:

```bash
gh pr view {N} --json title,body,comments,reviews
gh api repos/{owner}/{repo}/pulls/{N}/comments
gh pr diff {N}
```

## 4. Revise the code

Read the feedback gathered above, identify the concrete issues it describes,
and fix them directly in `$WORKTREE` — this is the one part of this skill
that is not scripted, the same way `/automerge`'s scoring is not scripted:
judging what a review means requires the model. If the feedback is too vague
to act on directly, make a good-faith improvement (add the missing test,
clarify the ambiguous logic) rather than aborting.

## 5. Commit and push

Stage only the files you actually changed — never `git add -A`. Commit with
a message summarizing what was addressed, and push to the PR's existing
branch:

```bash
git -C "$WORKTREE" add <files>
git -C "$WORKTREE" commit -m "fix: address /automerge review feedback"
git -C "$WORKTREE" push origin "HEAD:$HEAD_REF"
```

If the push fails, report the failure and **stop** — do not call
`finish_revision.sh`. `needs-work` must stay on a PR whose fix did not
actually land.

## 6. Finish

Write a short summary of what you changed to a file using the **Write
tool** — never interpolate it into a shell command — then:

```bash
.claude/skills/rework/finish_revision.sh --pr {N} --summary-file /tmp/rework-{N}-summary.md
```

This posts the summary as a PR comment and removes `needs-work`. On success,
remove the worktree:

```bash
git worktree remove "$WORKTREE"
```

## 7. Report

State which PR you revised, what you changed, and the `skipped` list from
step 1 with reasons — a PR sitting at the revision cap needs a human to look
at it.

## Constants

Do not restate these values elsewhere; each lives in exactly one file.

| Constant | Where it lives |
|----------|----------------|
| `MAX_REVISION_ATTEMPTS` | `find_candidate.sh` |
| `NEEDS_WORK_LABEL` | `find_candidate.sh`, `finish_revision.sh` (must match `automerge/apply_verdict.sh`'s copy) |

## Limits worth knowing

This skill's revision is not independently reviewed before `needs-work`
comes off — the next signal is whatever `/automerge` says next time it runs.
A confidently-wrong revision looks identical to a correct one until then.
There is no confirmation prompt. Watch the first few runs.

The revision-attempt cap counts prior `/automerge` rejections (`verdict:
REJECT` comments), not `/rework` runs — a PR a human re-labelled
`needs-work` by hand always looks like zero prior attempts to this skill.
```

- [ ] **Step 2: Commit**

```bash
git add .claude/skills/rework/SKILL.md
git commit -m "docs: add /rework SKILL.md orchestration"
```

---

### Task 4: Packaging and documentation

**Files:**
- Create: `agentharness/data/skills/rework/SKILL.md`, `agentharness/data/skills/rework/find_candidate.sh`, `agentharness/data/skills/rework/finish_revision.sh` (byte-identical copies of Tasks 1-3's files)
- Modify: `CLAUDE.md:69` (skills table)

**Interfaces:**
- Consumes: the finished files from Tasks 1-3, unchanged.
- Produces: nothing new consumed elsewhere — this is the terminal packaging/doc task.

- [ ] **Step 1: Verify the packaging test currently fails for the new skill**

Run: `pytest tests/test_packaged_skills.py -v`
Expected: `test_ships_the_full_skill_set` fails — `rework` exists under `.claude/skills/` but not yet under `agentharness/data/skills/`.

- [ ] **Step 2: Copy the skill into the packaged location**

```bash
mkdir -p agentharness/data/skills/rework
cp .claude/skills/rework/SKILL.md agentharness/data/skills/rework/SKILL.md
cp .claude/skills/rework/find_candidate.sh agentharness/data/skills/rework/find_candidate.sh
cp .claude/skills/rework/finish_revision.sh agentharness/data/skills/rework/finish_revision.sh
chmod +x agentharness/data/skills/rework/find_candidate.sh agentharness/data/skills/rework/finish_revision.sh
```

- [ ] **Step 3: Run the packaging test to verify it passes**

Run: `pytest tests/test_packaged_skills.py -v`
Expected: all tests pass, including `test_packaged_skills_match_their_source` for `rework`.

- [ ] **Step 4: Add `/rework` to `CLAUDE.md`'s skills table**

In `CLAUDE.md`, find:

```markdown
| `/automerge` | PR backlog | Reviews every open `agent` PR with a fresh subagent each, squash-merges those scoring above its configured threshold, comments on the rest |
| `/azure-storage` | infra/debugging | Setup, inspect blobs, peek queues, manage dead-letter (Azure backend only) |
```

Replace with:

```markdown
| `/automerge` | PR backlog | Reviews every open `agent` PR with a fresh subagent each, squash-merges those scoring above its configured threshold, comments on the rest |
| `/rework` | after an `/automerge` rejection | Picks the oldest `needs-work` PR under the revision-attempt cap, revises it using the review that rejected it, and pushes the fix |
| `/azure-storage` | infra/debugging | Setup, inspect blobs, peek queues, manage dead-letter (Azure backend only) |
```

- [ ] **Step 5: Run the full test suite**

Run: `pytest tests/ -v`
Expected: all tests pass, including `tests/test_rework.py` (14 tests) and `tests/test_packaged_skills.py`.

- [ ] **Step 6: Commit**

```bash
git add agentharness/data/skills/rework CLAUDE.md
git commit -m "feat: package /rework skill and document it in CLAUDE.md"
```

---

## Self-Review Notes

- **Spec coverage:** every design-doc component (`find_candidate.sh` selection + attempt cap, `finish_revision.sh` label/comment, `SKILL.md`'s 7 steps, packaging, `CLAUDE.md` row) maps to a task above. The design's Component 2-5 (worktree setup, reading feedback, revising, commit/push) are prose steps inside `SKILL.md` per the design — they are not independently scriptable/testable, matching the design's explicit call-out that this is the one unscripted part.
- **Placeholder scan:** no TBD/TODO; every code block is complete and runnable as written.
- **Type consistency:** `find_candidate.sh`'s `candidate.headRefName` and `candidate.number` are the exact fields `SKILL.md` step 2 and step 3 reference; `finish_revision.sh`'s `--pr`/`--summary-file` flags match what `SKILL.md` step 6 calls with. `NEEDS_WORK_LABEL` string (`"needs-work"`) is identical in both scripts and matches `automerge/apply_verdict.sh`'s existing constant.
