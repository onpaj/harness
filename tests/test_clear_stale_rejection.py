"""Tests for rework-pr/clear_stale_rejection.sh and hygiene-pr's --check-only.

A PR rejected `still-failing` on a false reading of CI (superseded CANCELLED
runs) used to burn all MAX_REVISION_ATTEMPTS on revisions with nothing to
fix. Before reworking, the rejection is re-checked against live CI.
"""
import json
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CLEAR = REPO_ROOT / ".claude" / "skills" / "rework-pr" / "clear_stale_rejection.sh"
CHECK = REPO_ROOT / ".claude" / "skills" / "hygiene-pr" / "update_and_wait.sh"

GH_STUB = """\
#!/usr/bin/env bash
echo "$*" >> "$GH_STATE/calls.log"
case "$1 $2" in
  "api --paginate") cat "$GH_STATE/comments.json" ;;
  "pr view") cat "$GH_STATE/pr.json" ;;
  "pr comment") exit 0 ;;
  "pr edit") exit 0 ;;
  *) echo "unexpected: $*" >&2; exit 1 ;;
esac
"""

HYGIENE_REJECT = (
    "Hygiene check found this PR cannot be merged as-is.\n\npr: 5\nscore: 0\n"
    "verdict: REJECT\nrisk: high\nreasons:\n  - {status}: {detail}\n"
    "concerns: needs a human, or /rework-pr, to resolve\n"
)


def _pr(checks, mergeable="MERGEABLE", merge_state="CLEAN"):
    return {"mergeable": mergeable, "mergeStateStatus": merge_state,
            "statusCheckRollup": checks, "baseRefName": "master", "headRefName": "feature/x"}


GREEN = [{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "SUCCESS"}]
RED = [{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "FAILURE"}]
RUNNING = [{"__typename": "CheckRun", "status": "IN_PROGRESS", "conclusion": None}]


@pytest.fixture
def run(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "gh").write_text(GH_STUB)
    (bin_dir / "gh").chmod(0o755)
    state = tmp_path / "state"
    state.mkdir()

    def go(script, args, comments=None, checks=GREEN):
        (state / "comments.json").write_text(json.dumps([{"body": b} for b in (comments or [])]))
        (state / "pr.json").write_text(json.dumps(_pr(checks)))
        (state / "calls.log").write_text("")
        proc = subprocess.run(
            [str(script), *args], capture_output=True, text=True, cwd=REPO_ROOT,
            env={"PATH": f"{bin_dir}:/usr/bin:/bin", "GH_STATE": str(state), "GH_REPO": "onpaj/harness"},
        )
        assert proc.returncode == 0, proc.stderr
        return json.loads(proc.stdout), (state / "calls.log").read_text()

    return go


CI_REJECT = HYGIENE_REJECT.format(status="still-failing", detail="branch is current with base, but checks are failing")


def test_green_ci_clears_a_stale_ci_rejection(run):
    out, calls = run(CLEAR, ["--pr", "5"], comments=[CI_REJECT], checks=GREEN)
    assert out["status"] == "cleared"
    assert "--remove-label needs-work" in calls
    assert "pr comment 5" in calls


def test_still_red_ci_keeps_the_rejection(run):
    out, calls = run(CLEAR, ["--pr", "5"], comments=[CI_REJECT], checks=RED)
    assert out["status"] == "holds"
    assert "--remove-label" not in calls


def test_running_ci_does_not_clear(run):
    out, calls = run(CLEAR, ["--pr", "5"], comments=[CI_REJECT], checks=RUNNING)
    assert out["status"] == "pending"
    assert "--remove-label" not in calls


def test_a_code_review_rejection_is_never_cleared_by_green_ci(run):
    review = "pr: 5\nscore: 40\nverdict: REJECT\nrisk: high\nreasons:\n  - tests missing\n"
    out, calls = run(CLEAR, ["--pr", "5"], comments=[review], checks=GREEN)
    assert out["status"] == "not-applicable"
    assert "--remove-label" not in calls


def test_the_latest_rejection_decides(run):
    conflict = HYGIENE_REJECT.format(status="conflict", detail="could not resolve")
    out, _ = run(CLEAR, ["--pr", "5"], comments=[CI_REJECT, conflict], checks=GREEN)
    assert out["status"] == "not-applicable"


def test_no_rejection_comment_is_not_applicable(run):
    out, _ = run(CLEAR, ["--pr", "5"], comments=["just chatting"], checks=GREEN)
    assert out["status"] == "not-applicable"


@pytest.mark.parametrize("checks,expected", [(GREEN, "already-clean"), (RED, "still-failing"), (RUNNING, "ci-running")])
def test_check_only_reports_without_side_effects(run, checks, expected):
    out, calls = run(CHECK, ["--pr", "5", "--check-only"], checks=checks)
    assert out["status"] == expected
    assert "update-branch" not in calls
    assert "--add-label" not in calls
    assert "pr comment" not in calls
