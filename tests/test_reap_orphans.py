"""Tests for .claude/skills/_lib/reap_orphans.sh — the sweeper for pipeline
runs whose GitHub issue was closed out from under them.

Every stage's candidate selection queries `--state open` only, which is
correct for picking work but means a CLOSED issue still carrying an
in-flight stage label leaves the world silently: nothing ever looks at that
issue/branch/PR pair again, and its draft PR is invisible to `automerge-*`,
`hygiene-*` and `rework-*` (all of which skip drafts). The reaper is the one
pass that looks for that gap.

Its central safety property is that it must never close a branch carrying
real work. "Real work" cannot be read off commit messages — implementation
commits use the same `chore(feat-N):` prefix planning artifacts do — so the
signal is changed paths: a run that never reached implementation touches
nothing outside `artifacts/feat-{N}/`.
"""
import json
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
REAPER = REPO_ROOT / ".claude" / "skills" / "_lib" / "reap_orphans.sh"

READY = "agent-ready-for-dev"
IMPLEMENTING = "agent-implementing"
PLANNING = "agent-planning"

# Serves canned `gh` responses out of files keyed by label / issue number and
# logs every invocation so the tests can assert on which writes did and did
# not happen. Reads exit 1 when the fixture is absent (the way `gh pr view`
# fails for a branch with no PR); writes always succeed.
GH_STUB = """\
#!/usr/bin/env bash
echo "$*" >> "$REAP_STUB_LOG"
if [ "$1" = "issue" ] && [ "$2" = "list" ]; then
  label=""
  for a in "$@"; do
    if [ "$prev" = "--label" ]; then label="$a"; fi
    prev="$a"
  done
  file="$REAP_STUB_CLOSED_DIR/$label.json"
  if [ -f "$file" ]; then cat "$file"; else echo "[]"; fi
  exit 0
fi
# A PR ref is either a bare number or a head branch; both must land on the
# same canonical fixture, so the tests can tell which one the reaper used.
_pr_file() {
  if [[ "$1" =~ ^[0-9]+$ ]]; then
    echo "$REAP_STUB_PRS_DIR/pr-$1.json"
    return
  fi
  local issue ptr
  issue=$(echo "$1" | sed -E 's#^feature/([0-9]+)-.*#\\1#')
  ptr="$REAP_STUB_PRS_DIR/branch-$issue"
  if [ -f "$ptr" ]; then echo "$REAP_STUB_PRS_DIR/pr-$(cat "$ptr").json"; fi
}
if [ "$1" = "pr" ] && [ "$2" = "close" ]; then
  if [ -n "${REAP_STUB_CLOSE_FAILS:-}" ]; then
    echo "could not close pull request" >&2
    exit 1
  fi
  file=$(_pr_file "$3")
  if [ -n "$file" ] && [ -f "$file" ]; then
    /usr/bin/sed -i.bak 's/"state": "OPEN"/"state": "CLOSED"/' "$file"
  fi
  exit 0
fi
if [ "$1" = "pr" ] && [ "$2" = "view" ]; then
  if [ -n "${REAP_STUB_PR_VIEW_ERROR:-}" ]; then
    echo "error connecting to api.github.com" >&2
    exit 1
  fi
  file=$(_pr_file "$3")
  if [ -n "$file" ] && [ -f "$file" ]; then cat "$file"; exit 0; fi
  echo "no pull requests found for branch $3" >&2
  exit 1
fi
if [ "$1" = "api" ]; then
  if [ -n "${REAP_STUB_COMMIT_ERROR:-}" ]; then
    echo '{"message":"Server Error"}'
    exit 1
  fi
  n=$(echo "$*" | grep -oE 'commits/[^ ]+' | sed 's#commits/##')
  file="$REAP_STUB_COMMITS_DIR/$n.json"
  if [ -f "$file" ]; then cat "$file"; else echo '{"commit":{"committer":{"date":"1970-01-01T00:00:00Z"}}}'; fi
  exit 0
fi
exit 0
"""

GIT_STUB = """\
#!/usr/bin/env bash
echo "$*" >> "$REAP_STUB_LOG"
if [ "$1" = "ls-remote" ]; then
  if [ -n "${REAP_STUB_LS_REMOTE_FAILS:-}" ]; then
    echo "fatal: could not read from remote repository" >&2
    exit 128
  fi
  n=$(echo "$*" | grep -oE 'feature/[0-9]+' | grep -oE '[0-9]+')
  file="$REAP_STUB_BRANCHES_DIR/$n"
  if [ -f "$file" ]; then
    while IFS= read -r b || [ -n "$b" ]; do
      [ -n "$b" ] && echo "deadbeef refs/heads/$b"
    done < "$file"
  fi
  exit 0
fi
exec /usr/bin/git "$@"
"""

NOW = "2026-09-10T12:00:00Z"
LONG_AGO = "2026-09-01T12:00:00Z"
JUST_NOW = "2026-09-10T11:58:00Z"


def _issue(number, created="2026-08-29T09:00:00Z"):
    return {"number": number, "title": f"issue {number}", "createdAt": created}


def _pr(number, files, changed_files=None, state="OPEN", is_draft=True):
    return {
        "number": number,
        "state": state,
        "isDraft": is_draft,
        "changedFiles": len(files) if changed_files is None else changed_files,
        "files": [{"path": p} for p in files],
    }


def _artifact_files(issue):
    return [
        f"artifacts/feat-{issue}/spec.r1.md",
        f"artifacts/feat-{issue}/design.r1.md",
        f"artifacts/feat-{issue}/task-plan.r1.md",
        f"artifacts/feat-{issue}/state.json",
    ]


@pytest.fixture
def reaper(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "gh").write_text(GH_STUB)
    (bin_dir / "gh").chmod(0o755)
    (bin_dir / "git").write_text(GIT_STUB)
    (bin_dir / "git").chmod(0o755)
    closed_dir = tmp_path / "closed"
    closed_dir.mkdir()
    prs_dir = tmp_path / "prs"
    prs_dir.mkdir()
    commits_dir = tmp_path / "commits"
    commits_dir.mkdir()
    branches_dir = tmp_path / "branches"
    branches_dir.mkdir()
    log = tmp_path / "reap.log"

    def run(closed=None, prs=None, branches=None, commit_dates=None,
            args=(), stale_minutes=None, now_override=NOW, close_fails=False,
            fail=None):
        for label, issues in (closed or {}).items():
            (closed_dir / f"{label}.json").write_text(
                issues if isinstance(issues, str) else json.dumps(issues))
        for issue, pr in (prs or {}).items():
            (prs_dir / f"pr-{pr['number']}.json").write_text(json.dumps(pr))
            (prs_dir / f"branch-{issue}").write_text(str(pr["number"]))
        for issue, branch in (branches or {}).items():
            names = [branch] if isinstance(branch, str) else list(branch)
            (branches_dir / str(issue)).write_text("\n".join(names) + "\n")
        for ref, iso in (commit_dates or {}).items():
            path = commits_dir / f"{ref}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"commit": {"committer": {"date": iso}}}))
        env = {
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "REAP_STUB_LOG": str(log),
            "REAP_STUB_CLOSED_DIR": str(closed_dir),
            "REAP_STUB_PRS_DIR": str(prs_dir),
            "REAP_STUB_COMMITS_DIR": str(commits_dir),
            "REAP_STUB_BRANCHES_DIR": str(branches_dir),
            "GH_REPO": "onpaj/harness",
            "NOW_OVERRIDE": now_override,
        }
        if stale_minutes is not None:
            env["STALE_MINUTES"] = str(stale_minutes)
        if close_fails:
            env["REAP_STUB_CLOSE_FAILS"] = "1"
        if fail == "ls-remote":
            env["REAP_STUB_LS_REMOTE_FAILS"] = "1"
        elif fail == "pr-view":
            env["REAP_STUB_PR_VIEW_ERROR"] = "1"
        elif fail == "commit":
            env["REAP_STUB_COMMIT_ERROR"] = "1"
        proc = subprocess.run(
            [str(REAPER), *args], capture_output=True, text=True, env=env,
            cwd=REPO_ROOT,
        )
        return proc, (log.read_text() if log.exists() else "")

    return run


def _orphans(proc):
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)["orphans"]


def _by_number(proc, number):
    matches = [o for o in _orphans(proc) if o["number"] == number]
    assert matches, f"issue #{number} not in output: {proc.stdout}"
    return matches[0]


# === the empty case ===


def test_reports_no_orphans_when_every_stage_label_pool_is_empty(reaper):
    proc, log = reaper()

    assert _orphans(proc) == []
    assert "pr close" not in log
    assert "issue edit" not in log


def test_queries_every_in_flight_stage_label_not_just_the_implementing_pair(reaper):
    # An `agent-planning` issue closed externally strands exactly the same
    # way an `agent-ready-for-dev` one does — plan-next-task's own candidate
    # selection is `--state open` too.
    proc, log = reaper()

    for label in (PLANNING, READY, IMPLEMENTING):
        assert f"--label {label}" in log, f"{label} pool never queried"
    assert "--state closed" in log


# === the reap: an artifact-only branch is safe to close ===


def test_closes_the_pr_of_an_artifact_only_orphan(reaper):
    proc, log = reaper(
        closed={READY: [_issue(3972)]},
        branches={3972: "feature/3972-widget"},
        prs={3972: _pr(3982, _artifact_files(3972))},
        commit_dates={"feature/3972-widget": LONG_AGO},
    )

    assert _by_number(proc, 3972)["action"] == "closed"
    assert _by_number(proc, 3972)["pr"] == 3982
    assert "pr close 3982" in log


def test_strips_the_stage_label_from_a_reaped_issue(reaper):
    # Without this the reaper re-finds the same orphan and re-comments on
    # every single cycle.
    proc, log = reaper(
        closed={READY: [_issue(3972)]},
        branches={3972: "feature/3972-widget"},
        prs={3972: _pr(3982, _artifact_files(3972))},
        commit_dates={"feature/3972-widget": LONG_AGO},
    )

    assert f"issue edit 3972" in log
    assert f"--remove-label {READY}" in log


def test_comments_on_the_pr_before_closing_it(reaper):
    proc, log = reaper(
        closed={READY: [_issue(3972)]},
        branches={3972: "feature/3972-widget"},
        prs={3972: _pr(3982, _artifact_files(3972))},
        commit_dates={"feature/3972-widget": LONG_AGO},
    )

    comment_at = log.index("pr comment 3982")
    close_at = log.index("pr close 3982")
    assert comment_at < close_at, "a PR closed with no explanation left behind"


def test_reaps_an_orphan_carrying_the_planning_label(reaper):
    proc, log = reaper(
        closed={PLANNING: [_issue(4003)]},
        branches={4003: "feature/4003-thing"},
        prs={4003: _pr(4013, _artifact_files(4003))},
        commit_dates={"feature/4003-thing": LONG_AGO},
    )

    assert _by_number(proc, 4003)["action"] == "closed"
    assert f"--remove-label {PLANNING}" in log


# === the guard: real work is never closed ===


def test_refuses_to_close_a_branch_touching_a_source_file(reaper):
    files = _artifact_files(3972) + ["agentharness/cli.py"]
    proc, log = reaper(
        closed={IMPLEMENTING: [_issue(3972)]},
        branches={3972: "feature/3972-widget"},
        prs={3972: _pr(3982, files)},
        commit_dates={"feature/3972-widget": LONG_AGO},
    )

    assert _by_number(proc, 3972)["action"] == "flagged"
    assert "pr close" not in log


def test_routes_a_branch_with_real_work_to_a_human(reaper):
    files = _artifact_files(3972) + ["agentharness/cli.py"]
    proc, log = reaper(
        closed={IMPLEMENTING: [_issue(3972)]},
        branches={3972: "feature/3972-widget"},
        prs={3972: _pr(3982, files)},
        commit_dates={"feature/3972-widget": LONG_AGO},
    )

    assert "--add-label agent-needs-human" in log
    assert "--add-label needs-work" in log
    assert f"--remove-label {IMPLEMENTING}" in log
    assert "pr comment 3982" in log


def test_refuses_to_close_when_the_file_list_is_truncated(reaper):
    # GitHub caps the files listing at 100 per page. If the PR reports more
    # changed files than were listed, "everything listed is an artifact" no
    # longer implies "everything changed is an artifact".
    proc, log = reaper(
        closed={READY: [_issue(3972)]},
        branches={3972: "feature/3972-widget"},
        prs={3972: _pr(3982, _artifact_files(3972), changed_files=412)},
        commit_dates={"feature/3972-widget": LONG_AGO},
    )

    orphan = _by_number(proc, 3972)
    assert orphan["action"] == "flagged"
    assert "truncat" in orphan["reason"].lower()
    assert "pr close" not in log


def test_refuses_to_close_when_the_pr_reports_no_files_at_all(reaper):
    proc, log = reaper(
        closed={READY: [_issue(3972)]},
        branches={3972: "feature/3972-widget"},
        prs={3972: _pr(3982, [], changed_files=0)},
        commit_dates={"feature/3972-widget": LONG_AGO},
    )

    assert _by_number(proc, 3972)["action"] == "flagged"
    assert "pr close" not in log


def test_refuses_to_close_a_branch_touching_another_features_artifacts(reaper):
    files = _artifact_files(3972) + ["artifacts/feat-9999/spec.r1.md"]
    proc, log = reaper(
        closed={READY: [_issue(3972)]},
        branches={3972: "feature/3972-widget"},
        prs={3972: _pr(3982, files)},
        commit_dates={"feature/3972-widget": LONG_AGO},
    )

    assert _by_number(proc, 3972)["action"] == "flagged"
    assert "pr close" not in log


# === orphans with nothing to close ===


def test_strips_the_label_when_the_orphan_has_no_branch(reaper):
    proc, log = reaper(closed={READY: [_issue(3972)]})

    orphan = _by_number(proc, 3972)
    assert orphan["action"] == "label-stripped"
    assert f"--remove-label {READY}" in log
    assert "pr close" not in log


def test_strips_the_label_when_the_branch_has_no_pr(reaper):
    proc, log = reaper(
        closed={READY: [_issue(3972)]},
        branches={3972: "feature/3972-widget"},
        commit_dates={"feature/3972-widget": LONG_AGO},
    )

    assert _by_number(proc, 3972)["action"] == "label-stripped"
    assert "pr close" not in log


def test_strips_the_label_when_the_pr_is_already_closed(reaper):
    # The common benign case: the harness's own PR merged, which closed the
    # issue. Nothing to reap, but the stage label is still stale.
    proc, log = reaper(
        closed={IMPLEMENTING: [_issue(3972)]},
        branches={3972: "feature/3972-widget"},
        prs={3972: _pr(3982, _artifact_files(3972), state="MERGED")},
        commit_dates={"feature/3972-widget": LONG_AGO},
    )

    assert _by_number(proc, 3972)["action"] == "label-stripped"
    assert "pr close" not in log


# === the staleness guard ===


def test_leaves_an_orphan_alone_while_its_branch_is_still_being_pushed_to(reaper):
    # A worker can be mid-run when someone closes the issue underneath it.
    # Closing its PR from another process while it is still pushing turns a
    # recoverable mess into a confusing one; the next cycle reaps it.
    proc, log = reaper(
        closed={IMPLEMENTING: [_issue(3972)]},
        branches={3972: "feature/3972-widget"},
        prs={3972: _pr(3982, _artifact_files(3972))},
        commit_dates={"feature/3972-widget": JUST_NOW},
        stale_minutes=10,
    )

    orphan = _by_number(proc, 3972)
    assert orphan["action"] == "skipped"
    assert "pr close" not in log
    assert "issue edit" not in log


def test_reaps_once_the_branch_goes_quiet(reaper):
    proc, log = reaper(
        closed={IMPLEMENTING: [_issue(3972)]},
        branches={3972: "feature/3972-widget"},
        prs={3972: _pr(3982, _artifact_files(3972))},
        commit_dates={"feature/3972-widget": JUST_NOW},
        stale_minutes=1,
    )

    assert _by_number(proc, 3972)["action"] == "closed"


# === dry run ===


def test_dry_run_classifies_without_touching_github(reaper):
    proc, log = reaper(
        closed={READY: [_issue(3972)], IMPLEMENTING: [_issue(3989)]},
        branches={3972: "feature/3972-widget", 3989: "feature/3989-other"},
        prs={
            3972: _pr(3982, _artifact_files(3972)),
            3989: _pr(3998, _artifact_files(3989) + ["src/app.ts"]),
        },
        commit_dates={"feature/3972-widget": LONG_AGO,
                      "feature/3989-other": LONG_AGO},
        args=("--dry-run",),
    )

    assert _by_number(proc, 3972)["action"] == "closed"
    assert _by_number(proc, 3989)["action"] == "flagged"
    assert "pr close" not in log
    assert "issue edit" not in log
    assert "pr comment" not in log
    assert "pr edit" not in log


# === multiple orphans ===


def test_reaps_every_orphan_in_one_pass(reaper):
    proc, _ = reaper(
        closed={READY: [_issue(3972), _issue(3975)], IMPLEMENTING: [_issue(3987)]},
        branches={3972: "feature/3972-a", 3975: "feature/3975-b",
                  3987: "feature/3987-c"},
        prs={
            3972: _pr(3982, _artifact_files(3972)),
            3975: _pr(3986, _artifact_files(3975)),
            3987: _pr(3995, _artifact_files(3987)),
        },
        commit_dates={"feature/3972-a": LONG_AGO, "feature/3975-b": LONG_AGO,
                      "feature/3987-c": LONG_AGO},
    )

    assert {o["number"] for o in _orphans(proc)} == {3972, 3975, 3987}
    assert all(o["action"] == "closed" for o in _orphans(proc))


def test_reports_an_issue_once_even_if_it_carries_two_stage_labels(reaper):
    proc, _ = reaper(
        closed={READY: [_issue(3972)], IMPLEMENTING: [_issue(3972)]},
        branches={3972: "feature/3972-widget"},
        prs={3972: _pr(3982, _artifact_files(3972))},
        commit_dates={"feature/3972-widget": LONG_AGO},
    )

    assert len(_orphans(proc)) == 1


# === the close is verified, not assumed ===
#
# #140's lesson: a GitHub write that returns without erroring is not proof
# it landed. A close that silently did nothing while the reaper stripped the
# stage label and reported "closed" would strand the PR permanently — the
# exact failure this whole script exists to undo.


def test_does_not_report_closed_when_the_pr_is_still_open_afterwards(reaper):
    proc, log = reaper(
        closed={READY: [_issue(3972)]},
        branches={3972: "feature/3972-widget"},
        prs={3972: _pr(3982, _artifact_files(3972))},
        commit_dates={"feature/3972-widget": LONG_AGO},
        close_fails=True,
    )

    orphan = _by_number(proc, 3972)
    assert orphan["action"] == "flagged"
    assert "close" in orphan["reason"].lower()


def test_routes_an_unconfirmed_close_to_a_human_instead_of_retrying_forever(reaper):
    proc, log = reaper(
        closed={READY: [_issue(3972)]},
        branches={3972: "feature/3972-widget"},
        prs={3972: _pr(3982, _artifact_files(3972))},
        commit_dates={"feature/3972-widget": LONG_AGO},
        close_fails=True,
    )

    assert "--add-label agent-needs-human" in log
    assert "--add-label needs-work" in log
    # The stage label must still be swapped away, or every later cycle
    # re-finds this orphan and posts the same comment again.
    assert f"--remove-label {READY}" in log


# === parity: the same reap through the gh-less transport ===
#
# USE_GH_API swaps every `gh` call for a different set of REST requests
# through _lib/gh_api.sh. The verbs are unit-tested there, but nothing else
# checks that the reaper passes them the arguments they actually want — and
# a wrong argument here fails into `|| true`, i.e. silently.

CURL_STUB = """\
#!/usr/bin/env bash
url="${@: -1}"
echo "$*" >> "$REAP_STUB_LOG"
closed_marker="$REAP_STUB_DIR/closed_marker"
case "$url" in
  *"/issues?"*)
    # Only the label under test has an orphan; the other two pools are
    # empty, exactly as they would be in a real repo.
    case "$url" in
      *"labels=$REAP_STUB_LABEL"*) body=$(cat "$REAP_STUB_DIR/issues.json") ;;
      *) body='[]' ;;
    esac
    ;;
  *"/commits/"*)         body=$(cat "$REAP_STUB_DIR/commit.json") ;;
  *"/pulls?"*)
    if [ -n "${REAP_STUB_PR_LOOKUP_404:-}" ]; then
      printf '%s\\n__HTTP_CODE__404' '{"message":"Not Found"}'
      exit 0
    fi
    body="[$(cat "$REAP_STUB_DIR/pull.json")]"
    ;;
  *"/files"*)            body=$(cat "$REAP_STUB_DIR/files.json") ;;
  *"/pulls/"*)
    if [ -e "$closed_marker" ]; then
      body=$(/usr/bin/sed 's/"state": "open"/"state": "closed"/' "$REAP_STUB_DIR/pull.json")
    else
      body=$(cat "$REAP_STUB_DIR/pull.json")
    fi
    case "$*" in *"-X PATCH"*) touch "$closed_marker" ;; esac
    ;;
  *"/labels"*)           body='[]' ;;
  *"/comments"*)         body='{}' ;;
  *) echo "unexpected URL: $url" >&2; exit 1 ;;
esac
printf '%s\\n__HTTP_CODE__200' "$body"
"""


@pytest.fixture
def reaper_via_rest(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "curl").write_text(CURL_STUB)
    (bin_dir / "curl").chmod(0o755)
    (bin_dir / "git").write_text(GIT_STUB)
    (bin_dir / "git").chmod(0o755)
    payload_dir = tmp_path / "payloads"
    payload_dir.mkdir()
    branches_dir = tmp_path / "branches"
    branches_dir.mkdir()
    log = tmp_path / "reap.log"

    def run(issue, branch, pr_number, files, label=READY, pr_lookup_404=False):
        (payload_dir / "issues.json").write_text(json.dumps([
            {"number": issue, "title": "t", "state": "closed",
             "created_at": "2026-08-29T09:00:00Z"},
        ]))
        (payload_dir / "commit.json").write_text(json.dumps(
            {"commit": {"committer": {"date": LONG_AGO}}}))
        (payload_dir / "pull.json").write_text(json.dumps({
            "number": pr_number, "title": "t", "body": "", "state": "open",
            "draft": True, "created_at": "2026-08-29T09:00:00Z",
            "base": {"ref": "master"}, "head": {"ref": branch, "sha": "abc"},
            "additions": 1, "deletions": 0, "changed_files": len(files),
            "labels": [], "user": {"login": "bot"},
            "html_url": "https://github.com/onpaj/harness/pull/1",
            "mergeable": True, "mergeable_state": "clean",
        }))
        (payload_dir / "files.json").write_text(
            json.dumps([{"filename": f} for f in files]))
        (branches_dir / str(issue)).write_text(branch)
        env = {
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "REAP_STUB_LOG": str(log),
            "REAP_STUB_DIR": str(payload_dir),
            "REAP_STUB_BRANCHES_DIR": str(branches_dir),
            "GH_REPO": "onpaj/harness",
            "GITHUB_TOKEN": "fake-token-for-tests",
            "REAP_STUB_LABEL": label,
            "NOW_OVERRIDE": NOW,
            "USE_GH_API": "1",
        }
        if pr_lookup_404:
            env["REAP_STUB_PR_LOOKUP_404"] = "1"
        proc = subprocess.run(
            [str(REAPER)], capture_output=True, text=True, env=env, cwd=REPO_ROOT,
        )
        return proc, (log.read_text() if log.exists() else "")

    return run


def test_reaps_an_artifact_only_orphan_through_the_rest_transport(reaper_via_rest):
    proc, log = reaper_via_rest(3972, "feature/3972-widget", 3982,
                                _artifact_files(3972))

    assert _by_number(proc, 3972)["action"] == "closed"
    assert "-X PATCH" in log and "/pulls/3982" in log
    assert "/issues/3982/comments" in log
    assert f"/issues/3972/labels/{READY}" in log


def test_flags_real_work_through_the_rest_transport(reaper_via_rest):
    proc, log = reaper_via_rest(3972, "feature/3972-widget", 3982,
                                _artifact_files(3972) + ["agentharness/cli.py"])

    assert _by_number(proc, 3972)["action"] == "flagged"
    assert "-X PATCH" not in log


# === a transient failure must never look like an orphan ===
#
# The dangerous direction is not "failed to reap" — it is "read a network
# error as 'this issue has no branch', strip the stage label, and lose the
# only handle on the PR forever." That is the bug this script exists to
# undo, so every read that can fail must fail into `skipped`, never into
# `label-stripped`.


def test_a_failed_branch_lookup_does_not_strip_the_stage_label(reaper):
    proc, log = reaper(
        closed={READY: [_issue(3972)]},
        branches={3972: "feature/3972-widget"},
        prs={3972: _pr(3982, _artifact_files(3972))},
        commit_dates={"feature/3972-widget": LONG_AGO},
        fail="ls-remote",
    )

    assert _by_number(proc, 3972)["action"] == "skipped"
    assert "issue edit" not in log
    assert "pr close" not in log


def test_a_failed_pr_lookup_does_not_strip_the_stage_label(reaper):
    # `gh pr view` exits non-zero both for "this branch has no PR" and for
    # "the API call failed". Only the first is an orphan with nothing left
    # to close.
    proc, log = reaper(
        closed={READY: [_issue(3972)]},
        branches={3972: "feature/3972-widget"},
        prs={3972: _pr(3982, _artifact_files(3972))},
        commit_dates={"feature/3972-widget": LONG_AGO},
        fail="pr-view",
    )

    assert _by_number(proc, 3972)["action"] == "skipped"
    assert "issue edit" not in log


def test_an_unreadable_commit_date_leaves_the_orphan_alone(reaper):
    # Without a commit date there is no way to tell an abandoned branch
    # from one a worker is pushing to right now.
    proc, log = reaper(
        closed={IMPLEMENTING: [_issue(3972)]},
        branches={3972: "feature/3972-widget"},
        prs={3972: _pr(3982, _artifact_files(3972))},
        fail="commit",
    )

    assert _by_number(proc, 3972)["action"] == "skipped"
    assert "pr close" not in log
    assert "issue edit" not in log


# === the label swap must survive being interrupted halfway ===


def test_adds_the_replacement_label_before_removing_the_stage_one(reaper):
    # Under USE_GH_API these are two separate HTTP calls. Add-first leaves a
    # half-applied swap over-labelled (harmless, still discoverable);
    # remove-first would leave the issue carrying NEITHER label — invisible
    # to every stage's `--state open` selection and to this reaper's own
    # closed-issue sweep, i.e. stranded permanently by the pass meant to
    # un-strand it.
    proc, log = reaper(
        closed={IMPLEMENTING: [_issue(3972)]},
        branches={3972: "feature/3972-widget"},
        prs={3972: _pr(3982, _artifact_files(3972) + ["agentharness/cli.py"])},
        commit_dates={"feature/3972-widget": LONG_AGO},
    )

    swap = [ln for ln in log.splitlines() if ln.startswith("issue edit 3972")]
    assert swap, f"no label swap in log: {log}"
    assert swap[0].index("--add-label") < swap[0].index("--remove-label"), swap[0]


def test_rest_transport_adds_the_label_before_deleting_the_old_one(reaper_via_rest):
    proc, log = reaper_via_rest(3972, "feature/3972-widget", 3982,
                                _artifact_files(3972) + ["agentharness/cli.py"],
                                label=IMPLEMENTING)

    assert _by_number(proc, 3972)["action"] == "flagged"
    add_at = log.index('-d ["agent-needs-human"]')
    remove_at = log.index(f"/issues/3972/labels/{IMPLEMENTING}")
    assert add_at < remove_at, "the stage label was removed before its replacement landed"


# === "no PR" must mean no PR, not "the call 404'd" ===


def test_a_404_from_the_rest_transport_is_not_read_as_no_pr(reaper_via_rest):
    # gh_api.sh's emit() renders every 404 as "GitHub API HTTP 404: Not
    # Found", which is textually indistinguishable from its deliberate "no
    # PR found for branch" message unless the match is narrow enough.
    proc, log = reaper_via_rest(3972, "feature/3972-widget", 3982,
                                _artifact_files(3972), pr_lookup_404=True)

    assert _by_number(proc, 3972)["action"] == "skipped"
    assert "-X DELETE" not in log, "stripped a stage label on a failed lookup"


def test_a_genuine_no_pr_message_still_strips_the_label(reaper):
    # The narrow match must not be so narrow it stops recognising the real
    # thing — `gh pr view` on a branch with no PR.
    proc, log = reaper(
        closed={READY: [_issue(3972)]},
        branches={3972: "feature/3972-widget"},
        commit_dates={"feature/3972-widget": LONG_AGO},
    )

    assert _by_number(proc, 3972)["action"] == "label-stripped"
    assert f"--remove-label {READY}" in log


# === one issue prefix, one branch — anything else is not safe to guess ===


def test_skips_when_more_than_one_branch_matches_the_issue_prefix(reaper):
    # `feature/{n}-*` is a glob, and slug drift produces a second branch for
    # one issue (implement-next-task warns that issue titles get edited after
    # the branch is cut). Picking the first match and stripping the stage
    # label would leave the *other* branch's still-open PR with no handle at
    # all — the exact permanent stranding this script exists to undo.
    proc, log = reaper(
        closed={READY: [_issue(3972)]},
        branches={3972: ["feature/3972-widget", "feature/3972-widget-v2"]},
        prs={3972: _pr(3982, _artifact_files(3972))},
        commit_dates={"feature/3972-widget": LONG_AGO},
    )

    assert _by_number(proc, 3972)["action"] == "skipped"
    assert "pr close" not in log
    assert "issue edit" not in log


def test_never_treats_a_branch_name_as_a_pr_reference(reaper):
    # A ref that reaches `gh pr view`/`_resolve_pr_number` as `.../pull/99`
    # resolves to PR #99. A branch name is attacker-influenced by anyone with
    # push access, so a branch shaped like a PR URL must never be forwarded
    # as a PR ref — it would aim the close at an unrelated PR.
    proc, log = reaper(
        closed={READY: [_issue(3972)]},
        branches={3972: "feature/3972-widget/pull/99"},
        prs={3972: _pr(3982, _artifact_files(3972))},
        commit_dates={"feature/3972-widget/pull/99": LONG_AGO},
    )

    assert _by_number(proc, 3972)["action"] == "skipped"
    assert "pr close" not in log
    assert "issue edit" not in log


# === act on the PR that was vetted, not on whatever the branch resolves to ===


def test_addresses_its_writes_to_the_vetted_pr_number_not_the_branch(reaper):
    # The safety gate vets one specific PR and yields its number. Re-resolving
    # from the branch for each write reopens the question: a PR created for
    # that branch in between, or a transport whose lookup prefers a different
    # one, gets the close instead of the PR that was actually checked.
    proc, log = reaper(
        closed={READY: [_issue(3972)]},
        branches={3972: "feature/3972-widget"},
        prs={3972: _pr(3982, _artifact_files(3972))},
        commit_dates={"feature/3972-widget": LONG_AGO},
    )

    assert _by_number(proc, 3972)["action"] == "closed"
    assert "pr close 3982" in log
    assert "pr comment 3982" in log
    assert "pr close feature/3972-widget" not in log
    assert "pr comment feature/3972-widget" not in log


def test_flagging_also_addresses_the_vetted_pr_number(reaper):
    proc, log = reaper(
        closed={READY: [_issue(3972)]},
        branches={3972: "feature/3972-widget"},
        prs={3972: _pr(3982, _artifact_files(3972) + ["agentharness/cli.py"])},
        commit_dates={"feature/3972-widget": LONG_AGO},
    )

    assert _by_number(proc, 3972)["action"] == "flagged"
    assert "pr edit 3982" in log
    assert "pr edit feature/3972-widget" not in log


# === the audit record is the whole point: never lose it ===


def test_a_nonsense_file_count_never_reads_as_a_passed_truncation_check(reaper):
    # `listed`/`changed` feed `[ x -ne y ]`, and a non-integer there does NOT
    # abort the run: `[` exits 2 with "integer expression expected", but as an
    # `elif` condition that status is exempt from `set -e` and simply reads as
    # false. So an unexpected API shape made the truncation check — the one
    # thing standing between a partially-listed PR and being closed as
    # "artifact-only" — quietly pass, and the PR got closed. A silent breach
    # of the never-close-real-work invariant, not a crash.
    proc, log = reaper(
        closed={READY: [_issue(3972), _issue(4003)]},
        branches={3972: "feature/3972-widget", 4003: "feature/4003-thing"},
        prs={
            3972: _pr(3982, _artifact_files(3972), changed_files="many"),
            4003: _pr(4013, _artifact_files(4003)),
        },
        commit_dates={"feature/3972-widget": LONG_AGO,
                      "feature/4003-thing": LONG_AGO},
    )

    assert _by_number(proc, 3972)["action"] == "skipped"
    assert "pr close 3982" not in log, "closed a PR whose file counts were unreadable"
    # and the sweep carried on: the second, healthy orphan was still handled
    assert _by_number(proc, 4003)["action"] == "closed"


def test_still_reports_what_it_already_did_when_the_sweep_dies_midway(reaper):
    # A truncated or malformed issue-list response makes jq exit non-zero,
    # and under `set -euo pipefail` that ends the run — after earlier pools
    # have already had PRs commented on and closed. Those actions are
    # irreversible and the JSON is their only record, so it has to survive
    # the crash; the caller treats a non-zero exit as non-fatal anyway.
    proc, log = reaper(
        closed={PLANNING: [_issue(4003)], READY: "{not json"},
        branches={4003: "feature/4003-thing"},
        prs={4003: _pr(4013, _artifact_files(4003))},
        commit_dates={"feature/4003-thing": LONG_AGO},
    )

    assert proc.returncode != 0, "a failed sweep should not report success"
    orphans = json.loads(proc.stdout)["orphans"]
    assert [o["action"] for o in orphans if o["number"] == 4003] == ["closed"]
    assert "pr close 4013" in log
