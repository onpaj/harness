# `/automerge` Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a `/automerge` skill that reviews open `agent`-labelled PRs with one fresh subagent each and autonomously squash-merges the high-confidence ones.

**Architecture:** Three shell/Python scripts own everything deterministic — candidate selection, verdict parsing with band decision, and action execution. `SKILL.md` owns only the part that needs a model: fanning out one read-only `code-reviewer` subagent per PR. Subagents score; the parent merges. No subagent can write to `master`.

**Tech Stack:** bash + `gh` CLI + `jq` for the GitHub-facing scripts; Python 3.11 stdlib only for the parser; pytest for tests. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-04-pr-automerge-design.md`

## Global Constraints

- **Skill directory:** `.claude/skills/automerge/`. Every file in it must be mirrored **byte-identically** into `agentharness/data/skills/automerge/` as real files — no symlinks. `tests/test_packaged_skills.py` enforces this and goes red otherwise.
- **No new runtime dependencies.** `parse_verdict.py` uses the Python standard library only. Shell scripts may use `gh` and `jq`, both already required by `applicationinsightsscan`.
- **Thresholds are defined once:** `MERGE_THRESHOLD = 80` and `NEEDS_WORK_THRESHOLD = 40` live in `parse_verdict.py` and nowhere else. `apply_verdict.sh` receives an action and never computes one.
- **Shell scripts:** start with `#!/usr/bin/env bash` and `set -euo pipefail`, and must be `chmod +x`.
- **Repo detection:** auto-detect from the `origin` remote, override with `GH_REPO=owner/repo` — same convention as `.claude/skills/applicationinsightsscan/gh-api.sh`.
- **Commit style:** conventional commits (`feat:`, `fix:`, `test:`, `docs:`). No attribution trailer.
- **Test command:** `.venv/bin/pytest tests/test_automerge.py -v`

## Environment setup

This worktree has no virtualenv yet. Before Task 1:

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
```

---

### Task 1: `parse_verdict.py` — parse, validate, decide the band

This is the safety-critical unit: it is the only thing standing between a
confused reviewer and a merge to `master`. Build it first and test it hardest.

**Files:**
- Create: `.claude/skills/automerge/parse_verdict.py`
- Test: `tests/test_automerge.py`

**Interfaces:**
- Consumes: nothing (first task).
- Produces: a CLI reading raw subagent text on **stdin**, writing one JSON object to **stdout**, always exit 0. Later tasks depend on these exact keys:
  `{"pr": int|None, "score": int, "action": "merge"|"comment"|"needs-work", "risk": str, "reasons": list[str], "concerns": str, "valid": bool, "error": str|None}`
- Also produces the importable helpers `parse_verdict(text) -> dict` and `action_for_score(score) -> str`, which the tests call directly.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_automerge.py`:

```python
"""Tests for the /automerge skill scripts."""
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO_ROOT / ".claude" / "skills" / "automerge"


def _load_parser():
    """Import parse_verdict.py by path — it lives outside the package."""
    spec = importlib.util.spec_from_file_location(
        "parse_verdict", SKILL_DIR / "parse_verdict.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


parser = _load_parser()

WELL_FORMED = """\
I reviewed the diff and it only touches documentation.

pr: 129
score: 94
verdict: MERGE
risk: low
reasons:
  - diff is docs-only, 2 files, matches linked issue #118 exactly
  - no runtime code paths touched
concerns: none
"""


def _block(score, verdict, pr=129):
    return (
        f"pr: {pr}\nscore: {score}\nverdict: {verdict}\nrisk: low\n"
        f"reasons:\n  - a specific fact about this diff\nconcerns: none\n"
    )


def test_parses_well_formed_block():
    # Arrange / Act
    result = parser.parse_verdict(WELL_FORMED)

    # Assert
    assert result["valid"] is True
    assert result["pr"] == 129
    assert result["score"] == 94
    assert result["action"] == "merge"
    assert result["risk"] == "low"
    assert len(result["reasons"]) == 2
    assert result["concerns"] == "none"


@pytest.mark.parametrize(
    "score,expected",
    [(0, "needs-work"), (39, "needs-work"), (40, "comment"),
     (79, "comment"), (80, "merge"), (100, "merge")],
)
def test_action_for_score_at_band_boundaries(score, expected):
    assert parser.action_for_score(score) == expected


@pytest.mark.parametrize(
    "score,verdict",
    [(94, "MERGE"), (60, "COMMENT"), (10, "REJECT")],
)
def test_consistent_verdict_is_valid(score, verdict):
    assert parser.parse_verdict(_block(score, verdict))["valid"] is True


def test_verdict_contradicting_score_is_invalid():
    # A reviewer saying MERGE at score 30 is confused — never merge on it.
    result = parser.parse_verdict(_block(30, "MERGE"))

    assert result["valid"] is False
    assert result["action"] == "comment"
    assert result["score"] == 0
    assert "verdict" in result["error"]


@pytest.mark.parametrize(
    "text",
    [
        "",
        "The PR looks fine to me, no structured block at all.",
        "pr: 1\nverdict: MERGE\nreasons:\n  - x\n",          # no score
        "pr: 1\nscore: ninety\nverdict: MERGE\nreasons:\n  - x\n",
        "pr: 1\nscore: 101\nverdict: MERGE\nreasons:\n  - x\n",
        "pr: 1\nscore: -1\nverdict: REJECT\nreasons:\n  - x\n",
        "pr: 1\nscore: 90\nverdict: MERGE\n",                # no reasons
    ],
)
def test_malformed_input_never_merges(text):
    result = parser.parse_verdict(text)

    assert result["valid"] is False
    assert result["action"] == "comment"
    assert result["score"] == 0


def test_last_block_wins_when_output_has_two():
    text = _block(20, "REJECT", pr=7) + "\nOn reflection:\n\n" + _block(90, "MERGE", pr=7)

    result = parser.parse_verdict(text)

    assert result["score"] == 90
    assert result["action"] == "merge"


def test_cli_reads_stdin_and_emits_json():
    proc = subprocess.run(
        [str(SKILL_DIR / "parse_verdict.py")],
        input=WELL_FORMED, capture_output=True, text=True,
    )

    assert proc.returncode == 0
    assert json.loads(proc.stdout)["action"] == "merge"


def test_cli_exits_zero_on_garbage():
    # The parent must always get parseable JSON back, even for junk.
    proc = subprocess.run(
        [str(SKILL_DIR / "parse_verdict.py")],
        input="total garbage", capture_output=True, text=True,
    )

    assert proc.returncode == 0
    assert json.loads(proc.stdout)["valid"] is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_automerge.py -v`
Expected: collection error — `parse_verdict.py` does not exist yet.

- [ ] **Step 3: Write the implementation**

Create `.claude/skills/automerge/parse_verdict.py`:

```python
#!/usr/bin/env python3
"""Parse a reviewer subagent's verdict block into a validated decision.

Reads raw subagent output on stdin, writes one JSON object to stdout, and
always exits 0 — the caller must always get parseable JSON back, even for
garbage input.

This module owns the band boundaries. They are defined here and nowhere else:
duplicating them into a shell script or a prompt is how the two drift apart.
"""
import json
import re
import sys

MERGE_THRESHOLD = 80
NEEDS_WORK_THRESHOLD = 40

VERDICT_FOR_ACTION = {"merge": "MERGE", "comment": "COMMENT", "needs-work": "REJECT"}

_SCORE_RE = re.compile(r"^score:\s*(\S+)\s*$", re.MULTILINE)
_PR_RE = re.compile(r"^pr:\s*(\d+)\s*$", re.MULTILINE)
_VERDICT_RE = re.compile(r"^verdict:\s*(\S+)\s*$", re.MULTILINE)
_RISK_RE = re.compile(r"^risk:\s*(\S+)\s*$", re.MULTILINE)
_CONCERNS_RE = re.compile(r"^concerns:\s*(.*)$", re.MULTILINE)
_REASON_RE = re.compile(r"^\s*-\s+(.*\S)\s*$", re.MULTILINE)


def action_for_score(score: int) -> str:
    """Map a 0-100 score onto the action the parent will take."""
    if score >= MERGE_THRESHOLD:
        return "merge"
    if score >= NEEDS_WORK_THRESHOLD:
        return "comment"
    return "needs-work"


def _invalid(error: str) -> dict:
    """Every rejection path lands here: score 0, comment, never merge."""
    return {
        "pr": None, "score": 0, "action": "comment", "risk": "unknown",
        "reasons": [], "concerns": "review could not be parsed",
        "valid": False, "error": error,
    }


def parse_verdict(text: str) -> dict:
    """Parse the last verdict block in `text`, validating every field."""
    if not text or not text.strip():
        return _invalid("empty reviewer output")

    score_matches = list(_SCORE_RE.finditer(text))
    if not score_matches:
        return _invalid("no `score:` line found in reviewer output")

    # The reviewer may reconsider mid-output; the final block is its conclusion.
    tail = text[score_matches[-1].start():]

    raw_score = score_matches[-1].group(1)
    try:
        score = int(raw_score)
    except ValueError:
        return _invalid(f"score is not an integer: {raw_score!r}")
    if not 0 <= score <= 100:
        return _invalid(f"score out of range 0-100: {score}")

    reasons = _REASON_RE.findall(tail)
    if not reasons:
        return _invalid("no `reasons:` bullets found")

    verdict_match = _VERDICT_RE.search(tail)
    if not verdict_match:
        return _invalid("no `verdict:` line found")

    action = action_for_score(score)
    stated = verdict_match.group(1).upper()
    if stated != VERDICT_FOR_ACTION[action]:
        return _invalid(
            f"verdict {stated} contradicts score {score} "
            f"(expected {VERDICT_FOR_ACTION[action]})"
        )

    # `pr:` precedes `score:` inside a block, so look in the prefix — and take
    # the LAST match, which belongs to the same (final) block as the score.
    pr_matches = list(_PR_RE.finditer(text[: score_matches[-1].start()]))
    pr_match = pr_matches[-1] if pr_matches else None
    risk_match = _RISK_RE.search(tail)
    concerns_match = _CONCERNS_RE.search(tail)

    return {
        "pr": int(pr_match.group(1)) if pr_match else None,
        "score": score,
        "action": action,
        "risk": risk_match.group(1).lower() if risk_match else "unknown",
        "reasons": reasons,
        "concerns": concerns_match.group(1).strip() if concerns_match else "none",
        "valid": True,
        "error": None,
    }


def main() -> int:
    print(json.dumps(parse_verdict(sys.stdin.read())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Make it executable and run the tests**

```bash
chmod +x .claude/skills/automerge/parse_verdict.py
.venv/bin/pytest tests/test_automerge.py -v
```
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/automerge/parse_verdict.py tests/test_automerge.py
git commit -m "feat: add automerge verdict parser with band decision"
```

---

### Task 2: `candidates.sh` — select mergeable agent PRs

**Files:**
- Create: `.claude/skills/automerge/candidates.sh`
- Modify: `tests/test_automerge.py` (append)

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: a script taking no arguments, writing one JSON object to stdout:
  `{"candidates": [{"number": int, "title": str, "changedFiles": int, "additions": int}], "skipped": [{"number": int, "reason": str}], "truncated": int}`
  `SKILL.md` (Task 4) reads exactly these three keys.
- Honours `GH_REPO=owner/repo` to override remote auto-detection.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_automerge.py`. The `gh` binary is stubbed by putting a
fake `gh` first on `PATH`, so no network is touched:

```python
GH_STUB = """\
#!/usr/bin/env bash
# Fake `gh` for tests: echoes the canned JSON in $GH_STUB_JSON.
if [ "$1" = "pr" ] && [ "$2" = "list" ]; then
  cat "$GH_STUB_JSON"
  exit 0
fi
exit 1
"""


@pytest.fixture
def gh_stub(tmp_path):
    """Put a fake `gh` on PATH; returns a function to set its canned output."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "gh"
    stub.write_text(GH_STUB)
    stub.chmod(0o755)

    def run(pr_list):
        payload = tmp_path / "prs.json"
        payload.write_text(json.dumps(pr_list))
        env = {
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "GH_STUB_JSON": str(payload),
            "GH_REPO": "onpaj/harness",
        }
        proc = subprocess.run(
            [str(SKILL_DIR / "candidates.sh")],
            capture_output=True, text=True, env=env,
        )
        assert proc.returncode == 0, proc.stderr
        return json.loads(proc.stdout)

    return run


def _pr(number, **overrides):
    base = {
        "number": number, "title": f"PR {number}", "isDraft": False,
        "mergeable": "MERGEABLE", "reviewDecision": "APPROVED",
        "headRefName": f"feature/{number}-Thing", "additions": 10,
        "deletions": 2, "changedFiles": 2,
    }
    base.update(overrides)
    return base


def test_clean_pr_is_a_candidate(gh_stub):
    result = gh_stub([_pr(129)])

    assert [c["number"] for c in result["candidates"]] == [129]
    assert result["skipped"] == []
    assert result["truncated"] == 0


@pytest.mark.parametrize(
    "overrides,reason",
    [
        ({"isDraft": True}, "draft"),
        ({"mergeable": "CONFLICTING"}, "CONFLICTING"),
        ({"mergeable": "UNKNOWN"}, "UNKNOWN"),
        ({"reviewDecision": "CHANGES_REQUESTED"}, "CHANGES_REQUESTED"),
    ],
)
def test_ineligible_prs_are_skipped_with_a_reason(gh_stub, overrides, reason):
    result = gh_stub([_pr(112, **overrides)])

    assert result["candidates"] == []
    assert result["skipped"][0]["number"] == 112
    assert reason in result["skipped"][0]["reason"]


def test_empty_pr_list_yields_empty_candidates(gh_stub):
    result = gh_stub([])

    assert result["candidates"] == []
    assert result["skipped"] == []


def test_truncates_at_twenty_and_reports_the_remainder(gh_stub):
    result = gh_stub([_pr(n) for n in range(1, 26)])

    assert len(result["candidates"]) == 20
    assert result["truncated"] == 5
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_automerge.py -k candidate -v`
Expected: FAIL — `candidates.sh` does not exist.

- [ ] **Step 3: Write the implementation**

Create `.claude/skills/automerge/candidates.sh`:

```bash
#!/usr/bin/env bash
# List open `agent` PRs that are mechanically mergeable.
#
# Emits JSON: {"candidates": [...], "skipped": [...], "truncated": N}
#
# Eligibility here is fact, not judgement: a draft or conflicted PR cannot be
# merged by anyone, so it is filtered out before any subagent is spawned.
set -euo pipefail

AGENT_LABEL="agent"
MAX_CANDIDATES=20

REPO="${GH_REPO:-}"
if [ -z "$REPO" ]; then
  # Same convention as .claude/skills/applicationinsightsscan/gh-api.sh's
  # detect_repo(): parse `origin` directly rather than relying on gh's own
  # remote-resolution heuristics.
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

gh pr list \
  --repo "$REPO" \
  --state open \
  --label "$AGENT_LABEL" \
  --limit 100 \
  --json number,title,isDraft,mergeable,reviewDecision,headRefName,additions,deletions,changedFiles \
| jq --argjson max "$MAX_CANDIDATES" '
    def reason:
      if .isDraft then "draft"
      elif .mergeable == "CONFLICTING" then "CONFLICTING (merge conflicts)"
      elif .mergeable == "UNKNOWN" then "UNKNOWN (mergeability not computed, retry)"
      elif .mergeable != "MERGEABLE" then "not mergeable: \(.mergeable)"
      elif .reviewDecision == "CHANGES_REQUESTED" then "CHANGES_REQUESTED"
      else null end;

    (map(select(reason == null))          | sort_by(.number)) as $ok
  | (map(select(reason != null))
      | map({number, reason: reason})     | sort_by(.number)) as $skipped
  | {
      candidates: ($ok[:$max] | map({number, title, additions, changedFiles})),
      skipped: $skipped,
      truncated: (($ok | length) - $max | if . < 0 then 0 else . end)
    }
  '
```

- [ ] **Step 4: Make it executable and run the tests**

```bash
chmod +x .claude/skills/automerge/candidates.sh
.venv/bin/pytest tests/test_automerge.py -v
```
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/automerge/candidates.sh tests/test_automerge.py
git commit -m "feat: add automerge candidate selection script"
```

---

### Task 3: `apply_verdict.sh` — execute one action for one PR

**Files:**
- Create: `.claude/skills/automerge/apply_verdict.sh`
- Modify: `tests/test_automerge.py` (append)

**Interfaces:**
- Consumes: the `action` value produced by `parse_verdict.py` in Task 1 — one of `merge`, `comment`, `needs-work`. It never computes an action itself.
- Produces: a CLI
  `apply_verdict.sh --pr N --action ACTION --review-file PATH [--issue N]`
  writing `{"pr": N, "action": ACTION, "status": "ok"|"failed"|"skipped", "detail": str}` to stdout. Exit 0 on success, 1 on failure — the caller continues to the next PR either way.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_automerge.py`. The stub records each `gh` invocation to a
log file so the test can assert on the exact calls and their order:

```python
GH_RECORDER = """\
#!/usr/bin/env bash
# Fake `gh` that records its argv and optionally fails.
echo "$*" >> "$GH_LOG"
if [ -n "${GH_FAIL_ON:-}" ] && [[ "$*" == *"$GH_FAIL_ON"* ]]; then
  echo "simulated gh failure" >&2
  exit 1
fi
exit 0
"""


@pytest.fixture
def apply_runner(tmp_path):
    """Run apply_verdict.sh against a recording `gh` stub."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "gh"
    stub.write_text(GH_RECORDER)
    stub.chmod(0o755)

    log = tmp_path / "gh.log"
    review = tmp_path / "review.md"
    review.write_text("score: 94\nLooks good.\n")

    def run(action, pr=129, issue=None, fail_on=None):
        env = {
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "GH_LOG": str(log),
            "GH_REPO": "onpaj/harness",
        }
        if fail_on:
            env["GH_FAIL_ON"] = fail_on
        cmd = [
            str(SKILL_DIR / "apply_verdict.sh"),
            "--pr", str(pr), "--action", action,
            "--review-file", str(review),
        ]
        if issue:
            cmd += ["--issue", str(issue)]
        proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
        calls = log.read_text().splitlines() if log.exists() else []
        log.write_text("")
        return proc, calls

    return run


def test_merge_action_comments_then_merges_then_labels_issue(apply_runner):
    proc, calls = apply_runner("merge", pr=129, issue=118)

    assert proc.returncode == 0
    assert json.loads(proc.stdout)["status"] == "ok"
    # Order matters: the audit comment must land before the merge.
    assert "pr comment 129" in calls[0]
    assert "pr merge 129" in calls[1]
    assert "--squash" in calls[1] and "--delete-branch" in calls[1]
    assert "issue edit 118" in calls[2]
    assert "agent-merged" in calls[2]


def test_comment_action_only_comments(apply_runner):
    proc, calls = apply_runner("comment")

    assert proc.returncode == 0
    assert len(calls) == 1
    assert "pr comment 129" in calls[0]


def test_needs_work_action_comments_and_labels_the_pr(apply_runner):
    proc, calls = apply_runner("needs-work")

    assert proc.returncode == 0
    joined = "\n".join(calls)
    assert "pr comment 129" in joined
    assert "pr edit 129" in joined and "needs-work" in joined


def test_merge_without_issue_still_merges(apply_runner):
    proc, calls = apply_runner("merge", issue=None)

    assert proc.returncode == 0
    assert "pr merge 129" in "\n".join(calls)
    assert json.loads(proc.stdout)["detail"] != ""


def test_failed_merge_reports_json_and_exits_nonzero(apply_runner):
    proc, _ = apply_runner("merge", fail_on="pr merge")

    assert proc.returncode == 1
    payload = json.loads(proc.stdout)
    assert payload["status"] == "failed"
    assert payload["pr"] == 129


def test_unknown_action_is_rejected(apply_runner):
    proc, calls = apply_runner("delete-everything")

    assert proc.returncode == 1
    assert calls == []          # nothing was touched
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_automerge.py -k apply -v`
Expected: FAIL — `apply_verdict.sh` does not exist.

- [ ] **Step 3: Write the implementation**

Create `.claude/skills/automerge/apply_verdict.sh`:

```bash
#!/usr/bin/env bash
# Execute one already-decided action for one PR.
#
#   apply_verdict.sh --pr N --action merge|comment|needs-work \
#                    --review-file PATH [--issue N]
#
# This script does NOT decide anything — parse_verdict.py owns the thresholds.
# It executes the action it is handed, and reports what happened as JSON so the
# caller can continue to the next PR after a failure.
set -uo pipefail

MERGED_ISSUE_LABEL="agent-merged"
NEEDS_WORK_LABEL="needs-work"

PR=""; ACTION=""; REVIEW_FILE=""; ISSUE=""

while [ $# -gt 0 ]; do
  case "$1" in
    --pr)          PR="$2"; shift 2 ;;
    --action)      ACTION="$2"; shift 2 ;;
    --review-file) REVIEW_FILE="$2"; shift 2 ;;
    --issue)       ISSUE="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 1 ;;
  esac
done

report() {  # status, detail
  printf '{"pr":%s,"action":"%s","status":"%s","detail":"%s"}\n' \
    "${PR:-null}" "$ACTION" "$1" "$2"
}

fail() { report "failed" "$1"; exit 1; }

[ -n "$PR" ] || { echo "--pr is required" >&2; exit 1; }
[ -n "$REVIEW_FILE" ] && [ -f "$REVIEW_FILE" ] || { echo "--review-file must exist" >&2; exit 1; }

case "$ACTION" in
  merge|comment|needs-work) ;;
  *) echo "unknown action: $ACTION" >&2; exit 1 ;;
esac

REPO="${GH_REPO:-}"
if [ -z "$REPO" ]; then
  # Same convention as .claude/skills/applicationinsightsscan/gh-api.sh's
  # detect_repo(): parse `origin` directly rather than relying on gh's own
  # remote-resolution heuristics.
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

# Always post the review first: it is the audit trail for whatever follows.
gh pr comment "$PR" --repo "$REPO" --body-file "$REVIEW_FILE" \
  || fail "could not post review comment"

case "$ACTION" in
  comment)
    report "ok" "review posted, left for a human"
    ;;

  needs-work)
    # Label may not exist yet; creating it is best-effort and idempotent.
    gh label create "$NEEDS_WORK_LABEL" --repo "$REPO" --color d93f0b \
      --description "Agent review found blocking problems" >/dev/null 2>&1 || true
    gh pr edit "$PR" --repo "$REPO" --add-label "$NEEDS_WORK_LABEL" \
      || fail "could not add $NEEDS_WORK_LABEL label"
    report "ok" "review posted, flagged $NEEDS_WORK_LABEL"
    ;;

  merge)
    if ! merge_err=$(gh pr merge "$PR" --repo "$REPO" --squash --delete-branch 2>&1); then
      # A PR that went unmergeable between listing and merging is not an error
      # in this run — master simply moved underneath it.
      case "$merge_err" in
        *not\ mergeable*|*Merge\ conflict*|*conflict*)
          report "skipped" "became unmergeable before merge"; exit 1 ;;
        *)
          fail "merge failed: ${merge_err//\"/\'}" ;;
      esac
    fi
    if [ -n "$ISSUE" ]; then
      gh issue edit "$ISSUE" --repo "$REPO" --add-label "$MERGED_ISSUE_LABEL" \
        || fail "merged, but could not label issue #$ISSUE"
      report "ok" "squash-merged, branch deleted, issue #$ISSUE labelled"
    else
      report "ok" "squash-merged, branch deleted, no linked issue to label"
    fi
    ;;
esac
```

- [ ] **Step 4: Make it executable and run the tests**

```bash
chmod +x .claude/skills/automerge/apply_verdict.sh
.venv/bin/pytest tests/test_automerge.py -v
```
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/automerge/apply_verdict.sh tests/test_automerge.py
git commit -m "feat: add automerge verdict execution script"
```

---

### Task 4: `SKILL.md` — orchestration and the reviewer prompt

**Files:**
- Create: `.claude/skills/automerge/SKILL.md`

**Interfaces:**
- Consumes: `candidates.sh` (Task 2), `parse_verdict.py` (Task 1), `apply_verdict.sh` (Task 3) — exact CLIs as specified in those tasks.
- Produces: the `/automerge` skill entry point. No code depends on it.

- [ ] **Step 1: Write the skill file**

Create `.claude/skills/automerge/SKILL.md`:

````markdown
---
name: automerge
description: Review every open agent-created PR with a fresh subagent each and autonomously squash-merge the high-confidence ones. Use when the user says "automerge", "merge ready PRs", "review open PRs", "ship what's ready", or asks to clear the PR backlog without reviewing each one by hand.
---

You autonomously clear the pipeline's PR backlog. You find the open PRs the
AgentHarness pipeline produced, have each one reviewed in isolation, and merge
the ones the review is confident about — without asking the user for
confirmation.

**All deterministic work is done by the scripts beside this file.** Do not
re-implement their logic, re-derive the score thresholds, or hand-write `gh`
commands they already own. Your only judgement call is the review itself.

## 1. Find the candidates

```bash
.claude/skills/automerge/candidates.sh
```

This returns `{"candidates": [...], "skipped": [...], "truncated": N}`. Draft,
conflicted, and changes-requested PRs are already filtered out — do not
second-guess that filter or try to rescue a skipped PR.

If `candidates` is empty, print `No agent PRs ready to review.`, list the
`skipped` entries with their reasons, and stop.

## 2. Review each candidate — one subagent per PR

Spawn **one `code-reviewer` subagent per candidate PR, all in a single message**
so they run concurrently. Each gets a fresh context containing only its own PR.
Never review two PRs in one subagent: an earlier PR's reasoning bleeds into the
next one's score.

Give each subagent exactly this prompt, with `{N}` replaced by the PR number:

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

## 3. Parse each verdict

For each subagent's output, write it to a file and run it through the parser —
never read the score off the block yourself:

```bash
printf '%s' "$SUBAGENT_OUTPUT" > /tmp/automerge-review-{N}.md
.claude/skills/automerge/parse_verdict.py < /tmp/automerge-review-{N}.md
```

The parser owns the thresholds and returns the `action` to take. A malformed or
self-contradictory review comes back `"valid": false` with
`"action": "comment"` — that is correct and final. **Never override it into a
merge.**

## 4. Apply each verdict — serially

Process PRs one at a time, in ascending PR number, so two merges never race on
`master`:

```bash
.claude/skills/automerge/apply_verdict.sh \
  --pr {N} --action {action} --review-file /tmp/automerge-review-{N}.md --issue {issue}
```

Pass `--issue` only when the PR body links one (`Closes #<n>`). The script
returns JSON; a non-zero exit means that PR failed. **Continue to the next PR
regardless** — one failure never aborts the batch.

## 5. Report

Print a table of every PR: number, score, verdict, action taken. Then list:

- `skipped` from step 1, with reasons
- any PR whose review was unparseable
- any `apply_verdict.sh` failure, with its `detail`
- if `truncated` > 0, state exactly how many PRs were left unprocessed

The user reads only this report. It must say what was *not* done as clearly as
what was — a report that quietly omits a truncated tail reads as "everything is
handled" when it is not.

## Constants

Do not restate these values elsewhere; each lives in exactly one file.

| Constant | Where it lives |
|----------|----------------|
| `MERGE_THRESHOLD` (80), `NEEDS_WORK_THRESHOLD` (40) | `parse_verdict.py` |
| `MAX_CANDIDATES` (20), `AGENT_LABEL` | `candidates.sh` |
| `MERGED_ISSUE_LABEL`, `NEEDS_WORK_LABEL` | `apply_verdict.sh` |

## Limits worth knowing

This skill merges without running the test suite — every score comes from
reading a diff. It is deliberately conservative (threshold 80, uncertainty costs
score), but it can merge a change that reads correctly and is not. There is also
no confirmation prompt. Watch the first few runs.
````

- [ ] **Step 2: Verify the skill is discoverable**

```bash
.venv/bin/pytest tests/test_packaged_skills.py -v
```
Expected: `test_ships_the_full_skill_set` and `test_packaged_skills_match_their_source` **FAIL** — `automerge` exists in `.claude/skills/` but not yet in `agentharness/data/skills/`. This failure is expected here and is fixed in Task 5.

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/automerge/SKILL.md
git commit -m "feat: add automerge skill orchestration and reviewer prompt"
```

---

### Task 5: Package the skill for `agentharness init`

**Files:**
- Create: `agentharness/data/skills/automerge/` (copy of `.claude/skills/automerge/`)

**Interfaces:**
- Consumes: every file created in Tasks 1-4.
- Produces: nothing new — makes the existing packaging tests pass.

- [ ] **Step 1: Confirm the packaging tests currently fail**

Run: `.venv/bin/pytest tests/test_packaged_skills.py -v`
Expected: FAIL — `packaged skills must mirror .claude/skills exactly`.

- [ ] **Step 2: Copy the skill as real files**

`cp -R` (not a symlink — symlinks ship nothing from a pip install, which
`test_data_skills_is_not_a_symlink` enforces):

```bash
rm -rf agentharness/data/skills/automerge
cp -R .claude/skills/automerge agentharness/data/skills/automerge
```

- [ ] **Step 3: Run the packaging tests**

Run: `.venv/bin/pytest tests/test_packaged_skills.py -v`
Expected: all PASS.

- [ ] **Step 4: Run the whole suite**

Run: `.venv/bin/pytest tests/ -v`
Expected: all PASS — no existing test regressed.

- [ ] **Step 5: Commit**

```bash
git add agentharness/data/skills/automerge
git commit -m "feat: package automerge skill for agentharness init"
```

---

### Task 6: Document the skill and verify end-to-end

**Files:**
- Modify: `CLAUDE.md` (the "Claude Code skills" table)

**Interfaces:**
- Consumes: the finished skill.
- Produces: nothing code depends on.

- [ ] **Step 1: Add the skill to the CLAUDE.md skills table**

In `CLAUDE.md`, find the `## Claude Code skills` table and add a row after the
`/oneshot` row:

```markdown
| `/automerge` | PR backlog | Reviews every open `agent` PR with a fresh subagent each, squash-merges those scoring ≥ 80, comments on the rest |
```

- [ ] **Step 2: Dry-run candidate selection against the live repo**

This is read-only — it lists PRs and merges nothing:

```bash
.claude/skills/automerge/candidates.sh
```
Expected: valid JSON. With the repo in its current state the `candidates` list
will likely be **empty**, because the one open PR (#112) is `CONFLICTING` and
carries no `agent` label. An empty result here is a correct result, not a bug —
it confirms the filter rejects exactly what it should.

- [ ] **Step 3: Verify the parser end-to-end from the shell**

```bash
printf 'pr: 1\nscore: 85\nverdict: MERGE\nrisk: low\nreasons:\n  - docs only\nconcerns: none\n' \
  | .claude/skills/automerge/parse_verdict.py
```
Expected: `{"pr": 1, "score": 85, "action": "merge", ...  "valid": true, ...}`

- [ ] **Step 4: Run the full suite one final time**

Run: `.venv/bin/pytest tests/ -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: document the automerge skill"
```

---

## Self-review notes

**Spec coverage:** Component 1 → Task 2. Component 2 (reviewer subagent, rubric,
output contract) → Task 4. Component 3 (parsing, validation, bands) → Task 1.
Component 4 (actions, error handling, report) → Tasks 3 and 4. Component 5
dropped — `oneshot`'s `ensure_pr_linked.sh` already guarantees the `agent`
label. Component 6 (packaging) → Task 5. Testing section → Tasks 1-3, plus the
Task 6 end-to-end checks.

**Known deviation from the spec:** the spec's testing section put
`tests/test_automerge.py` tests for all three scripts in one file; this plan
does that, building the file incrementally across Tasks 1-3 rather than writing
it all up front, so each task has its own red-green cycle.
