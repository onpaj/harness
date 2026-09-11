"""Tests for .claude/skills/_lib/gh_api.sh — the curl+REST transport used in
place of the `gh` CLI when USE_GH_API is set.

Its whole contract is that every shaped subcommand emits JSON identical in
shape *and value casing* to what `gh ... --json <fields>` produces, so
call-site jq filters work unchanged across both transports. REST returns
lowercase enum values where gh's GraphQL-backed output returns uppercase
ones, so each shaped field needs explicit normalization — and a field that
misses it is invisible until a downstream jq comparison silently never
matches.
"""
import json
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
LIB = REPO_ROOT / ".claude" / "skills" / "_lib" / "gh_api.sh"
HYGIENE = REPO_ROOT / ".claude" / "skills" / "hygiene-pr" / "update_and_wait.sh"

PR_NUMBER = 3901
HEAD_SHA = "12be804b418a9db06ca042b852534b4a351169da"

# Serves canned REST payloads by URL substring, mimicking curl's
# `-w '\n__HTTP_CODE__%{http_code}'` output format. Every call is logged.
CURL_STUB = """\
#!/usr/bin/env bash
url="${@: -1}"
echo "$*" >> "$CURL_STUB_LOG"
case "$url" in
  *"/check-runs"*) body=$(cat "$CURL_STUB_DIR/check_runs.json") ;;
  *"/status"*)     body=$(cat "$CURL_STUB_DIR/status.json") ;;
  *"/pulls?"*)     body="[$(cat "$CURL_STUB_DIR/pull.json")]" ;;
  *"/pulls/"*)     body=$(cat "$CURL_STUB_DIR/pull.json") ;;
  *) echo "unexpected URL: $url" >&2; exit 1 ;;
esac
printf '%s\\n__HTTP_CODE__200' "$body"
"""


def _pull(mergeable=True, mergeable_state="clean"):
    return {
        "number": PR_NUMBER,
        "title": "a pull request",
        "body": "",
        "state": "open",
        "draft": False,
        "created_at": "2026-08-12T09:00:00Z",
        "base": {"ref": "master"},
        "head": {"ref": "feature/x", "sha": HEAD_SHA},
        "additions": 1,
        "deletions": 0,
        "changed_files": 1,
        "labels": [],
        "user": {"login": "someone"},
        "html_url": f"https://github.com/onpaj/harness/pull/{PR_NUMBER}",
        "mergeable": mergeable,
        "mergeable_state": mergeable_state,
    }


@pytest.fixture
def gh_api(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "curl"
    stub.write_text(CURL_STUB)
    stub.chmod(0o755)

    payload_dir = tmp_path / "payloads"
    payload_dir.mkdir()
    log = tmp_path / "curl.log"

    def run(argv, check_runs=None, statuses=None, pull=None, extra_env=None):
        (payload_dir / "pull.json").write_text(json.dumps(pull or _pull()))
        (payload_dir / "check_runs.json").write_text(
            json.dumps({"check_runs": check_runs if check_runs is not None else []})
        )
        (payload_dir / "status.json").write_text(
            json.dumps({"statuses": statuses if statuses is not None else []})
        )
        env = {
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "CURL_STUB_DIR": str(payload_dir),
            "CURL_STUB_LOG": str(log),
            "GH_REPO": "onpaj/harness",
            "GITHUB_TOKEN": "fake-token-for-tests",
            **(extra_env or {}),
        }
        proc = subprocess.run(
            argv, capture_output=True, text=True, env=env, cwd=REPO_ROOT,
        )
        proc.curl_log = log.read_text() if log.exists() else ""
        return proc

    return run


def _rollup(proc):
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)["statusCheckRollup"]


# === casing normalization ===
#
# `gh --json statusCheckRollup` returns GraphQL enums (COMPLETED/SUCCESS);
# the REST check-runs endpoint returns them lowercase. update_and_wait.sh's
# CI_STATE_FILTER compares against the uppercase form, so passing REST's
# casing through unchanged classified every finished check as "pending" —
# and every PR as ci-running, forever, in gh-less environments.


def test_check_run_status_and_conclusion_are_uppercased(gh_api):
    proc = gh_api(
        [str(LIB), "pr-view", str(PR_NUMBER), "statusCheckRollup"],
        check_runs=[
            {"status": "completed", "conclusion": "success"},
            {"status": "completed", "conclusion": "skipped"},
        ],
    )

    assert _rollup(proc) == [
        {"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "SUCCESS"},
        {"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "SKIPPED"},
    ]


def test_in_progress_check_run_keeps_its_null_conclusion(gh_api):
    # A running check has conclusion: null — uppercasing must tolerate it
    # rather than erroring out mid-filter.
    proc = gh_api(
        [str(LIB), "pr-view", str(PR_NUMBER), "statusCheckRollup"],
        check_runs=[{"status": "in_progress", "conclusion": None}],
    )

    assert _rollup(proc) == [
        {"__typename": "CheckRun", "status": "IN_PROGRESS", "conclusion": None},
    ]


def test_legacy_status_context_state_is_uppercased(gh_api):
    proc = gh_api(
        [str(LIB), "pr-view", str(PR_NUMBER), "statusCheckRollup"],
        statuses=[{"state": "success"}],
    )

    assert _rollup(proc) == [{"__typename": "StatusContext", "state": "SUCCESS"}]


# === end to end through the consumer that reads it ===


def test_hygiene_reads_finished_green_checks_as_already_clean(gh_api):
    # The bug as it actually presented: five finished, green checks read as
    # `ci-running`, so /automerge-all skipped the PR on every sweep.
    proc = gh_api(
        [str(HYGIENE), "--pr", str(PR_NUMBER)],
        check_runs=[
            {"status": "completed", "conclusion": "success"},
            {"status": "completed", "conclusion": "skipped"},
            {"status": "completed", "conclusion": "success"},
        ],
        extra_env={"USE_GH_API": "1", "HYGIENE_POLL_MAX_ATTEMPTS": "2",
                   "HYGIENE_POLL_INTERVAL_SECONDS": "0"},
    )

    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["status"] == "already-clean"


def test_hygiene_reads_a_finished_red_check_as_still_failing(gh_api):
    proc = gh_api(
        [str(HYGIENE), "--pr", str(PR_NUMBER)],
        check_runs=[
            {"status": "completed", "conclusion": "success"},
            {"status": "completed", "conclusion": "failure"},
        ],
        extra_env={"USE_GH_API": "1", "HYGIENE_POLL_MAX_ATTEMPTS": "2",
                   "HYGIENE_POLL_INTERVAL_SECONDS": "0"},
    )

    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["status"] == "still-failing"


def test_hygiene_still_sees_a_genuinely_running_check_as_ci_running(gh_api):
    proc = gh_api(
        [str(HYGIENE), "--pr", str(PR_NUMBER)],
        check_runs=[{"status": "in_progress", "conclusion": None}],
        extra_env={"USE_GH_API": "1", "HYGIENE_POLL_MAX_ATTEMPTS": "2",
                   "HYGIENE_POLL_INTERVAL_SECONDS": "0"},
    )

    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["status"] == "ci-running"


# === pr-close ===
#
# reap_orphans.sh closes a superseded PR through this verb. Without it the
# gh-less transport would fail the call, and the reaper's `|| true` would
# turn that into a silent no-op — a PR reported closed but still open.


def test_pr_close_patches_the_pr_state_to_closed(gh_api):
    proc = gh_api([str(LIB), "pr-close", str(PR_NUMBER)])

    assert proc.returncode == 0, proc.stderr
    assert "-X PATCH" in proc.curl_log
    assert '{"state":"closed"}' in proc.curl_log.replace(" ", "")
    assert f"/pulls/{PR_NUMBER}" in proc.curl_log


def test_pr_close_resolves_a_branch_name_to_its_pr(gh_api):
    # A PR ref is a number, a PR URL, or a head branch — the same three
    # forms `gh pr close <ref>` accepts.
    proc = gh_api([str(LIB), "pr-close", "feature/x"])

    assert proc.returncode == 0, proc.stderr
    assert "head=onpaj%3Afeature%2Fx" in proc.curl_log
    assert f"-X PATCH" in proc.curl_log
    assert f"/pulls/{PR_NUMBER}" in proc.curl_log


def test_pr_close_leaves_the_branch_in_place(gh_api):
    # Deliberate: a reaped branch stays recoverable. Deleting the ref is
    # what `pr-merge --delete-branch` is for.
    proc = gh_api([str(LIB), "pr-close", str(PR_NUMBER)])

    assert proc.returncode == 0, proc.stderr
    assert "-X DELETE" not in proc.curl_log
    assert "/git/refs/" not in proc.curl_log


# === a PR ref is three forms, and a branch name is not the URL one ===


def test_a_branch_name_containing_a_pull_path_is_not_read_as_that_pr(gh_api):
    # The URL form was matched unanchored, so any ref merely *containing*
    # `/pull/<n>` short-circuited to <n>. Branch names come from whoever can
    # push, and `git ls-remote`'s `feature/12-*` glob matches across `/`, so
    # a branch called `feature/12-x/pull/99` would have aimed a close at the
    # unrelated PR #99. A branch must go through the head lookup like any
    # other branch.
    proc = gh_api([str(LIB), "pr-close", "feature/12-x/pull/99"])

    assert proc.returncode == 0, proc.stderr
    assert "/pulls/99" not in proc.curl_log, "a branch name was parsed as a PR URL"
    assert "head=onpaj%3Afeature%2F12-x%2Fpull%2F99" in proc.curl_log
    assert f"/pulls/{PR_NUMBER}" in proc.curl_log


def test_a_real_pr_url_still_resolves_without_a_lookup(gh_api):
    # The anchored form must still recognise the genuine article.
    proc = gh_api([str(LIB), "pr-close",
                   f"https://github.com/onpaj/harness/pull/{PR_NUMBER}"])

    assert proc.returncode == 0, proc.stderr
    assert "/pulls?" not in proc.curl_log, "resolved a full PR URL via a head lookup"
    assert f"/pulls/{PR_NUMBER}" in proc.curl_log


# === .env discovery across git worktrees ===
#
# The pipeline runs every unit of work inside a `git worktree add`-created
# worktree. `.env` is gitignored, so it exists only in the main checkout and
# is never present in a worktree. Resolving it from the script's own path
# therefore found nothing, and with USE_GH_API set every call from inside a
# worktree died with "no token" — which implement-next-task's step 9 then
# swallowed via `|| true`, reporting success while writing nothing.


def _seed_repo(root: Path, token_line: str) -> None:
    """A git repo carrying the real gh_api.sh, plus a gitignored .env."""
    lib_dir = root / ".claude" / "skills" / "_lib"
    lib_dir.mkdir(parents=True)
    target = lib_dir / "gh_api.sh"
    target.write_text(LIB.read_text())
    target.chmod(0o755)
    (root / ".gitignore").write_text(".env\n")
    subprocess.run(["git", "init", "-q", "-b", "master"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"],
        cwd=root, check=True,
    )
    (root / ".env").write_text(token_line)


def _run_lib(cwd: Path, argv_extra=None, env_extra=None):
    """Run gh_api.sh with no token in the environment at all."""
    env = {
        "PATH": "/usr/bin:/bin:/usr/local/bin",
        "HOME": str(cwd),
        "GH_REPO": "onpaj/harness",
        **(env_extra or {}),
    }
    return subprocess.run(
        [str(cwd / ".claude" / "skills" / "_lib" / "gh_api.sh")] + (argv_extra or []),
        capture_output=True, text=True, env=env, cwd=cwd,
    )


def test_token_is_read_from_the_main_checkouts_env_when_run_inside_a_worktree(tmp_path):
    main = tmp_path / "main"
    main.mkdir()
    _seed_repo(main, "GIT_PAT=token-from-main-checkout\n")
    tree = tmp_path / "wt"
    subprocess.run(
        ["git", "worktree", "add", "-q", "-b", "feature/x", str(tree)],
        cwd=main, check=True,
    )
    assert not (tree / ".env").exists(), "fixture invalid: .env must not reach the worktree"

    proc = _run_lib(tree)

    assert "no token" not in proc.stderr, (
        "gh_api.sh could not find the main checkout's .env from inside a worktree — "
        "every USE_GH_API call in the pipeline fails there"
    )


def test_token_is_still_read_from_env_in_the_primary_checkout(tmp_path):
    main = tmp_path / "main"
    main.mkdir()
    _seed_repo(main, "GIT_PAT=token-from-main-checkout\n")

    proc = _run_lib(main)

    assert "no token" not in proc.stderr, proc.stderr


def test_a_real_environment_token_still_wins_over_the_env_file(tmp_path):
    # Precedence matters: an Orca automation injects GIT_PAT directly, and a
    # stale .env in the main checkout must never shadow it.
    main = tmp_path / "main"
    main.mkdir()
    _seed_repo(main, "GIT_PAT=token-from-env-file\n")
    tree = tmp_path / "wt"
    subprocess.run(
        ["git", "worktree", "add", "-q", "-b", "feature/x", str(tree)],
        cwd=main, check=True,
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "curl.log"
    stub = bin_dir / "curl"
    stub.write_text(
        '#!/usr/bin/env bash\necho "$*" >> "$CURL_STUB_LOG"\n'
        "printf '%s\\n__HTTP_CODE__200' " + repr(json.dumps(_pull())) + "\n"
    )
    stub.chmod(0o755)

    proc = _run_lib(
        tree,
        ["pr-close", str(PR_NUMBER)],
        {
            "GIT_PAT": "token-from-environment",
            "PATH": f"{bin_dir}:/usr/bin:/bin:/usr/local/bin",
            "CURL_STUB_LOG": str(log),
        },
    )

    assert proc.returncode == 0, proc.stderr
    assert "Bearer token-from-environment" in log.read_text()
    assert "token-from-env-file" not in log.read_text()
