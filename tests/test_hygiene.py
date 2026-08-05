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
