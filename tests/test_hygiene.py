"""Tests for the /hygiene-pr skill script."""
import json
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO_ROOT / ".claude" / "skills" / "hygiene-pr"

GH_STUB = """\
#!/usr/bin/env bash
# Fake `gh` for hygiene-pr tests.
#   `pr view` serves canned JSON from $GH_STUB_VIEW_DIR/{1,2,3,...}.json,
#   advancing one file per call and repeating the last file once exhausted,
#   or fails with $GH_STUB_VIEW_ERR when $GH_STUB_VIEW_EXIT is non-zero.
#   `pr update-branch` succeeds/fails per $GH_STUB_UPDATE_BRANCH_EXIT.
#   `api repos/.../compare/...` echoes $GH_STUB_BEHIND_BY (the --jq the
#   script passes already reduces the payload to that one number).
#   `label create`/`pr comment`/`pr edit` are what apply_verdict.sh calls
#   when update_and_wait.sh flags a PR needs-work — all succeed by default;
#   `pr edit` fails per $GH_STUB_LABEL_EDIT_EXIT. `pr comment`'s
#   --body-file content is copied to $GH_STUB_COMMENT_BODY when set, so
#   tests can assert on the posted comment.
# Every call is recorded to $GH_STUB_LOG for assertions.
echo "$*" >> "$GH_STUB_LOG"
if [ "$1" = "pr" ] && [ "$2" = "view" ]; then
  if [ "${GH_STUB_VIEW_EXIT:-0}" != "0" ]; then
    echo "${GH_STUB_VIEW_ERR:-simulated gh pr view failure}" >&2
    exit "$GH_STUB_VIEW_EXIT"
  fi
  n=$(( $(cat "$GH_STUB_COUNTER" 2>/dev/null || echo 0) + 1 ))
  echo "$n" > "$GH_STUB_COUNTER"
  max=$(ls "$GH_STUB_VIEW_DIR" | wc -l | tr -d ' ')
  [ "$n" -gt "$max" ] && n="$max"
  cat "$GH_STUB_VIEW_DIR/$n.json"
  exit 0
fi
if [ "$1" = "api" ] && [[ "$2" == *"/compare/"* ]]; then
  echo "${GH_STUB_BEHIND_BY:-0}"
  exit 0
fi
if [ "$1" = "pr" ] && [ "$2" = "update-branch" ]; then
  if [ "${GH_STUB_UPDATE_BRANCH_EXIT:-0}" = "0" ]; then
    exit 0
  fi
  echo "${GH_STUB_UPDATE_BRANCH_ERR:-simulated update-branch failure}" >&2
  exit 1
fi
if [ "$1" = "label" ] && [ "$2" = "create" ]; then
  exit 0
fi
if [ "$1" = "pr" ] && [ "$2" = "comment" ]; then
  prev=""
  for arg in "$@"; do
    if [ "$prev" = "--body-file" ] && [ -n "${GH_STUB_COMMENT_BODY:-}" ]; then
      cp "$arg" "$GH_STUB_COMMENT_BODY"
    fi
    prev="$arg"
  done
  exit 0
fi
if [ "$1" = "pr" ] && [ "$2" = "edit" ]; then
  if [ "${GH_STUB_LABEL_EDIT_EXIT:-0}" != "0" ]; then
    echo "${GH_STUB_LABEL_EDIT_ERR:-simulated label edit failure}" >&2
    exit "$GH_STUB_LABEL_EDIT_EXIT"
  fi
  exit 0
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

    comment_body = tmp_path / "comment_body.md"

    def run(view_sequence, pr=129, update_branch_exit=0, update_branch_err=None,
             max_attempts=5, interval=0, behind_by=0, view_exit=0, view_err=None,
             label_edit_exit=0, label_edit_err=None, force=False):
        for i, payload in enumerate(view_sequence, start=1):
            (view_dir / f"{i}.json").write_text(json.dumps(payload))
        env = {
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "GH_STUB_VIEW_DIR": str(view_dir),
            "GH_STUB_LOG": str(log),
            "GH_STUB_COUNTER": str(counter),
            "GH_STUB_UPDATE_BRANCH_EXIT": str(update_branch_exit),
            "GH_STUB_BEHIND_BY": str(behind_by),
            "GH_STUB_VIEW_EXIT": str(view_exit),
            "GH_STUB_LABEL_EDIT_EXIT": str(label_edit_exit),
            "GH_STUB_COMMENT_BODY": str(comment_body),
            "GH_REPO": "onpaj/harness",
            "HYGIENE_POLL_INTERVAL_SECONDS": str(interval),
            "HYGIENE_POLL_MAX_ATTEMPTS": str(max_attempts),
        }
        if update_branch_err:
            env["GH_STUB_UPDATE_BRANCH_ERR"] = update_branch_err
        if view_err:
            env["GH_STUB_VIEW_ERR"] = view_err
        if label_edit_err:
            env["GH_STUB_LABEL_EDIT_ERR"] = label_edit_err
        cmd = [str(SKILL_DIR / "update_and_wait.sh"), "--pr", str(pr)]
        if force:
            cmd.append("--force")
        proc = subprocess.run(
            cmd, capture_output=True, text=True, env=env, cwd=REPO_ROOT,
        )
        assert proc.returncode == 0, proc.stderr
        result = json.loads(proc.stdout)
        result["_gh_calls"] = log.read_text().splitlines() if log.exists() else []
        result["_comment_body"] = comment_body.read_text() if comment_body.exists() else None
        return result

    return run


def _view(mergeable="MERGEABLE", merge_state="CLEAN", checks=None,
          base_ref="master", head_ref="feature/x"):
    return {
        "mergeable": mergeable,
        "mergeStateStatus": merge_state,
        "baseRefName": base_ref,
        "headRefName": head_ref,
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


def test_gh_pr_view_failure_reports_error_without_polling(hygiene_runner):
    # A failed `gh pr view` used to be swallowed by process substitution:
    # every variable came back empty, no branch matched, and the script
    # spent the full poll window before reporting a false `pending-timeout`.
    result = hygiene_runner(
        [_view()], view_exit=1, view_err="gh: authentication token expired",
        max_attempts=40,
    )

    assert result["status"] == "error"
    assert "authentication token expired" in result["detail"]
    # Fails fast: exactly one `pr view`, and no branch update attempted.
    assert len([c for c in result["_gh_calls"] if c.startswith("pr view")]) == 1
    assert not any("update-branch" in c for c in result["_gh_calls"])


def test_behind_by_from_compare_api_triggers_update_even_when_state_is_clean(
    hygiene_runner,
):
    # GitHub only reports mergeStateStatus=BEHIND when the base branch
    # requires branches to be up to date. On an unprotected base branch the
    # compare API's behind_by is the only staleness signal there is.
    pending = [{"__typename": "CheckRun", "status": "IN_PROGRESS", "conclusion": None}]
    success = [{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "SUCCESS"}]
    result = hygiene_runner(
        [_view(merge_state="CLEAN", checks=pending), _view(checks=success)],
        behind_by=4,
    )

    assert result["status"] == "fixed"
    assert any("update-branch" in c for c in result["_gh_calls"])
    assert any(c.startswith("api repos/onpaj/harness/compare/") for c in result["_gh_calls"])


def test_both_signals_agree_branch_is_current_so_no_update_is_made(hygiene_runner):
    result = hygiene_runner([_view(merge_state="CLEAN")], behind_by=0)

    assert result["status"] == "already-clean"
    assert not any("update-branch" in c for c in result["_gh_calls"])


def test_compare_api_is_only_consulted_once_not_per_poll(hygiene_runner):
    pending = [{"__typename": "CheckRun", "status": "IN_PROGRESS", "conclusion": None}]
    result = hygiene_runner(
        [_view(merge_state="BEHIND", checks=pending)] + [_view(checks=pending)] * 3,
        max_attempts=3,
    )

    assert result["status"] == "pending-timeout"
    compare_calls = [c for c in result["_gh_calls"] if "/compare/" in c]
    assert len(compare_calls) == 1


def test_not_behind_but_ci_running_short_circuits_without_touching_branch(hygiene_runner):
    # Not behind/conflicting, but CI is already mid-flight from some earlier
    # push this run had nothing to do with — must not update-branch (that
    # would cancel it for no benefit) or poll; just report and let the
    # caller retry later.
    pending = [{"__typename": "CheckRun", "status": "IN_PROGRESS", "conclusion": None}]
    success = [{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "SUCCESS"}]
    result = hygiene_runner([_view(checks=pending), _view(checks=success)])

    assert result["status"] == "ci-running"
    assert not any("update-branch" in c for c in result["_gh_calls"])
    # Only the initial read — no polling happened.
    assert len([c for c in result["_gh_calls"] if c.startswith("pr view")]) == 1


def test_force_polls_through_ci_running_when_not_behind(hygiene_runner):
    # --force overrides the ci-running bailout: since there's nothing to
    # merge (not behind/conflicting), it never calls update-branch either —
    # it just polls the already-running CI through to resolution instead of
    # bailing out immediately.
    pending = [{"__typename": "CheckRun", "status": "IN_PROGRESS", "conclusion": None}]
    success = [{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "SUCCESS"}]
    result = hygiene_runner([_view(checks=pending), _view(checks=success)], force=True)

    assert result["status"] == "fixed"
    assert "already current" in result["detail"]
    assert not any("update-branch" in c for c in result["_gh_calls"])


def test_force_still_updates_and_cancels_running_ci_when_behind(hygiene_runner):
    # --force does not change the behind/conflicting path at all — it was
    # already going to update-branch (and thus cancel whatever CI was
    # running on the stale head) regardless of --force.
    pending = [{"__typename": "CheckRun", "status": "IN_PROGRESS", "conclusion": None}]
    success = [{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "SUCCESS"}]
    result = hygiene_runner(
        [_view(merge_state="BEHIND", checks=pending), _view(checks=success)], force=True,
    )

    assert result["status"] == "fixed"
    assert "branch updated" in result["detail"]
    assert any("update-branch" in c for c in result["_gh_calls"])


def test_missing_pr_argument_is_rejected():
    proc = subprocess.run(
        [str(SKILL_DIR / "update_and_wait.sh")], capture_output=True, text=True,
    )
    assert proc.returncode == 1


# === needs-work flagging: still-failing/conflict get a durable trail ===
#
# hygiene-pr/hygiene-all must be runnable independent of /automerge-pr, but
# a standalone run that finds still-failing/conflict used to leave zero
# trace — invisible to /rework-pr's candidate search and to a human unless
# they were staring at that one report. These flag needs-work via the same
# apply_verdict.sh mechanism /automerge-pr uses for a code-review rejection.


def test_still_failing_flags_needs_work_and_comments(hygiene_runner):
    checks = [{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "FAILURE"}]
    result = hygiene_runner([_view(checks=checks)])

    assert result["status"] == "still-failing"
    joined = "\n".join(result["_gh_calls"])
    assert "label create" in joined
    assert "pr comment 129" in joined
    assert "pr edit 129" in joined and "needs-work" in joined
    assert result["_comment_body"] is not None
    assert re.search(r"verdict:\s*REJECT", result["_comment_body"])
    assert "still-failing" in result["_comment_body"]


def test_conflict_flags_needs_work_and_comments(hygiene_runner):
    result = hygiene_runner(
        [_view(mergeable="CONFLICTING", merge_state="DIRTY")],
        update_branch_exit=1, update_branch_err="merge conflict",
    )

    assert result["status"] == "conflict"
    joined = "\n".join(result["_gh_calls"])
    assert "pr edit 129" in joined and "needs-work" in joined
    assert result["_comment_body"] is not None
    assert re.search(r"verdict:\s*REJECT", result["_comment_body"])
    assert "merge conflict" in result["_comment_body"]


def test_already_clean_does_not_touch_labels(hygiene_runner):
    result = hygiene_runner([_view()])

    assert result["status"] == "already-clean"
    joined = "\n".join(result["_gh_calls"])
    assert "pr comment" not in joined and "pr edit" not in joined


def test_fixed_does_not_touch_labels(hygiene_runner):
    pending = [{"__typename": "CheckRun", "status": "IN_PROGRESS", "conclusion": None}]
    success = [{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "SUCCESS"}]
    result = hygiene_runner([
        _view(merge_state="BEHIND", checks=pending), _view(checks=success),
    ])

    assert result["status"] == "fixed"
    joined = "\n".join(result["_gh_calls"])
    assert "pr comment" not in joined and "pr edit" not in joined


def test_pending_timeout_does_not_touch_labels(hygiene_runner):
    pending = [{"__typename": "CheckRun", "status": "IN_PROGRESS", "conclusion": None}]
    result = hygiene_runner(
        [_view(merge_state="BEHIND", checks=pending)] + [_view(checks=pending)] * 3,
        max_attempts=2,
    )

    assert result["status"] == "pending-timeout"
    joined = "\n".join(result["_gh_calls"])
    assert "pr comment" not in joined and "pr edit" not in joined


def test_error_does_not_touch_labels(hygiene_runner):
    result = hygiene_runner([_view()], view_exit=1, view_err="auth expired")

    assert result["status"] == "error"
    joined = "\n".join(result["_gh_calls"])
    assert "pr comment" not in joined and "pr edit" not in joined


def test_needs_work_flag_failure_is_noted_but_status_is_still_reported(hygiene_runner):
    # A labelling failure must not mask the underlying hygiene finding —
    # still-failing is real regardless of whether the flag landed.
    checks = [{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "FAILURE"}]
    result = hygiene_runner(
        [_view(checks=checks)],
        label_edit_exit=1, label_edit_err="simulated label API outage",
    )

    assert result["status"] == "still-failing"
    assert "could not flag needs-work" in result["detail"]
    assert "simulated label API outage" in result["detail"]


def test_hygiene_needs_work_block_emits_a_countable_verdict_line():
    # rework-pr/find_candidate.sh and list_candidates.sh count a PR's prior
    # rejections toward MAX_REVISION_ATTEMPTS by matching comment bodies
    # against `verdict:\s*REJECT`. The needs-work block this script writes
    # must keep emitting that pattern, or a PR with a permanently broken
    # build bounces between hygiene/automerge-pr and /rework-pr forever
    # without ever hitting the cap.
    script = (SKILL_DIR / "update_and_wait.sh").read_text()

    marker = "Hygiene check found this PR cannot be merged as-is"
    assert marker in script, "needs-work verdict block is gone or was reworded"
    block = script[script.index(marker):]
    block = block[: block.index("concerns:")]

    assert re.search(r"verdict:\s*REJECT", block), (
        "needs-work block no longer emits a `verdict: REJECT` line; "
        "rework-pr's revision-attempt cap would stop counting it"
    )
