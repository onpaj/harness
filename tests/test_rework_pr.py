"""Tests for the /rework-pr skill scripts."""
import json
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO_ROOT / ".claude" / "skills" / "rework-pr"


# === find_candidate.sh tests ===

GH_STUB = """\
#!/usr/bin/env bash
# Fake `gh` for tests: serves `pr list` from a canned file, and
# `api repos/.../issues/N/comments` from per-PR canned comment files. Also
# records every invocation's full argv so tests can assert on the exact
# flags find_candidate.sh passes.
echo "$*" >> "$GH_STUB_LOG"
if [ "$1" = "pr" ] && [ "$2" = "list" ]; then
  cat "$GH_STUB_PR_LIST_JSON"
  exit 0
fi
if [ "$1" = "api" ]; then
  n=$(echo "$*" | grep -oE 'issues/[0-9]+/comments' | grep -oE '[0-9]+')
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
    log = tmp_path / "gh.log"

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
            "GH_STUB_LOG": str(log),
            "GH_REPO": "onpaj/harness",
        }
        proc = subprocess.run(
            [str(SKILL_DIR / "find_candidate.sh")],
            capture_output=True, text=True, env=env,
        )
        assert proc.returncode == 0, proc.stderr
        result = json.loads(proc.stdout)
        result["_gh_calls"] = log.read_text().splitlines() if log.exists() else []
        return result

    return run


def _needs_work_pr(number, created_at, **overrides):
    base = {
        "number": number, "title": f"PR {number}", "createdAt": created_at,
        "headRefName": f"feature/{number}-Thing", "body": "",
        "isDraft": False, "mergeable": "MERGEABLE",
        "labels": [{"name": "needs-work"}, {"name": "agent"}],
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


@pytest.mark.parametrize(
    "overrides,reason",
    [
        ({"isDraft": True}, "draft"),
        ({"mergeable": "UNKNOWN"}, "UNKNOWN"),
    ],
)
def test_draft_or_unmergeable_prs_are_skipped_with_a_reason(
    candidate_runner, overrides, reason
):
    result = candidate_runner(
        [_needs_work_pr(129, "2026-08-01T00:00:00Z", **overrides)],
        {129: []},
    )

    assert result["candidate"] is None
    assert result["skipped"][0]["number"] == 129
    assert reason in result["skipped"][0]["reason"]


def test_draft_pr_is_skipped_without_ever_fetching_its_comments(candidate_runner):
    # A skip decided from isDraft/mergeable alone should not cost an extra
    # `gh api .../comments` call for that PR.
    result = candidate_runner(
        [_needs_work_pr(129, "2026-08-01T00:00:00Z", isDraft=True)],
        {129: []},
    )

    assert result["candidate"] is None
    assert not any("issues/129/comments" in call for call in result["_gh_calls"])


def test_older_draft_pr_is_skipped_younger_eligible_pr_becomes_candidate(
    candidate_runner,
):
    result = candidate_runner(
        [
            _needs_work_pr(129, "2026-08-01T00:00:00Z", isDraft=True),
            _needs_work_pr(200, "2026-08-02T00:00:00Z"),
        ],
        {200: []},
    )

    assert result["candidate"]["number"] == 200
    assert result["skipped"] == [{"number": 129, "reason": "draft"}]


def test_older_at_cap_pr_is_skipped_younger_eligible_pr_becomes_candidate(
    candidate_runner,
):
    # The promoted regression test: the for-loop's `continue` path (skip an
    # ineligible PR, keep looking at the next one) must actually advance to
    # the next candidate rather than stopping the walk.
    result = candidate_runner(
        [
            _needs_work_pr(129, "2026-08-01T00:00:00Z"),
            _needs_work_pr(200, "2026-08-02T00:00:00Z"),
        ],
        {129: [REJECT_COMMENT] * 3, 200: []},
    )

    assert result["candidate"]["number"] == 200
    assert result["skipped"] == [
        {"number": 129, "reason": "revision cap reached (3 attempts)"}
    ]


def test_pr_list_is_filtered_by_both_needs_work_and_agent_labels(candidate_runner):
    result = candidate_runner(
        [_needs_work_pr(129, "2026-08-01T00:00:00Z")],
        {129: []},
    )

    pr_list_calls = [c for c in result["_gh_calls"] if c.startswith("pr list")]
    assert len(pr_list_calls) == 1
    call = pr_list_calls[0]
    assert "--label needs-work" in call
    assert "--label agent" in call
    assert "isDraft" in call and "mergeable" in call


def test_comments_lookup_uses_paginate(candidate_runner):
    result = candidate_runner(
        [_needs_work_pr(129, "2026-08-01T00:00:00Z")],
        {129: []},
    )

    api_calls = [c for c in result["_gh_calls"] if c.startswith("api")]
    assert len(api_calls) == 1
    assert "--paginate" in api_calls[0]
    assert "issues/129/comments" in api_calls[0]


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


def test_success_releases_claim_then_comments_then_removes_needs_work(finish_runner):
    proc, calls = finish_runner()

    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["status"] == "ok"
    assert payload["pr"] == 129
    # Order matters: the agent-wip claim must be released FIRST, so a failure
    # in either later step can never leak the claim permanently.
    assert "pr edit 129" in calls[0] and "agent-wip" in calls[0]
    assert "pr comment 129" in calls[1]
    assert "pr edit 129" in calls[2] and "needs-work" in calls[2]


def test_needs_work_removal_failure_reports_failed_but_claim_and_comment_landed(
    finish_runner,
):
    proc, calls = finish_runner(fail_on="needs-work")

    assert proc.returncode == 1
    payload = json.loads(proc.stdout)
    assert payload["status"] == "failed"
    assert payload["pr"] == 129
    assert "could not remove needs-work" in payload["detail"]
    joined = "\n".join(calls)
    assert "agent-wip" in joined
    assert "pr comment 129" in joined


def test_comment_failure_reports_failed_after_claim_released(finish_runner):
    proc, calls = finish_runner(fail_on="pr comment")

    assert proc.returncode == 1
    payload = json.loads(proc.stdout)
    assert payload["status"] == "failed"
    # The claim release already happened; needs-work is never touched.
    assert len(calls) == 2
    assert "pr edit 129" in calls[0] and "agent-wip" in calls[0]
    assert "pr comment 129" in calls[1]
    assert "needs-work" not in "\n".join(calls)


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


def test_success_removes_both_needs_work_and_agent_wip_labels(finish_runner):
    proc, calls = finish_runner()

    assert proc.returncode == 0
    joined = "\n".join(calls)
    assert "pr edit 129" in joined and "needs-work" in joined
    assert "agent-wip" in joined


def test_agent_wip_removal_failure_reports_failed_before_anything_else_runs(
    finish_runner,
):
    proc, calls = finish_runner(fail_on="agent-wip")

    assert proc.returncode == 1
    payload = json.loads(proc.stdout)
    assert payload["status"] == "failed"
    assert "agent-wip" in payload["detail"]
    # Releasing the claim is now the FIRST thing that can fail: nothing else
    # has run yet, so the audit comment and the needs-work removal are both
    # still untouched and the PR stays visibly needs-work for the next run.
    assert len(calls) == 1
    assert "pr edit 129" in calls[0] and "agent-wip" in calls[0]
    assert "pr comment" not in "\n".join(calls)
    assert "needs-work" not in "\n".join(calls)
