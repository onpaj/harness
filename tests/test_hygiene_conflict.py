"""Tests for /hygiene-pr's conflict resolution script.

`resolve_conflict.sh` is the deterministic scaffolding around the one part of
conflict resolution that needs judgement: editing the conflicted files. It
prepares a worktree with the merge already attempted (`prepare`), pushes the
resolution once the caller has edited those files (`finish`), or cleans up and
flags the PR `needs-work` when the caller gives up (`abort`).

These tests drive it against a real local git repo (a bare "origin" plus a
clone) and a fake `gh`, so the git half is exercised for real.
"""
import json
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / ".claude" / "skills" / "hygiene-pr" / "resolve_conflict.sh"
FLAG_SCRIPT = REPO_ROOT / ".claude" / "skills" / "_lib" / "flag_needs_work.sh"

GH_STUB = """\
#!/usr/bin/env bash
# Fake `gh` for resolve_conflict.sh tests.
#   `pr view` serves $GH_STUB_VIEW (a single canned JSON payload).
#   `pr edit`/`label create`/`pr comment` are the label + comment calls
#   apply_verdict.sh makes; `pr comment`'s --body-file is copied to
#   $GH_STUB_COMMENT_BODY so tests can assert on the posted comment.
# Every call is recorded to $GH_STUB_LOG.
echo "$*" >> "$GH_STUB_LOG"
if [ "$1" = "pr" ] && [ "$2" = "view" ]; then
  if [ "${GH_STUB_VIEW_EXIT:-0}" != "0" ]; then
    echo "simulated gh pr view failure" >&2
    exit "$GH_STUB_VIEW_EXIT"
  fi
  cat "$GH_STUB_VIEW"
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
if [ "$1" = "label" ] && [ "$2" = "create" ]; then exit 0; fi
if [ "$1" = "pr" ] && [ "$2" = "edit" ]; then exit 0; fi
exit 1
"""

BASE_FILE = "shared.txt"


def _git(cwd, *args, check=True):
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, check=check,
    )


@pytest.fixture
def repo(tmp_path):
    """A bare origin plus a clone, with `feature/x` conflicting against `master`."""
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "--bare", "--initial-branch=master", str(origin))

    clone = tmp_path / "repo"
    _git(tmp_path, "clone", str(origin), str(clone))
    _git(clone, "config", "user.email", "test@example.com")
    _git(clone, "config", "user.name", "Test")
    _git(clone, "remote", "set-url", "origin", str(origin))

    (clone / BASE_FILE).write_text("original\n")
    (clone / "untouched.txt").write_text("untouched\n")
    _git(clone, "add", "-A")
    _git(clone, "commit", "-m", "initial")
    _git(clone, "push", "-u", "origin", "master")

    _git(clone, "checkout", "-b", "feature/x")
    (clone / BASE_FILE).write_text("from the feature branch\n")
    _git(clone, "commit", "-am", "feature change")
    _git(clone, "push", "-u", "origin", "feature/x")

    # A second branch off the same commit that touches nothing master touches,
    # so it merges cleanly — the "update-branch failed for some other reason"
    # case.
    _git(clone, "checkout", "-b", "feature/clean", "master")
    (clone / "only-here.txt").write_text("no overlap\n")
    _git(clone, "add", "-A")
    _git(clone, "commit", "-m", "non-conflicting change")
    _git(clone, "push", "-u", "origin", "feature/clean")

    _git(clone, "checkout", "master")
    (clone / BASE_FILE).write_text("from master\n")
    _git(clone, "commit", "-am", "master change")
    _git(clone, "push", "origin", "master")

    return clone


@pytest.fixture
def runner(tmp_path, repo):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "gh"
    stub.write_text(GH_STUB)
    stub.chmod(0o755)

    view = tmp_path / "view.json"
    log = tmp_path / "gh.log"
    comment_body = tmp_path / "comment_body.md"

    def run(step, pr=129, state="OPEN", labels=(), base="master", head="feature/x",
            detail=None, view_exit=0):
        view.write_text(json.dumps({
            "number": pr,
            "state": state,
            "labels": [{"name": name} for name in labels],
            "baseRefName": base,
            "headRefName": head,
        }))
        env = {
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "HOME": str(tmp_path),
            "GH_STUB_VIEW": str(view),
            "GH_STUB_LOG": str(log),
            "GH_STUB_COMMENT_BODY": str(comment_body),
            "GH_STUB_VIEW_EXIT": str(view_exit),
            "GH_REPO": "onpaj/harness",
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
        }
        cmd = [str(SCRIPT), "--pr", str(pr), "--step", step]
        if detail:
            cmd += ["--detail", detail]
        proc = subprocess.run(
            cmd, capture_output=True, text=True, env=env, cwd=str(repo),
        )
        assert proc.returncode == 0, f"stdout={proc.stdout}\nstderr={proc.stderr}"
        result = json.loads(proc.stdout)
        result["_gh_calls"] = log.read_text().splitlines() if log.exists() else []
        result["_comment_body"] = (
            comment_body.read_text() if comment_body.exists() else None
        )
        return result

    return run


def _origin_head_file(repo, ref="feature/x", path=BASE_FILE):
    return _git(repo, "show", f"origin/{ref}:{path}").stdout


# === prepare ===


def test_prepare_reports_the_conflicted_files_and_claims_the_pr(runner, repo):
    result = runner("prepare")

    assert result["status"] == "conflicted"
    assert result["files"] == [BASE_FILE]
    worktree = Path(result["worktree"])
    assert worktree.is_dir()
    assert "<<<<<<<" in (worktree / BASE_FILE).read_text()
    joined = "\n".join(result["_gh_calls"])
    assert "pr edit 129" in joined and "--add-label agent-wip" in joined


def test_prepare_on_a_cleanly_mergeable_branch_reports_merged_clean(runner, repo):
    # A `conflict` from update_and_wait.sh only means `gh pr update-branch`
    # failed — that can happen for reasons other than a real conflict, and a
    # local merge is what tells the two apart.
    result = runner("prepare", head="feature/clean")

    assert result["status"] == "merged-clean"
    assert result["files"] == []


def test_prepare_skips_a_pr_already_claimed_by_another_run(runner, repo):
    result = runner("prepare", labels=["agent-wip"])

    assert result["status"] == "claimed-elsewhere"
    assert not Path(result.get("worktree") or "/nonexistent").exists()
    assert not any("--add-label" in c for c in result["_gh_calls"])


def test_prepare_skips_a_closed_pr(runner):
    result = runner("prepare", state="CLOSED")

    assert result["status"] == "not-open"
    assert not any("--add-label" in c for c in result["_gh_calls"])


def test_prepare_reports_error_without_claiming_when_the_pr_read_fails(runner):
    result = runner("prepare", view_exit=1)

    assert result["status"] == "error"
    assert not any("--add-label" in c for c in result["_gh_calls"])


# === finish ===


def test_finish_pushes_the_resolution_releases_the_claim_and_cleans_up(runner, repo):
    prepared = runner("prepare")
    worktree = Path(prepared["worktree"])
    (worktree / BASE_FILE).write_text("reconciled by hand\n")

    result = runner("finish")

    assert result["status"] == "pushed"
    assert not worktree.exists()
    _git(repo, "fetch", "origin", "feature/x")
    assert _origin_head_file(repo) == "reconciled by hand\n"
    joined = "\n".join(result["_gh_calls"])
    assert "--remove-label agent-wip" in joined


def test_finish_pushes_a_clean_merge_that_needed_no_edits(runner, repo):
    runner("prepare", head="feature/clean")

    result = runner("finish", head="feature/clean")

    assert result["status"] == "pushed"
    _git(repo, "fetch", "origin", "feature/clean")
    # master's change is now part of the PR branch.
    assert _origin_head_file(repo, ref="feature/clean") == "from master\n"


def test_finish_refuses_to_push_leftover_conflict_markers(runner, repo):
    prepared = runner("prepare")
    worktree = Path(prepared["worktree"])
    before = _git(repo, "rev-parse", "origin/feature/x").stdout

    result = runner("finish")  # markers left exactly as prepare produced them

    assert result["status"] == "unresolved"
    assert result["files"] == [BASE_FILE]
    # Nothing pushed, and the worktree + claim are left in place to fix.
    _git(repo, "fetch", "origin", "feature/x")
    assert _git(repo, "rev-parse", "origin/feature/x").stdout == before
    assert worktree.is_dir()
    assert not any("--remove-label agent-wip" in c for c in result["_gh_calls"])


def test_finish_accepts_a_resolution_containing_a_bare_equals_line(runner, repo):
    # `=======` on its own is a Markdown setext underline at least as often as
    # it is half a conflict marker; rejecting it would cost a needless
    # needs-work flag on a perfectly good resolution.
    prepared = runner("prepare")
    worktree = Path(prepared["worktree"])
    (worktree / BASE_FILE).write_text("Heading\n=======\n\nreconciled prose\n")

    result = runner("finish")

    assert result["status"] == "pushed"
    _git(repo, "fetch", "origin", "feature/x")
    assert "reconciled prose" in _origin_head_file(repo)


def test_finish_after_a_second_attempt_at_the_edits_succeeds(runner, repo):
    prepared = runner("prepare")
    worktree = Path(prepared["worktree"])
    assert runner("finish")["status"] == "unresolved"

    (worktree / BASE_FILE).write_text("resolved on the second pass\n")
    result = runner("finish")

    assert result["status"] == "pushed"
    _git(repo, "fetch", "origin", "feature/x")
    assert _origin_head_file(repo) == "resolved on the second pass\n"


def test_finish_merges_and_retries_when_the_branch_moved_under_it(runner, repo):
    prepared = runner("prepare")
    worktree = Path(prepared["worktree"])
    (worktree / BASE_FILE).write_text("reconciled by hand\n")

    # Something else pushes to the PR branch between prepare and finish.
    _git(repo, "fetch", "origin", "feature/x")
    _git(repo, "checkout", "-B", "sidecar", "origin/feature/x")
    (repo / "sidecar.txt").write_text("landed mid-run\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "concurrent change")
    _git(repo, "push", "origin", "HEAD:feature/x")

    result = runner("finish")

    assert result["status"] == "pushed"
    _git(repo, "fetch", "origin", "feature/x")
    assert _origin_head_file(repo) == "reconciled by hand\n"
    # The concurrent commit survived the retry rather than being clobbered.
    assert _origin_head_file(repo, path="sidecar.txt") == "landed mid-run\n"


def test_finish_without_a_prepared_worktree_is_an_error(runner):
    result = runner("finish")

    assert result["status"] == "error"


# === abort ===


def test_abort_flags_needs_work_releases_the_claim_and_removes_the_worktree(
    runner, repo,
):
    prepared = runner("prepare")
    worktree = Path(prepared["worktree"])

    result = runner("abort", detail="both sides rewrote the same function")

    assert result["status"] == "flagged"
    assert not worktree.exists()
    joined = "\n".join(result["_gh_calls"])
    assert "--add-label needs-work" in joined
    assert "--remove-label agent-wip" in joined
    assert result["_comment_body"] is not None
    assert re.search(r"verdict:\s*REJECT", result["_comment_body"])
    assert "both sides rewrote the same function" in result["_comment_body"]


def test_abort_still_flags_when_no_worktree_was_ever_prepared(runner):
    result = runner("abort", detail="update-branch failed and prepare never ran")

    assert result["status"] == "flagged"
    joined = "\n".join(result["_gh_calls"])
    assert "--add-label needs-work" in joined


# === argument validation ===


def test_missing_pr_argument_is_rejected():
    proc = subprocess.run(
        [str(SCRIPT), "--step", "prepare"], capture_output=True, text=True,
    )
    assert proc.returncode == 1


def test_unknown_step_is_rejected():
    proc = subprocess.run(
        [str(SCRIPT), "--pr", "1", "--step", "wat"], capture_output=True, text=True,
    )
    assert proc.returncode == 1


# === the shared needs-work trail ===


def test_shared_needs_work_helper_emits_a_countable_verdict_line():
    # rework-pr/find_candidate.sh and list_candidates.sh count a PR's prior
    # rejections toward MAX_REVISION_ATTEMPTS by matching comment bodies
    # against `verdict:\s*REJECT`. Both hygiene callers (update_and_wait.sh's
    # still-failing, resolve_conflict.sh's abort) go through this one helper,
    # so the pattern must live here.
    script = FLAG_SCRIPT.read_text()

    marker = "Hygiene check found this PR cannot be merged as-is"
    assert marker in script, "needs-work verdict block is gone or was reworded"
    block = script[script.index(marker):]
    block = block[: block.index("concerns:")]

    assert re.search(r"verdict:\s*REJECT", block), (
        "needs-work block no longer emits a `verdict: REJECT` line; "
        "rework-pr's revision-attempt cap would stop counting it"
    )


def test_both_hygiene_scripts_use_the_shared_helper():
    for script in (
        REPO_ROOT / ".claude" / "skills" / "hygiene-pr" / "update_and_wait.sh",
        SCRIPT,
    ):
        assert "flag_needs_work.sh" in script.read_text(), (
            f"{script.name} must flag needs-work through _lib/flag_needs_work.sh, "
            "not its own copy of the comment block"
        )
