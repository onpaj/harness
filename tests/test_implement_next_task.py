"""Tests for the /implement-next-task skill scripts."""
import json
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO_ROOT / ".claude" / "skills" / "implement-next-task"

FIND_GH_STUB = """\
#!/usr/bin/env bash
echo "$*" >> "$FIND_STUB_LOG"
if [ "$1" = "issue" ] && [ "$2" = "list" ]; then
  label=""
  for a in "$@"; do
    if [ "$prev" = "--label" ]; then label="$a"; fi
    prev="$a"
  done
  if [ "$label" = "agent-ready-for-dev" ]; then
    cat "$FIND_STUB_READY_JSON"
  elif [ "$label" = "agent-implementing" ]; then
    cat "$FIND_STUB_IMPLEMENTING_JSON"
  else
    echo "[]"
  fi
  exit 0
fi
if [ "$1" = "api" ]; then
  n=$(echo "$*" | grep -oE 'commits/[^ ]+' | sed 's#commits/##')
  file="$FIND_STUB_COMMITS_DIR/$n.json"
  if [ -f "$file" ]; then cat "$file"; else echo '{"commit":{"committer":{"date":"1970-01-01T00:00:00Z"}}}'; fi
  exit 0
fi
exit 1
"""

FIND_GIT_STUB = """\
#!/usr/bin/env bash
echo "$*" >> "$FIND_STUB_LOG"
if [ "$1" = "ls-remote" ]; then
  n=$(echo "$*" | grep -oE 'feature/[0-9]+' | grep -oE '[0-9]+')
  file="$FIND_STUB_BRANCHES_DIR/$n"
  if [ -f "$file" ]; then echo "deadbeef refs/heads/$(cat "$file")"; fi
  exit 0
fi
exec /usr/bin/git "$@"
"""


@pytest.fixture
def implement_candidate_runner(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "gh").write_text(FIND_GH_STUB)
    (bin_dir / "gh").chmod(0o755)
    (bin_dir / "git").write_text(FIND_GIT_STUB)
    (bin_dir / "git").chmod(0o755)
    commits_dir = tmp_path / "commits"
    commits_dir.mkdir()
    branches_dir = tmp_path / "branches"
    branches_dir.mkdir()
    log = tmp_path / "find.log"

    def run(ready_issues, implementing_issues=None, commit_dates=None, branch_names=None, stale_minutes=None, now_override=None):
        ready_json = tmp_path / "ready.json"
        ready_json.write_text(json.dumps(ready_issues))
        implementing_json = tmp_path / "implementing.json"
        implementing_json.write_text(json.dumps(implementing_issues or []))
        for ref, iso_date in (commit_dates or {}).items():
            file_path = commits_dir / f"{ref}.json"
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(
                json.dumps({"commit": {"committer": {"date": iso_date}}})
            )
        for number, branch in (branch_names or {}).items():
            (branches_dir / str(number)).write_text(branch)
        env = {
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "FIND_STUB_LOG": str(log),
            "FIND_STUB_READY_JSON": str(ready_json),
            "FIND_STUB_IMPLEMENTING_JSON": str(implementing_json),
            "FIND_STUB_COMMITS_DIR": str(commits_dir),
            "FIND_STUB_BRANCHES_DIR": str(branches_dir),
            "GH_REPO": "onpaj/harness",
        }
        if stale_minutes is not None:
            env["STALE_MINUTES"] = str(stale_minutes)
        if now_override is not None:
            env["NOW_OVERRIDE"] = now_override
        proc = subprocess.run(
            [str(SKILL_DIR / "find_candidate.sh")],
            capture_output=True, text=True, env=env,
        )
        assert proc.returncode == 0, proc.stderr
        return json.loads(proc.stdout)

    return run


def _issue(number, created_at, title="Some Title"):
    return {"number": number, "title": title, "createdAt": created_at}


def test_ready_for_dev_issue_is_immediately_eligible_regardless_of_age(implement_candidate_runner):
    result = implement_candidate_runner(
        ready_issues=[_issue(1, "2026-08-06T23:59:00Z")],
        now_override="2026-08-07T00:00:00Z",  # 1 minute old, well under any staleness window
    )
    assert result["candidate"]["number"] == 1
    assert result["candidate"]["source"] == "fresh-handoff"


def test_oldest_ready_for_dev_wins_over_younger(implement_candidate_runner):
    result = implement_candidate_runner(
        ready_issues=[_issue(2, "2026-08-02T00:00:00Z"), _issue(1, "2026-08-01T00:00:00Z")],
    )
    assert result["candidate"]["number"] == 1


def test_oldest_wins_across_merged_pool_implementing_beats_younger_ready_for_dev(implement_candidate_runner):
    """Regression test for the starvation bug: candidate selection used to
    strictly prefer any `agent-ready-for-dev` issue over every
    `agent-implementing` issue, no matter how old or how close to finishing
    the in-progress one was. Both pools now merge into one eligible set and
    the OLDEST issue by createdAt wins regardless of which label it
    carries -- here the stale implementing issue (created 2026-01-01) is
    older than the ready-for-dev issue (created 2026-08-05), so it must win.
    """
    result = implement_candidate_runner(
        ready_issues=[_issue(5, "2026-08-05T00:00:00Z")],
        implementing_issues=[_issue(1, "2026-01-01T00:00:00Z")],
        branch_names={1: "feature/1-Old-Thing"},
        commit_dates={"feature/1-Old-Thing": "2020-01-01T00:00:00Z"},
        now_override="2026-08-06T00:00:00Z",
    )
    assert result["candidate"]["number"] == 1
    assert result["candidate"]["source"] == "stale-reclaim"


def test_older_ready_for_dev_wins_over_younger_non_stale_implementing(implement_candidate_runner):
    """The recency gate still correctly excludes a non-stale
    `agent-implementing` issue from the eligible pool -- even though it may
    be younger than the ready-for-dev issue, an issue that's actively being
    worked (recent commit) must never be preempted."""
    result = implement_candidate_runner(
        ready_issues=[_issue(1, "2026-08-01T00:00:00Z")],
        implementing_issues=[_issue(2, "2026-08-02T00:00:00Z")],
        branch_names={2: "feature/2-Active-Thing"},
        commit_dates={"feature/2-Active-Thing": "2026-08-06T23:55:00Z"},
        now_override="2026-08-07T00:00:00Z",
        stale_minutes=10,
    )
    assert result["candidate"]["number"] == 1
    assert result["candidate"]["source"] == "fresh-handoff"
    assert result["skipped"][0]["number"] == 2


def test_non_numeric_stale_minutes_is_a_usage_error(implement_candidate_runner):
    with pytest.raises(AssertionError):
        # implement_candidate_runner asserts returncode == 0; a
        # non-numeric STALE_MINUTES must instead fail fast.
        implement_candidate_runner(ready_issues=[], implementing_issues=[], stale_minutes="two")


def test_stale_implementing_issue_is_candidate_when_no_fresh_handoff(implement_candidate_runner):
    result = implement_candidate_runner(
        ready_issues=[],
        implementing_issues=[_issue(1, "2026-08-01T00:00:00Z")],
        branch_names={1: "feature/1-Old-Thing"},
        commit_dates={"feature/1-Old-Thing": "2026-08-01T00:00:00Z"},
        now_override="2026-08-01T00:20:00Z",
        stale_minutes=10,
    )
    assert result["candidate"]["number"] == 1
    assert result["candidate"]["source"] == "stale-reclaim"


def test_recently_active_implementing_issue_is_skipped_not_candidate(implement_candidate_runner):
    result = implement_candidate_runner(
        ready_issues=[],
        implementing_issues=[_issue(1, "2026-08-01T00:00:00Z")],
        branch_names={1: "feature/1-Old-Thing"},
        commit_dates={"feature/1-Old-Thing": "2026-08-01T00:19:00Z"},
        now_override="2026-08-01T00:20:00Z",
        stale_minutes=10,
    )
    assert result["candidate"] is None
    assert result["skipped"][0]["number"] == 1
    assert "actively" in result["skipped"][0]["reason"] or "no commit age" in result["skipped"][0]["reason"]


def test_no_issues_at_all_yields_null_candidate(implement_candidate_runner):
    result = implement_candidate_runner(ready_issues=[], implementing_issues=[])
    assert result["candidate"] is None
    assert result["skipped"] == []


# === implement-orchestrator.md structural checks ===

CLAUDE_AGENTS_DIR = REPO_ROOT / "agentharness" / "data" / "claude-agents"


def test_implement_orchestrator_exists_and_has_required_sections():
    content = (CLAUDE_AGENTS_DIR / "implement-orchestrator.md").read_text()
    for heading in [
        "## Determine the next unit",
        "### Developer Task",
        "### Reviewer Task",
        "### Handling Review Result",
        "## Code Review Fix Pass",
        "## Code Review phase",
        "## Finishing",
    ]:
        assert heading in content, f"missing section: {heading}"


def test_implement_orchestrator_commits_real_code_not_just_artifacts():
    content = (CLAUDE_AGENTS_DIR / "implement-orchestrator.md").read_text()
    # Task 4's plan-orchestrator.md only ever does `git add -A artifacts/feat-{issue_number}`.
    # This template must also stage the rest of the worktree so developer
    # code changes are actually committed.
    assert "git add -A\n" in content or "git add -A .\n" in content


def test_implement_orchestrator_stops_after_one_unit():
    content = (CLAUDE_AGENTS_DIR / "implement-orchestrator.md").read_text()
    assert "exactly one" in content.lower() or "exactly ONE" in content
    assert "do not loop" in content.lower() or "do NOT loop" in content


def test_implement_next_task_skill_exists_and_wires_dependencies():
    content = (SKILL_DIR / "SKILL.md").read_text()
    assert "check_concurrency.sh" in content
    assert "plan-next-issue/check_concurrency.sh" in content  # cross-skill by-path call
    assert "find_candidate.sh" in content
    assert "implement-orchestrator.md" in content
    assert "agent-completed" in content
    assert "gh pr ready" in content


def test_terminal_task_failure_removes_issue_from_implementing_pool():
    """A task that exhausts max_revisions must not just get needs-work on
    the PR -- the ISSUE's own agent-implementing label has to be swapped
    off too, or the issue keeps winning oldest-wins candidate selection
    against every newer issue forever (see FAILED_TASK block in step 6).
    """
    content = (SKILL_DIR / "SKILL.md").read_text()
    failed_task_block = content[content.index('if [ -n "$FAILED_TASK" ]'):]
    failed_task_block = failed_task_block[: failed_task_block.index("\nfi\n") + len("\nfi\n")]

    assert "needs-work" in failed_task_block
    assert "agent-needs-human" in failed_task_block
    assert "gh label create agent-needs-human" in failed_task_block
    assert (
        'gh issue edit "$ISSUE_ID" --remove-label agent-implementing --add-label agent-needs-human'
        in failed_task_block
    )
