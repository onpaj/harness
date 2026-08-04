"""Tests for the /automerge skill scripts."""
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO_ROOT / ".claude" / "skills" / "automerge"


def _load_parser():
    """Import parse_verdict.py by path — it lives outside the package."""
    spec = importlib.util.spec_from_file_location(
        "parse_verdict", SKILL_DIR / "parse_verdict.py"
    )
    module = importlib.util.module_from_spec(spec)
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
        "deletions": 2, "changedFiles": 2,
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


def test_truncates_at_twenty_and_reports_the_remainder(gh_stub):
    result = gh_stub([_pr(n) for n in range(1, 26)])

    assert len(result["candidates"]) == 20
    assert result["truncated"] == 5
