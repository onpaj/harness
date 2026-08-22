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
echo "$url" >> "$CURL_STUB_LOG"
case "$url" in
  *"/check-runs"*) body=$(cat "$CURL_STUB_DIR/check_runs.json") ;;
  *"/status"*)     body=$(cat "$CURL_STUB_DIR/status.json") ;;
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


# === pr-ready: the mutation's response is not evidence ===
#
# `markPullRequestReadyForReview` has been observed returning a clean,
# error-free response while the PR stayed a draft. pr_ready used to return 0 on
# that response alone, and implement-next-task's Finishing step treats exit 0
# as "the PR is mergeable now" — so six PRs ended up in draft with their issues
# labelled agent-completed, invisible to every downstream skill.

READY_STUB = """\
#!/usr/bin/env bash
url="${@: -1}"
echo "$url" >> "$CURL_STUB_LOG"
case "$url" in
  *"/graphql"*)
    if [ -n "${UNDRAFT_TAKES_EFFECT:-}" ]; then touch "$CURL_STUB_DIR/undrafted"; fi
    printf '%s\\n__HTTP_CODE__200' '{"data":{"markPullRequestReadyForReview":{"pullRequest":{"id":"PR_x"}}}}'
    ;;
  *"/pulls/"*)
    if [ -f "$CURL_STUB_DIR/undrafted" ]; then
      cat "$CURL_STUB_DIR/pull_ready.json"
    else
      cat "$CURL_STUB_DIR/pull_draft.json"
    fi
    printf '\\n__HTTP_CODE__200'
    ;;
  *) echo "unexpected URL: $url" >&2; exit 1 ;;
esac
"""


@pytest.fixture
def gh_api_ready(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "curl"
    stub.write_text(READY_STUB)
    stub.chmod(0o755)

    payload_dir = tmp_path / "payloads"
    payload_dir.mkdir()
    draft = _pull()
    draft["draft"] = True
    draft["node_id"] = "PR_x"
    ready = dict(draft, draft=False)
    (payload_dir / "pull_draft.json").write_text(json.dumps(draft))
    (payload_dir / "pull_ready.json").write_text(json.dumps(ready))

    def run(argv, undraft_takes_effect: bool):
        env = {
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "CURL_STUB_DIR": str(payload_dir),
            "CURL_STUB_LOG": str(tmp_path / "curl.log"),
            "GH_REPO": "onpaj/harness",
            "GITHUB_TOKEN": "fake-token-for-tests",
        }
        if undraft_takes_effect:
            env["UNDRAFT_TAKES_EFFECT"] = "1"
        return subprocess.run(
            argv, capture_output=True, text=True, env=env, cwd=REPO_ROOT,
        )

    return run


def test_pr_ready_succeeds_once_the_pr_actually_left_draft(gh_api_ready):
    proc = gh_api_ready([str(LIB), "pr-ready", str(PR_NUMBER)], undraft_takes_effect=True)

    assert proc.returncode == 0, proc.stderr


def test_pr_ready_fails_when_the_mutation_returns_clean_but_the_pr_is_still_draft(gh_api_ready):
    proc = gh_api_ready([str(LIB), "pr-ready", str(PR_NUMBER)], undraft_takes_effect=False)

    assert proc.returncode != 0, "a still-draft PR must not be reported as ready"
    assert "still a draft" in proc.stderr


# === graphql: a query with no variables ===


def test_graphql_accepts_a_query_with_no_variables(gh_api_ready):
    # `vars="${2:-{\}}"` cannot yield a literal `{}` — it yields `{\}`, which
    # jq rejects with "invalid JSON text passed to --argjson", so every
    # variable-less GraphQL call died before it was ever sent.
    proc = gh_api_ready(
        [str(LIB), "graphql", "mutation{markPullRequestReadyForReview}"],
        undraft_takes_effect=False,
    )

    assert proc.returncode == 0, proc.stderr
    assert "argjson" not in proc.stderr
