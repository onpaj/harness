"""Tests for the /plan-next-issue skill scripts."""
import json
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO_ROOT / ".claude" / "skills" / "plan-next-issue"

PGREP_STUB = """\
#!/usr/bin/env bash
# Fake `pgrep` for tests: prints a canned newline-separated PID list
# regardless of the pattern it was asked to match.
cat "$PGREP_STUB_PIDS"
exit 0
"""

PGREP_STUB_REAL = """\
#!/usr/bin/env bash
# Fake `pgrep` that mimics real pgrep: exits 1 on zero matches
cat "$PGREP_STUB_PIDS"
pids_file="$PGREP_STUB_PIDS"
if [ ! -s "$pids_file" ]; then
  exit 1
fi
exit 0
"""


@pytest.fixture
def concurrency_runner(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "pgrep"
    stub.write_text(PGREP_STUB)
    stub.chmod(0o755)
    pids_file = tmp_path / "pids"

    def run(max_concurrent, pattern, matching_pids):
        # None of these fake PIDs will coincidentally equal the real PPID
        # subprocess.run assigns at test time, so the script's self-PID
        # exclusion is a no-op here and every fake PID counts -- which is
        # exactly what these tests assert on. Self-PID exclusion itself is
        # exercised for real in Task 2's claim_issue.sh integration, where
        # the concurrency gate and a real parent process interact.
        pids_file.write_text("\n".join(matching_pids) + ("\n" if matching_pids else ""))
        env = {
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "PGREP_STUB_PIDS": str(pids_file),
        }
        proc = subprocess.run(
            [str(SKILL_DIR / "check_concurrency.sh"), str(max_concurrent), pattern],
            capture_output=True, text=True, env=env,
        )
        return proc

    return run


def test_under_capacity_exits_zero(concurrency_runner):
    proc = concurrency_runner(2, "plan-next-issue", ["111"])
    assert proc.returncode == 0, proc.stderr
    assert "under capacity: 1/2" in proc.stdout


def test_at_capacity_exits_four(concurrency_runner):
    proc = concurrency_runner(2, "plan-next-issue", ["111", "222"])
    assert proc.returncode == 4
    assert "at capacity: 2/2" in proc.stderr


def test_over_capacity_exits_four(concurrency_runner):
    proc = concurrency_runner(1, "plan-next-issue", ["111", "222", "333"])
    assert proc.returncode == 4
    assert "at capacity: 3/1" in proc.stderr


def test_zero_matches_is_under_capacity(concurrency_runner):
    proc = concurrency_runner(2, "plan-next-issue", [])
    assert proc.returncode == 0
    assert "under capacity: 0/2" in proc.stdout


def test_missing_args_is_usage_error():
    proc = subprocess.run(
        [str(SKILL_DIR / "check_concurrency.sh")],
        capture_output=True, text=True,
    )
    assert proc.returncode == 2
    assert "usage:" in proc.stderr


def test_non_numeric_max_is_usage_error():
    proc = subprocess.run(
        [str(SKILL_DIR / "check_concurrency.sh"), "two", "pattern"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 2
    assert "usage:" in proc.stderr


def test_pgrep_exit_one_on_zero_matches(tmp_path):
    """Regression test: pgrep exits 1 on zero matches, script must handle it.
    Uses a stub that mimics real pgrep's behavior: returns 1 on empty output."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "pgrep"
    stub.write_text(PGREP_STUB_REAL)
    stub.chmod(0o755)
    pids_file = tmp_path / "pids"
    pids_file.write_text("")  # Empty file to trigger pgrep's exit 1

    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "PGREP_STUB_PIDS": str(pids_file),
    }
    proc = subprocess.run(
        [str(SKILL_DIR / "check_concurrency.sh"), "2", "test-pattern"],
        capture_output=True, text=True, env=env,
    )
    assert proc.returncode == 0, f"stderr: {proc.stderr}"
    assert "under capacity: 0/2" in proc.stdout


PS_STUB = """\
#!/usr/bin/env bash
# Fake `ps -o ppid= -p <pid>` used to simulate a multi-level process
# ancestry (this script -> a wrapping shell -> a top-level `claude`
# process) without depending on the real OS process tree. Ignores the
# queried PID entirely and returns the next canned ancestor by call count.
count_file="$PS_STUB_CALL_COUNT"
n=0
if [ -f "$count_file" ]; then n=$(cat "$count_file"); fi
n=$((n + 1))
echo "$n" > "$count_file"
case "$n" in
  1) echo "$PS_STUB_WRAPPER_PID" ;;
  2) echo "$PS_STUB_CLAUDE_PID" ;;
  *) echo "1" ;;
esac
exit 0
"""

WRAPPER_TEMPLATE = """\
#!/usr/bin/env bash
# Populate the fake pgrep match list with our own PID (which becomes
# check_concurrency.sh's real PID after the `exec` below, since exec
# replaces the process image in place without forking a new PID), plus
# the fake ancestor PIDs the `ps` stub will report, plus one genuinely
# separate match that must still be counted.
printf '%s\\n%s\\n%s\\n%s\\n' "$$" "{wrapper_pid}" "{claude_pid}" "{other_pid}" > "$PGREP_STUB_PIDS"
exec "{check_script}" "$@"
"""


def test_multi_level_ancestry_all_excluded_true_count_reported(tmp_path):
    """Regression test: `pgrep -f` matches full command lines, and $PATTERN
    is passed to this script as a literal argv string -- so this script's
    own process, any wrapping shell between the top-level `claude` process
    and this script, and that `claude` process itself can all spuriously
    match $PATTERN just by having invoked this script. Excluding only
    $PPID (a single PID) left the count inflated by at least one even in
    the best case. This simulates the full three-level ancestry chain
    (self, wrapping shell, top-level claude) all appearing in the pgrep
    match list and asserts every PID in that chain is excluded, while a
    genuinely separate match is still counted.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    (bin_dir / "pgrep").write_text(PGREP_STUB)
    (bin_dir / "pgrep").chmod(0o755)

    fake_wrapper_pid = "555555"
    fake_claude_pid = "666666"
    fake_other_pid = "777777"

    ps_stub = bin_dir / "ps"
    ps_stub.write_text(PS_STUB)
    ps_stub.chmod(0o755)

    pids_file = tmp_path / "pids"
    wrapper = tmp_path / "wrapper.sh"
    wrapper.write_text(WRAPPER_TEMPLATE.format(
        wrapper_pid=fake_wrapper_pid,
        claude_pid=fake_claude_pid,
        other_pid=fake_other_pid,
        check_script=str(SKILL_DIR / "check_concurrency.sh"),
    ))
    wrapper.chmod(0o755)

    call_count_file = tmp_path / "ps_call_count"

    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "PGREP_STUB_PIDS": str(pids_file),
        "PS_STUB_CALL_COUNT": str(call_count_file),
        "PS_STUB_WRAPPER_PID": fake_wrapper_pid,
        "PS_STUB_CLAUDE_PID": fake_claude_pid,
    }
    proc = subprocess.run(
        [str(wrapper), "2", "claude.*plan-next-issue"],
        capture_output=True, text=True, env=env,
    )
    assert proc.returncode == 0, proc.stderr
    # Only the genuinely separate match (fake_other_pid) counts -- self,
    # the wrapping shell, and the top-level claude process are all
    # excluded via the ancestry walk.
    assert "under capacity: 1/2" in proc.stdout, proc.stdout


# === claim_issue.sh tests ===

CLAIM_GH_STUB = """\
#!/usr/bin/env bash
echo "$*" >> "$CLAIM_STUB_LOG"
if [ "$1" = "issue" ] && [ "$2" = "view" ]; then
  # Check if --jq filter is specified (for title extraction)
  if [ "$6" = "--jq" ] && [ "$7" = ".title" ]; then
    # Extract title from JSON
    python3 -c "import json, sys; print(json.load(open('$CLAIM_STUB_ISSUE_JSON')).get('title', ''))"
  else
    cat "$CLAIM_STUB_ISSUE_JSON"
  fi
  exit 0
fi
if [ "$1" = "repo" ] && [ "$2" = "view" ]; then
  if [ "$3" = "--json" ] && [ "$4" = "defaultBranchRef" ] && [ "$5" = "--jq" ]; then
    echo "main"
  else
    echo '{"defaultBranchRef":{"name":"main"}}'
  fi
  exit 0
fi
if [ "$1" = "api" ] && [ "$2" = "repos/{owner}/{repo}/git/refs" ]; then
  if [ -f "$CLAIM_STUB_REF_EXISTS" ]; then
    echo "HTTP 422: Reference already exists" >&2
    exit 1
  fi
  touch "$CLAIM_STUB_REF_EXISTS"
  exit 0
fi
if [ "$1" = "issue" ] && [ "$2" = "edit" ]; then
  exit 0
fi
exit 1
"""

CLAIM_GIT_STUB = """\
#!/usr/bin/env bash
echo "$*" >> "$CLAIM_STUB_LOG"
if [ "$1" = "ls-remote" ]; then
  # Check if called with feature branch pattern match (4th arg)
  if [ -n "${4:-}" ] && [[ "$4" == feature/* ]]; then
    if [ -f "$CLAIM_STUB_BRANCH_EXISTS" ]; then
      echo "deadbeef refs/heads/feature/42-Some-Title"
    fi
  else
    # For regular branch refs (like refs/heads/main)
    echo "cafebabe refs/heads/main"
  fi
  exit 0
fi
exec /usr/bin/git "$@"
"""


@pytest.fixture
def claim_runner(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "gh").write_text(CLAIM_GH_STUB)
    (bin_dir / "gh").chmod(0o755)
    (bin_dir / "git").write_text(CLAIM_GIT_STUB)
    (bin_dir / "git").chmod(0o755)
    log = tmp_path / "claim.log"

    def run(issue, target_label, title="Some Title", branch_exists=False, ref_exists=False):
        issue_json = tmp_path / "issue.json"
        issue_json.write_text(json.dumps({"title": title}))
        ref_exists_marker = tmp_path / "ref_exists"
        if ref_exists:
            ref_exists_marker.touch()
        branch_exists_marker = tmp_path / "branch_exists"
        if branch_exists:
            branch_exists_marker.touch()
        env = {
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "CLAIM_STUB_LOG": str(log),
            "CLAIM_STUB_ISSUE_JSON": str(issue_json),
            "CLAIM_STUB_REF_EXISTS": str(ref_exists_marker),
            "CLAIM_STUB_BRANCH_EXISTS": str(branch_exists_marker),
        }
        proc = subprocess.run(
            [str(SKILL_DIR / "claim_issue.sh"), str(issue), target_label],
            capture_output=True, text=True, env=env,
        )
        return proc

    run.log = log
    return run


def test_claim_succeeds_and_prints_branch(claim_runner):
    proc = claim_runner(42, "agent-planning")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "feature/42-Some-Title"


def test_claim_fails_when_branch_already_exists(claim_runner):
    proc = claim_runner(42, "agent-planning", branch_exists=True)
    assert proc.returncode == 3
    assert "already claimed" in proc.stderr


def test_claim_fails_when_ref_creation_loses_race(claim_runner):
    proc = claim_runner(42, "agent-planning", ref_exists=True)
    assert proc.returncode == 3
    assert "lost the race" in proc.stderr


def test_claim_swaps_agent_label_for_target_label(claim_runner):
    proc = claim_runner(42, "agent-planning")
    assert proc.returncode == 0
    calls = claim_runner.log.read_text()
    assert "issue edit 42 --add-label agent-planning --remove-label agent" in calls


def test_missing_args_is_usage_error_for_claim():
    proc = subprocess.run(
        [str(SKILL_DIR / "claim_issue.sh")],
        capture_output=True, text=True,
    )
    assert proc.returncode == 2


def test_non_numeric_issue_is_usage_error_for_claim():
    proc = subprocess.run(
        [str(SKILL_DIR / "claim_issue.sh"), "abc", "agent-planning"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 2


def test_missing_target_label_is_usage_error_for_claim():
    proc = subprocess.run(
        [str(SKILL_DIR / "claim_issue.sh"), "42"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 2


# === find_candidate.sh tests ===

FIND_GH_STUB = """\
#!/usr/bin/env bash
echo "$*" >> "$FIND_STUB_LOG"
if [ "$1" = "issue" ] && [ "$2" = "list" ]; then
  label=""
  for a in "$@"; do
    if [ "$prev" = "--label" ]; then label="$a"; fi
    prev="$a"
  done
  if [ "$label" = "agent" ]; then
    cat "$FIND_STUB_AGENT_JSON"
  elif [ "$label" = "agent-planning" ]; then
    cat "$FIND_STUB_PLANNING_JSON"
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
def plan_candidate_runner(tmp_path):
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

    def run(agent_issues, planning_issues=None, commit_dates=None, branch_names=None, stale_minutes=None, now_override=None):
        agent_json = tmp_path / "agent.json"
        agent_json.write_text(json.dumps(agent_issues))
        planning_json = tmp_path / "planning.json"
        planning_json.write_text(json.dumps(planning_issues or []))
        for branch_ref, iso_date in (commit_dates or {}).items():
            # Create any parent directories needed
            commit_file = commits_dir / f"{branch_ref}.json"
            commit_file.parent.mkdir(parents=True, exist_ok=True)
            commit_file.write_text(
                json.dumps({"commit": {"committer": {"date": iso_date}}})
            )
        for number, branch in (branch_names or {}).items():
            (branches_dir / str(number)).write_text(branch)
        env = {
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "FIND_STUB_LOG": str(log),
            "FIND_STUB_AGENT_JSON": str(agent_json),
            "FIND_STUB_PLANNING_JSON": str(planning_json),
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


def test_oldest_fresh_agent_issue_is_the_candidate(plan_candidate_runner):
    result = plan_candidate_runner(
        agent_issues=[_issue(2, "2026-08-01T00:00:00Z"), _issue(1, "2026-07-01T00:00:00Z")],
    )
    assert result["candidate"]["number"] == 1
    assert result["candidate"]["source"] == "fresh"


def test_fresh_agent_issue_preferred_over_older_stale_reclaim(plan_candidate_runner):
    result = plan_candidate_runner(
        agent_issues=[_issue(5, "2026-08-05T00:00:00Z")],
        planning_issues=[_issue(1, "2026-01-01T00:00:00Z")],
        branch_names={1: "feature/1-Old-Thing"},
        commit_dates={"feature/1-Old-Thing": "2020-01-01T00:00:00Z"},
        now_override="2026-08-06T00:00:00Z",
    )
    assert result["candidate"]["number"] == 5
    assert result["candidate"]["source"] == "fresh"


def test_stale_planning_issue_is_candidate_when_no_fresh_work(plan_candidate_runner):
    result = plan_candidate_runner(
        agent_issues=[],
        planning_issues=[_issue(1, "2026-08-01T00:00:00Z")],
        branch_names={1: "feature/1-Old-Thing"},
        commit_dates={"feature/1-Old-Thing": "2026-08-01T00:10:00Z"},
        now_override="2026-08-01T00:20:00Z",
        stale_minutes=10,
    )
    assert result["candidate"]["number"] == 1
    assert result["candidate"]["source"] == "stale-reclaim"


def test_fresh_planning_issue_is_skipped_not_candidate(plan_candidate_runner):
    result = plan_candidate_runner(
        agent_issues=[],
        planning_issues=[_issue(1, "2026-08-01T00:00:00Z")],
        branch_names={1: "feature/1-Old-Thing"},
        commit_dates={"feature/1-Old-Thing": "2026-08-01T00:19:00Z"},
        now_override="2026-08-01T00:20:00Z",
        stale_minutes=10,
    )
    assert result["candidate"] is None
    assert result["skipped"][0]["number"] == 1
    assert "in progress" in result["skipped"][0]["reason"]


def test_no_issues_at_all_yields_null_candidate(plan_candidate_runner):
    result = plan_candidate_runner(agent_issues=[], planning_issues=[])
    assert result["candidate"] is None
    assert result["skipped"] == []


def test_agent_issue_with_existing_branch_is_skipped_next_one_wins(plan_candidate_runner):
    """Regression test: an `agent`-labeled issue that already has a
    feature/{n}-* branch on origin means claim_issue.sh's label swap
    didn't fully land (branch exists but the agent label was never
    removed). Selecting it as "fresh" every time would deadlock planning
    on that one issue forever -- the walk must skip it and fall through to
    the next oldest `agent` issue instead.
    """
    result = plan_candidate_runner(
        agent_issues=[_issue(1, "2026-07-01T00:00:00Z"), _issue(2, "2026-08-01T00:00:00Z")],
        branch_names={1: "feature/1-Old-Thing"},
    )
    assert result["candidate"]["number"] == 2
    assert result["candidate"]["source"] == "fresh"
    assert result["skipped"][0]["number"] == 1
    assert "already has a feature/1-" in result["skipped"][0]["reason"]


def test_all_agent_issues_branched_falls_through_to_stale_reclaim(plan_candidate_runner):
    """If the entire `agent`-labeled pool is exhausted (every issue already
    has a branch), fall through to the existing stale `agent-planning`
    reclaim logic exactly as if the `agent` pool had been empty."""
    result = plan_candidate_runner(
        agent_issues=[_issue(1, "2026-07-01T00:00:00Z")],
        planning_issues=[_issue(2, "2026-08-01T00:00:00Z")],
        branch_names={1: "feature/1-Old-Thing", 2: "feature/2-Other-Thing"},
        commit_dates={"feature/2-Other-Thing": "2026-08-01T00:10:00Z"},
        now_override="2026-08-01T00:20:00Z",
        stale_minutes=10,
    )
    assert result["candidate"]["number"] == 2
    assert result["candidate"]["source"] == "stale-reclaim"
    numbers_skipped = {s["number"] for s in result["skipped"]}
    assert 1 in numbers_skipped


def test_non_numeric_stale_minutes_is_a_usage_error(plan_candidate_runner):
    with pytest.raises(AssertionError):
        # plan_candidate_runner asserts returncode == 0; a non-numeric
        # STALE_MINUTES must instead fail fast with a clear error.
        plan_candidate_runner(agent_issues=[], planning_issues=[], stale_minutes="two")


# === plan-orchestrator.md structural checks ===

CLAUDE_AGENTS_DIR = REPO_ROOT / "agentharness" / "data" / "claude-agents"


def test_plan_orchestrator_exists_and_has_required_sections():
    content = (CLAUDE_AGENTS_DIR / "plan-orchestrator.md").read_text()
    for heading in [
        "## Artifact persistence",
        "## Setup",
        "## Reading Agent System Prompts",
        "## Phase Loop",
        "### Phase → Agent Mapping",
        "## Task Extraction",
    ]:
        assert heading in content, f"missing section: {heading}"


def test_plan_orchestrator_has_no_developer_or_code_review_sections():
    content = (CLAUDE_AGENTS_DIR / "plan-orchestrator.md").read_text()
    for heading in [
        "## Developer/Reviewer Loop",
        "## Code Review phase",
        "## Completion",
    ]:
        assert heading not in content, f"unexpected section carried over: {heading}"


def test_plan_orchestrator_ends_with_planning_complete_message():
    content = (CLAUDE_AGENTS_DIR / "plan-orchestrator.md").read_text()
    assert "Planning complete for feat-{issue_number}. Ready for implementing." in content


def test_plan_next_issue_skill_exists_and_wires_dependencies():
    content = (SKILL_DIR / "SKILL.md").read_text()
    assert "check_concurrency.sh" in content
    assert "find_candidate.sh" in content
    assert "claim_issue.sh" in content
    assert "plan-orchestrator.md" in content
    assert "agent-ready-for-dev" in content
