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
