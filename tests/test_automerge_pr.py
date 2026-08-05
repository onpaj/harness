"""Tests for the /automerge-pr skill scripts."""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO_ROOT / ".claude" / "skills" / "automerge-pr"


def _load_parser():
    """Import parse_verdict.py by path — it lives outside the package."""
    spec = importlib.util.spec_from_file_location(
        "parse_verdict", SKILL_DIR / "parse_verdict.py"
    )
    module = importlib.util.module_from_spec(spec)
    # Never write a __pycache__/*.pyc under the skill directory: that dir is
    # byte-for-byte compared against agentharness/data/skills/automerge-pr/ by
    # test_packaged_skills.py, and a stray .pyc (untracked, not synced
    # between the two copies) would fail that comparison on any fresh
    # checkout or CI run.
    sys.dont_write_bytecode = True
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


# === Candidate selection tests ===

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
        "deletions": 2, "changedFiles": 2, "body": "", "labels": [],
        "createdAt": "2026-08-01T00:00:00Z",
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
        ({"labels": [{"name": "needs-work"}]}, "needs-work"),
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


def test_pr_with_closes_link_in_body_yields_linked_issue(gh_stub):
    result = gh_stub([_pr(129, body="Fixes some stuff.\n\nCloses #118\n")])

    assert result["candidates"][0]["linkedIssue"] == 118


def test_pr_with_no_closes_link_yields_null_linked_issue(gh_stub):
    result = gh_stub([_pr(129, body="No issue reference here.")])

    assert result["candidates"][0]["linkedIssue"] is None


def test_candidate_reports_created_at(gh_stub):
    result = gh_stub([_pr(129, createdAt="2026-08-03T12:00:00Z")])

    assert result["candidates"][0]["createdAt"] == "2026-08-03T12:00:00Z"


def test_truncates_at_twenty_and_reports_the_remainder(gh_stub):
    result = gh_stub([_pr(n) for n in range(1, 26)])

    assert len(result["candidates"]) == 20
    assert result["truncated"] == 5


# === apply_verdict tests ===

GH_RECORDER = """\
#!/usr/bin/env bash
# Fake `gh` that records its argv and optionally fails with a chosen message.
echo "$*" >> "$GH_LOG"
if [ -n "${GH_FAIL_ON:-}" ] && [[ "$*" == *"$GH_FAIL_ON"* ]]; then
  echo "${GH_FAIL_MESSAGE:-simulated gh failure}" >&2
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

    def run(action, pr=129, issue=None, fail_on=None, fail_message=None):
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
    # The label is created defensively (best-effort, like needs-work's label)
    # before it is applied to the issue.
    joined = "\n".join(calls[2:])
    assert "label create agent-merged" in joined
    assert "issue edit 118" in joined
    assert "agent-merged" in joined


def test_merge_succeeds_even_when_issue_labelling_fails(apply_runner):
    # The merge and branch deletion already happened by the time labelling
    # runs — a labelling failure must be reported as "ok" with a caveat, not
    # as a failed PR, or the orchestrator would tell the user a merge failed
    # after master already moved.
    proc, calls = apply_runner("merge", pr=129, issue=118, fail_on="issue edit")

    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["status"] == "ok"
    assert payload["pr"] == 129
    assert "could not label issue #118" in payload["detail"]
    joined = "\n".join(calls)
    assert "pr merge 129" in joined
    assert "issue edit 118" in joined


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


def test_merge_conflict_reports_skipped_not_failed(apply_runner):
    # A PR that went unmergeable between listing and merging is not an error
    # in this run — master simply moved underneath it. Distinct from a
    # generic gh failure, which reports "failed" (tested above).
    proc, calls = apply_runner(
        "merge", issue=118, fail_on="pr merge",
        fail_message="GraphQL: Pull Request is not mergeable (mergePullRequest)",
    )

    assert proc.returncode == 1
    payload = json.loads(proc.stdout)
    assert payload["status"] == "skipped"
    assert payload["pr"] == 129
    # The review comment must still have posted; the issue must NOT be labelled.
    joined = "\n".join(calls)
    assert "pr comment 129" in joined
    assert "issue edit" not in joined


def test_unknown_action_is_rejected(apply_runner):
    proc, calls = apply_runner("delete-everything")

    assert proc.returncode == 1
    assert calls == []          # nothing was touched


# === SKILL.md / parser threshold drift guard ===


def test_skill_md_prompt_thresholds_match_parser_constants():
    # SKILL.md's reviewer-subagent prompt restates the thresholds in natural
    # language (the subagent can't read a Python constant at runtime). That
    # restatement must stay in sync with parse_verdict.py's actual constants,
    # or the prompt and the parser silently disagree about the merge bar.
    skill_md = (SKILL_DIR / "SKILL.md").read_text()

    assert f"score >= {parser.MERGE_THRESHOLD}" in skill_md
    assert (
        f"COMMENT if {parser.NEEDS_WORK_THRESHOLD}-{parser.MERGE_THRESHOLD - 1}"
        in skill_md
    )
    assert f"REJECT if < {parser.NEEDS_WORK_THRESHOLD}" in skill_md
