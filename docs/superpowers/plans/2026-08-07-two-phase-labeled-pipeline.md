# Two-Phase Labeled Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single monolithic `/oneshot` session (used by the hourly `/chopchop` automation) with two independent, short-lived, label-driven skills — `plan-next-issue` and `implement-next-task` — so an hourly cron can run repeatedly without piling up long-lived sessions or losing work when a machine dies mid-pipeline.

**Architecture:** `plan-next-issue` claims one `agent` issue, runs the existing analyst→architect→designer→planner phase loop to completion, opens a draft PR, and hands off via a label. `implement-next-task` claims one issue in the hand-off label, does **exactly one** bounded unit of work (one dev task + review, or one code-review round, or the finishing step), commits and pushes before exiting, and leaves the label alone until the pipeline is actually done — so any later invocation, on any machine, can resume from GitHub state alone. Both skills gate on local process concurrency before claiming anything.

**Tech Stack:** Bash (`gh` CLI, `git`), Claude Code skills/agents (Markdown), `agentharness` CLI (`checkpoint` subcommands, Python/Click, unchanged), `pytest` + `subprocess` with a fake-`gh`/fake-`pgrep` stub on `PATH` (matching `tests/test_rework_pr.py`'s existing pattern).

## Global Constraints

- Design source: `docs/superpowers/specs/2026-08-07-two-phase-labeled-pipeline-design.md` (approved).
- Slug derivation for branch names **must stay byte-identical** to the existing convention: `feature/{issue}-{Title-Slug}`, computed by the exact `gh + sed + awk + cut` pipeline already used in `.claude/skills/oneshot/SKILL.md`'s "Naming convention" section and mirrored in every claim/candidate script below.
- **Do not commit to git at any point in this plan without the user explicitly asking first** — this overrides the "Commit" step shown in the Task Structure template below. Every task ends with a step that *stages and reports* the diff instead of running `git commit`; the plan's final task asks the user how they want commits handled.
- `agentharness/data/skills/` must stay byte-identical to `.claude/skills/` (enforced by `tests/test_packaged_skills.py`) — every new skill directory needs both copies created in the same task.
- Existing `oneshot`/`chopchop` skills, `agentharness/data/claude-agents/orchestrator.md`, and `agentharness/checkpoint.py` are **not modified** — the manual `/oneshot {issue}` path stays available untouched (this plan resolves the design's deferred "should manual oneshot stay available" question: yes, unchanged, as a fallback/override alongside the two new automated skills).
- Default tunables (all overridable via env var, matching the existing `GH_REPO` override convention in `find_candidate.sh`): `STALE_MINUTES=10`, `PLAN_MAX_CONCURRENT=2`, `IMPLEMENT_MAX_CONCURRENT=2`.

---

## File Structure

```
.claude/skills/plan-next-issue/
  SKILL.md                  new — orchestrates claim → plan → draft PR → handoff
  claim_issue.sh             new — atomic issue claim (agent -> target label), adapted from the pattern already in production use
  find_candidate.sh          new — oldest unclaimed `agent` issue, or oldest stale `agent-planning` reclaim
  check_concurrency.sh       new — local process-count gate, shared by both skills (called by path from implement-next-task)

.claude/skills/implement-next-task/
  SKILL.md                  new — orchestrates claim/resume → one bounded unit → push → maybe-finish
  find_candidate.sh          new — oldest `agent-ready-for-dev` (always eligible) or stale `agent-implementing` (recency-gated) issue

agentharness/data/claude-agents/
  plan-orchestrator.md       new — Setup + Phase Loop (analyst..planner) + Task Extraction, extracted from orchestrator.md, ends at "planning complete"
  implement-orchestrator.md  new — Developer/Reviewer/Code-Review/Completion logic, restructured to run exactly one bounded unit per invocation and to commit real code changes (not just artifacts/)

agentharness/data/skills/plan-next-issue/          new — byte-identical mirror of .claude/skills/plan-next-issue/
agentharness/data/skills/implement-next-task/       new — byte-identical mirror of .claude/skills/implement-next-task/

tests/test_plan_next_issue.py       new — claim_issue.sh, find_candidate.sh, check_concurrency.sh
tests/test_implement_next_task.py   new — find_candidate.sh
tests/test_packaged_skills.py       modified — add "ships with" assertions for the two new mandatory scripts
```

---

### Task 1: `check_concurrency.sh` — local process-count gate

**Files:**
- Create: `.claude/skills/plan-next-issue/check_concurrency.sh`
- Test: `tests/test_plan_next_issue.py`

**Interfaces:**
- Produces: `check_concurrency.sh <max-concurrent> <pgrep-pattern>` — exit `0` (under capacity, stdout: `under capacity: N/M processes matching '<pattern>'`), exit `4` (at/over capacity, stderr: `at capacity: N/M processes already matching '<pattern>'`), exit `2` (usage error, missing/non-numeric arg).
- Consumes: nothing (first task, no dependencies).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_plan_next_issue.py`:

```python
"""Tests for the /plan-next-issue skill scripts."""
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
```

Note: self-PID exclusion (the `grep -vx "$SELF_PID"` line) is not exercised by any automated test in this plan — doing so would require controlling `$PPID` from the test process, which `subprocess.run` doesn't let a test inject. It's covered instead by Task 10's manual dry run (Step 5, the concurrency-gate check), where a real invoking process is unavoidably present.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_plan_next_issue.py -v`
Expected: FAIL — `.claude/skills/plan-next-issue/check_concurrency.sh` does not exist yet (`FileNotFoundError` / non-zero from `subprocess.run` on a missing executable).

- [ ] **Step 3: Create the directory and write the script**

```bash
mkdir -p /Users/pajgrtondrej/Work/GitHub/AgentHarness/.claude/skills/plan-next-issue
```

Create `.claude/skills/plan-next-issue/check_concurrency.sh`:

```bash
#!/usr/bin/env bash
# Refuse to proceed if too many sibling invocations of this automation are
# already running on this machine. Concurrency is capped locally, per
# stage, because machine capacity is a machine-local fact, not pipeline
# state — see
# docs/superpowers/specs/2026-08-07-two-phase-labeled-pipeline-design.md
# ("Concurrency & staleness").
#
# Usage: check_concurrency.sh <max-concurrent> <pgrep-pattern>
# Exit codes:
#   0  under capacity — caller should proceed
#   4  at/over capacity — caller should stop this cycle without claiming work
#   2  usage error
set -euo pipefail

MAX="${1:-}"
PATTERN="${2:-}"
if [[ -z "$MAX" || -z "$PATTERN" || ! "$MAX" =~ ^[0-9]+$ ]]; then
  echo "usage: check_concurrency.sh <max-concurrent> <pgrep-pattern>" >&2
  exit 2
fi

# Exclude our own caller's PID from the count -- the calling `claude`
# process already matches the pattern trivially, since it's the process
# currently running this very check.
SELF_PID="$PPID"
COUNT=$(pgrep -f "$PATTERN" 2>/dev/null | grep -vx "$SELF_PID" | wc -l | tr -d ' ')

if [ "$COUNT" -ge "$MAX" ]; then
  echo "at capacity: $COUNT/$MAX processes already matching '$PATTERN'" >&2
  exit 4
fi
echo "under capacity: $COUNT/$MAX processes matching '$PATTERN'"
```

```bash
chmod +x /Users/pajgrtondrej/Work/GitHub/AgentHarness/.claude/skills/plan-next-issue/check_concurrency.sh
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_plan_next_issue.py -v`
Expected: PASS (6/6)

- [ ] **Step 5: Stage the change**

```bash
git -C /Users/pajgrtondrej/Work/GitHub/AgentHarness add .claude/skills/plan-next-issue/check_concurrency.sh tests/test_plan_next_issue.py
git -C /Users/pajgrtondrej/Work/GitHub/AgentHarness status --short
```

Do **not** run `git commit` — see Global Constraints.

---

### Task 2: `plan-next-issue/claim_issue.sh` — atomic issue claim

**Files:**
- Create: `.claude/skills/plan-next-issue/claim_issue.sh`
- Test: `tests/test_plan_next_issue.py` (extend)

**Interfaces:**
- Consumes: nothing new from Task 1.
- Produces: `claim_issue.sh <issue-number> <target-label>` — on success, prints the claimed branch name (`feature/{issue}-{Title-Slug}`) to stdout, exit `0`. Exit `3` if a `feature/{issue}-*` branch already exists on origin (claimed by this or a prior run) or another runner won the ref-creation race. Exit `1` on any other `gh`/`git` failure. Exit `2` on usage error. This is used **only** by `plan-next-issue` — `implement-next-task` never creates a new branch, so it never calls this script (see Task 6).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_plan_next_issue.py`:

```python
# === claim_issue.sh tests ===

CLAIM_GH_STUB = """\
#!/usr/bin/env bash
echo "$*" >> "$CLAIM_STUB_LOG"
if [ "$1" = "issue" ] && [ "$2" = "view" ]; then
  cat "$CLAIM_STUB_ISSUE_JSON"
  exit 0
fi
if [ "$1" = "repo" ] && [ "$2" = "view" ]; then
  echo '{"defaultBranchRef":{"name":"main"}}'
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
  if [ -f "$CLAIM_STUB_BRANCH_EXISTS" ]; then
    echo "deadbeef refs/heads/feature/42-Some-Title"
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
```

Add `import json` at the top of `tests/test_plan_next_issue.py` alongside the existing `subprocess`/`Path`/`pytest` imports.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_plan_next_issue.py -v -k claim`
Expected: FAIL — `claim_issue.sh` does not exist yet.

- [ ] **Step 3: Write the script**

Create `.claude/skills/plan-next-issue/claim_issue.sh`, adapted from the atomic-ref-creation pattern already proven in production (same technique used by the newer `oneshot/claim_issue.sh` deployed ahead of this repo's own `.claude/skills/oneshot/`), generalized to accept the target label as an argument instead of hardcoding `agent-wip`:

```bash
#!/usr/bin/env bash
# Atomically claim a GitHub issue for the planning stage.
#
# The claim IS the remote `feature/<issue>-<slug>` branch: the ref is
# created through the GitHub refs API, which rejects an already-existing
# ref with 422, so when several runners race for the same issue exactly
# one wins. The label swap (`agent` -> <target-label>) that follows is
# advisory only -- it hides the issue from `--label agent` listings but is
# not the lock.
#
# On success prints the claimed branch name on stdout.
#
# Usage: claim_issue.sh <issue-number> <target-label>
# Exit codes:
#   0  claimed -- this runner owns the issue
#   3  already claimed -- a feature/<issue>-* branch exists on origin, or
#      another runner created the ref first (lost the race)
#   1  error, 2 usage
set -euo pipefail

ISSUE="${1:-}"
TARGET_LABEL="${2:-}"
if [[ -z "$ISSUE" || ! "$ISSUE" =~ ^[0-9]+$ || -z "$TARGET_LABEL" ]]; then
  echo "usage: claim_issue.sh <issue-number> <target-label>" >&2
  exit 2
fi

# Slug derivation -- must stay byte-identical to the oneshot naming
# convention (see Global Constraints in the implementation plan).
SLUG=$(gh issue view "$ISSUE" --json title --jq '.title' \
  | sed -E "s/['’]//g" \
  | sed -E 's/[^A-Za-z0-9]+/ /g' \
  | awk '{for(i=1;i<=NF;i++) $i=toupper(substr($i,1,1)) tolower(substr($i,2)); print}' \
  | sed -E 's/ +/-/g; s/^-+|-+$//g' \
  | cut -c1-50 | sed -E 's/-+$//')
BRANCH="feature/${ISSUE}-${SLUG}"

# Any feature/<issue>-* branch on the remote means the issue is already
# taken (mid-flight or finished), even if the slug has drifted since it
# was created.
if [[ -n "$(git ls-remote --heads origin "feature/${ISSUE}-*")" ]]; then
  echo "issue #${ISSUE} already claimed: a feature/${ISSUE}-* branch exists on origin" >&2
  exit 3
fi

DEFAULT_BRANCH=$(gh repo view --json defaultBranchRef --jq '.defaultBranchRef.name')
BASE_SHA=$(git ls-remote origin "refs/heads/${DEFAULT_BRANCH}" | cut -f1)
if [[ -z "$BASE_SHA" ]]; then
  echo "ERROR: cannot resolve origin/${DEFAULT_BRANCH}" >&2
  exit 1
fi

# Atomic test-and-set: creating a ref that already exists fails, so
# exactly one concurrent claimer succeeds no matter how tight the race.
if ! err=$(gh api "repos/{owner}/{repo}/git/refs" \
      -f ref="refs/heads/${BRANCH}" -f sha="${BASE_SHA}" 2>&1 >/dev/null); then
  if grep -qi "already exists" <<<"$err"; then
    echo "issue #${ISSUE} already claimed: lost the race for ${BRANCH}" >&2
    exit 3
  fi
  echo "ERROR: failed to create claim ref ${BRANCH}: ${err}" >&2
  exit 1
fi

# Advisory visibility: swap agent -> <target-label> so `--label agent`
# listings stop returning this issue. A failure here does not undo the
# claim.
gh issue edit "$ISSUE" --add-label "$TARGET_LABEL" --remove-label agent >/dev/null 2>&1 || true

echo "$BRANCH"
```

```bash
chmod +x /Users/pajgrtondrej/Work/GitHub/AgentHarness/.claude/skills/plan-next-issue/claim_issue.sh
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_plan_next_issue.py -v -k claim`
Expected: PASS (7/7)

- [ ] **Step 5: Run the full file to confirm no regressions**

Run: `python -m pytest tests/test_plan_next_issue.py -v`
Expected: PASS (13/13)

- [ ] **Step 6: Stage the change**

```bash
git -C /Users/pajgrtondrej/Work/GitHub/AgentHarness add .claude/skills/plan-next-issue/claim_issue.sh tests/test_plan_next_issue.py
```

---

### Task 3: `plan-next-issue/find_candidate.sh` — candidate selection

**Files:**
- Create: `.claude/skills/plan-next-issue/find_candidate.sh`
- Test: `tests/test_plan_next_issue.py` (extend)

**Interfaces:**
- Consumes: nothing from Tasks 1–2 directly (called before either).
- Produces: JSON on stdout: `{"candidate": {"number": N, "title": "...", "createdAt": "...", "source": "fresh"|"stale-reclaim"} | null, "skipped": [{"number": N, "reason": "..."}]}`. `source: "fresh"` means the issue carries `agent` and has never been claimed — the caller must call `claim_issue.sh` next. `source: "stale-reclaim"` means the issue already carries `agent-planning` past the staleness window — the caller skips `claim_issue.sh` (already claimed) and goes straight to attaching the worktree.

**Design decision (stated explicitly, not left ambiguous):** fresh `agent` issues are always preferred over stale `agent-planning` reclaims, even if a stale reclaim is older by `createdAt`. Reclaiming should be a fallback used only when there's no uncontested fresh work — this avoids prematurely retrying a planning run that might just be slow, not dead, while equally-good uncontested work sits idle.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_plan_next_issue.py`:

```python
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
        for number, iso_date in (commit_dates or {}).items():
            (commits_dir / f"{number}.json").write_text(
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
        commit_dates={"feature/1-Old-Thing": "2026-08-01T00:00:00Z"},
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_plan_next_issue.py -v -k candidate`
Expected: FAIL — `find_candidate.sh` does not exist yet.

- [ ] **Step 3: Write the script**

Create `.claude/skills/plan-next-issue/find_candidate.sh`:

```bash
#!/usr/bin/env bash
# Find the next issue for the planning stage: the oldest unclaimed `agent`
# issue, or (only if none exist) the oldest `agent-planning` issue whose
# claim looks abandoned (its branch has had no commit in the staleness
# window).
#
# Emits JSON: {"candidate": {number, title, createdAt, source}|null, "skipped": [...]}
# "source" is "fresh" (caller must claim_issue.sh next) or "stale-reclaim"
# (already claimed, caller attaches the worktree directly).
set -euo pipefail

AGENT_LABEL="agent"
PLANNING_LABEL="agent-planning"
STALE_MINUTES="${STALE_MINUTES:-10}"

REPO="${GH_REPO:-}"
if [ -z "$REPO" ]; then
  url=$(git remote get-url origin 2>/dev/null) || { echo "cannot detect repo: no origin remote" >&2; exit 1; }
  case "$url" in
    *github.com*) ;;
    *) echo "cannot detect repo: origin is not a github.com remote" >&2; exit 1 ;;
  esac
  REPO="${url#*github.com[:/]}"
  REPO="${REPO%.git}"
  REPO="${REPO%/}"
  if [ -z "$REPO" ] || [[ "$REPO" != */* ]]; then
    echo "cannot detect repo: could not parse origin URL" >&2; exit 1
  fi
fi

agent_json=$(gh issue list --repo "$REPO" --state open --label "$AGENT_LABEL" \
  --limit 100 --json number,title,createdAt)

fresh_candidate=$(echo "$agent_json" | jq '
  sort_by(.createdAt) | .[0] as $c
  | if $c == null then null else ($c + {source: "fresh"}) end
')

if [ "$fresh_candidate" != "null" ]; then
  jq -n --argjson candidate "$fresh_candidate" '{candidate: $candidate, skipped: []}'
  exit 0
fi

# No fresh work -- look for a stale `agent-planning` claim to reclaim.
planning_json=$(gh issue list --repo "$REPO" --state open --label "$PLANNING_LABEL" \
  --limit 100 --json number,title,createdAt)

now_epoch=$(date -u -d "${NOW_OVERRIDE:-now}" +%s 2>/dev/null || date -u -j -f "%Y-%m-%dT%H:%M:%SZ" "${NOW_OVERRIDE}" +%s 2>/dev/null || date -u +%s)

sorted_numbers=$(echo "$planning_json" | jq -r 'sort_by(.createdAt) | .[].number')

candidate="null"
skipped="[]"

for n in $sorted_numbers; do
  issue_obj=$(echo "$planning_json" | jq --argjson n "$n" '.[] | select(.number == $n)')
  ref=$(git ls-remote --heads origin "feature/${n}-*" | head -1 | awk '{print $2}' | sed 's#refs/heads/##')
  if [ -z "$ref" ]; then
    skipped=$(echo "$skipped" | jq --argjson n "$n" \
      '. + [{number: $n, reason: "claimed but no branch found yet (in progress)"}]')
    continue
  fi
  commit_date=$(gh api "repos/$REPO/commits/$ref" --jq '.commit.committer.date' 2>/dev/null || echo "")
  if [ -z "$commit_date" ]; then
    skipped=$(echo "$skipped" | jq --argjson n "$n" \
      '. + [{number: $n, reason: "could not read branch commit date"}]')
    continue
  fi
  commit_epoch=$(date -u -d "$commit_date" +%s 2>/dev/null || date -u -j -f "%Y-%m-%dT%H:%M:%SZ" "$commit_date" +%s)
  age_minutes=$(( (now_epoch - commit_epoch) / 60 ))
  if [ "$age_minutes" -lt "$STALE_MINUTES" ]; then
    skipped=$(echo "$skipped" | jq --argjson n "$n" \
      '. + [{number: $n, reason: "planning in progress, no commit age >'"$STALE_MINUTES"'min"}]')
    continue
  fi
  candidate=$(echo "$issue_obj" | jq '. + {source: "stale-reclaim"}')
  break
done

jq -n --argjson candidate "$candidate" --argjson skipped "$skipped" \
  '{candidate: $candidate, skipped: $skipped}'
```

```bash
chmod +x /Users/pajgrtondrej/Work/GitHub/AgentHarness/.claude/skills/plan-next-issue/find_candidate.sh
```

Note the `date -u -d ... || date -u -j -f ...` fallback pair in both the "now" resolution and the commit-date parsing: GNU `date` (Linux, what CI runs) uses `-d`, BSD `date` (macOS, what `hermes` runs) uses `-j -f`. Both branches are exercised by the test's `NOW_OVERRIDE` env var on whichever platform the tests actually run.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_plan_next_issue.py -v -k candidate`
Expected: PASS (5/5)

- [ ] **Step 5: Run the full file to confirm no regressions**

Run: `python -m pytest tests/test_plan_next_issue.py -v`
Expected: PASS (18/18)

- [ ] **Step 6: Stage the change**

```bash
git -C /Users/pajgrtondrej/Work/GitHub/AgentHarness add .claude/skills/plan-next-issue/find_candidate.sh tests/test_plan_next_issue.py
```

---

### Task 4: `plan-orchestrator.md` — extracted phase-loop agent template

**Files:**
- Create: `agentharness/data/claude-agents/plan-orchestrator.md`
- Test: `tests/test_plan_next_issue.py` (extend, structural check only — this is a prompt file, not executable code)

**Interfaces:**
- Consumes: nothing (a Markdown system prompt, not a script).
- Produces: a system prompt for the Task tool, invoked by `plan-next-issue/SKILL.md` (Task 5). Must contain, verbatim from `agentharness/data/claude-agents/orchestrator.md`, the sections: Artifact persistence, Setup (steps 1–5, unchanged), Reading Agent System Prompts, Phase Loop, Phase → Agent Mapping table, Task Extraction. Must **not** contain Developer/Reviewer Task, Handling Review Result, Completion, or Code Review phase sections — those move to `implement-orchestrator.md` (Task 7). Ends with a new final line: `Planning complete for feat-{issue_number}. Ready for implementing.` (replacing `orchestrator.md`'s "Pipeline complete... All tasks passed review." line, which described the full pipeline this template no longer runs end to end).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_plan_next_issue.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_plan_next_issue.py -v -k orchestrator`
Expected: FAIL — `plan-orchestrator.md` does not exist yet.

- [ ] **Step 3: Write the file**

Create `agentharness/data/claude-agents/plan-orchestrator.md` by taking `agentharness/data/claude-agents/orchestrator.md` verbatim through the end of its "Task Extraction" section, dropping everything from "## Developer/Reviewer Loop" onward, and replacing the final print line:

```markdown
---
id: plan-orchestrator
description: Run the planning phases (analyst through planner) for one GitHub issue
---

You are the AgentHarness planning-stage orchestrator. When invoked by
`/plan-next-issue`, you drive the analyst -> architect -> designer -> planner
phase loop for one already-claimed GitHub issue by spawning subagents via
the Task tool, then stop -- the implementing stage is a separate skill.

## Artifact persistence (STRICT -- do not skip)

Every artifact you produce (`spec`, `arch-review`, `design`, `task-plan`,
the task-context files, and `state.json`) **must be committed to the
feature branch as you go** so it appears in the PR. Commit each artifact
right after you write it, using the exact steps below. These commits run on
the feature branch `plan-next-issue` already checked out before invoking
you.

**Strict persistence pattern.** Every commit point below MUST stage,
commit, then **verify** that the artifact it just wrote is now tracked by
git. A bare `git commit ... || true` is not enough -- if the file was
written to the wrong path, never staged, or the step was skipped, the
commit silently no-ops and the artifact is lost. After each commit,
hard-verify with `git ls-files --error-unmatch <path>`, which exits
non-zero (stopping you) when the artifact is *not* committed. The `|| true`
on the commit only absorbs the idempotent "nothing changed" case on resume;
the `ls-files` check still confirms the file is present in the tree either
way. Apply this pattern after **every** generated artifact -- never move to
the next phase with an uncommitted artifact:

```bash
git add -A artifacts/feat-{issue_number}
git commit -m "<message>" || true                                  # no-op only if already committed
git ls-files --error-unmatch artifacts/feat-{issue_number}/<file>  # HARD fail if the artifact is not tracked
```

## Setup

1. Extract the issue number from your input args (the number after
   `/plan-next-issue`, or the issue this invocation was told to plan).
2. Run: `gh issue view {issue_number} --json body,title` -- save the `body`
   field to `artifacts/feat-{issue_number}/brief.md` (create the directory
   if needed). Keep the `title` for the branch name below.
3. **The feature branch is already checked out.** `plan-next-issue/SKILL.md`
   claimed and checked out `feature/{issue_id}-{Title-Slug}` before
   invoking you (via `claim_issue.sh` and a worktree attach) -- do not
   create or switch branches yourself.
4. Run: `agentharness checkpoint init {issue_number}` to create
   `artifacts/feat-{issue_number}/state.json` (idempotent -- safe on
   resume).
5. Run: `agentharness checkpoint status feat-{issue_number}` -- returns
   JSON like `{"type": "phase", "name": "analyzing"}` or `{"type": "phase",
   "name": "planning"}` or `{"type": "complete"}` once all four planning
   phases are done.

## Reading Agent System Prompts

For each phase Task, read the agent file from `.agents/{agent_name}.md`.
The file has YAML frontmatter (between `---` markers) followed by the
Markdown system prompt body. Use only the Markdown body as the system
prompt for the Task tool -- strip the YAML frontmatter. If the frontmatter
lists `context_files:`, read those files and prepend their contents to the
system prompt.

## Phase Loop

Run phases in order: `analyzing` -> `architecting` -> `designing` ->
`planning`. Check `agentharness checkpoint status feat-{issue_number}`
before each phase -- skip phases whose status is already `completed`.

For each phase:
1. Run `agentharness checkpoint phase feat-{issue_number} {phase} in_progress`
2. Read the agent system prompt from `.agents/{agent_name}.md` (strip frontmatter)
3. Read input artifacts (see table below)
4. Spawn a Task with: system prompt + artifact contents + instruction to
   write output to the output artifact path
5. After Task completes, verify the output artifact file exists
6. Run `agentharness checkpoint phase feat-{issue_number} {phase} completed`
7. **Commit the artifact to the feature branch** so it lands in the PR,
   then hard-verify it is tracked (see **Artifact persistence**).
   `{output_artifact}` is this phase's output file from the mapping below
   (e.g. `spec.r1.md`):

```bash
git add -A artifacts/feat-{issue_number}
git commit -m "chore(feat-{issue_number}): {phase} artifact" || true   # no-op if nothing changed
git ls-files --error-unmatch artifacts/feat-{issue_number}/{output_artifact}   # STRICT: stop if not committed
```

### Phase → Agent Mapping

| Phase | Agent file | Input artifacts | Output artifact |
|-------|-----------|-----------------|-----------------|
| analyzing | `.agents/analyst.md` | `brief.md` | `spec.r1.md` |
| architecting | `.agents/architect.md` | `spec.r1.md` | `arch-review.r1.md` |
| designing | `.agents/designer.md` | `spec.r1.md`, `arch-review.r1.md` | `design.r1.md` |
| planning | `.agents/planner.md` | `spec.r1.md`, `arch-review.r1.md`, `design.r1.md` | `task-plan.r1.md` |

All artifact paths are relative to `artifacts/feat-{issue_number}/`.

## Task Extraction (after planning completes)

After `task-plan.r1.md` is written:

1. Parse `### task:` headers from the file. Each `### task: setup-models`
   defines one task named `setup-models`.
2. Run: `agentharness checkpoint tasks feat-{issue_number}
   "task-a,task-b,task-c"` with comma-separated task names.
3. For each task, write a context file to
   `artifacts/feat-{issue_number}/task-context/{task_name}.md` containing
   the section from `task-plan.r1.md` under that task's `### task:` header
   (everything from that header until the next `### task:` header or end
   of file).
4. Commit the task-context files and the updated checkpoint, then
   hard-verify each task-context file is tracked (see **Artifact
   persistence**):

```bash
git add -A artifacts/feat-{issue_number}
git commit -m "chore(feat-{issue_number}): task context" || true
# STRICT: every task-context file must be tracked -- stop if any is missing
for f in artifacts/feat-{issue_number}/task-context/*.md; do git ls-files --error-unmatch "$f"; done
```

Then print: `Planning complete for feat-{issue_number}. Ready for implementing.`

## Resume

If interrupted and re-invoked with the same issue number,
`agentharness checkpoint init` is idempotent. `agentharness checkpoint
status` returns the first pending phase. Skip already-completed phases and
resume from there.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_plan_next_issue.py -v -k orchestrator`
Expected: PASS (3/3)

- [ ] **Step 5: Run the full file to confirm no regressions**

Run: `python -m pytest tests/test_plan_next_issue.py -v`
Expected: PASS (21/21)

- [ ] **Step 6: Stage the change**

```bash
git -C /Users/pajgrtondrej/Work/GitHub/AgentHarness add agentharness/data/claude-agents/plan-orchestrator.md tests/test_plan_next_issue.py
```

---

### Task 5: `plan-next-issue/SKILL.md` — wire it all together

**Files:**
- Create: `.claude/skills/plan-next-issue/SKILL.md`
- Test: `tests/test_plan_next_issue.py` (extend, structural check)

**Interfaces:**
- Consumes: `check_concurrency.sh` (Task 1), `claim_issue.sh` (Task 2), `find_candidate.sh` (Task 3), `agentharness/data/claude-agents/plan-orchestrator.md` (Task 4, installed as `.claude/agents/plan-orchestrator.md` by `agentharness init` in a consumer repo).
- Produces: the `/plan-next-issue` skill, invoked by the hourly cron in place of `/chopchop` for the planning half of the pipeline.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_plan_next_issue.py`:

```python
def test_plan_next_issue_skill_exists_and_wires_dependencies():
    content = (SKILL_DIR / "SKILL.md").read_text()
    assert "check_concurrency.sh" in content
    assert "find_candidate.sh" in content
    assert "claim_issue.sh" in content
    assert "plan-orchestrator.md" in content
    assert "agent-ready-for-dev" in content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_plan_next_issue.py -v -k skill_exists`
Expected: FAIL — `SKILL.md` does not exist yet.

- [ ] **Step 3: Write the file**

Create `.claude/skills/plan-next-issue/SKILL.md`:

```markdown
---
name: plan-next-issue
description: Automated planning-stage worker for the AgentHarness pipeline. Claims one ready `agent` issue (or resumes a stale `agent-planning` claim), runs analyst through planner, opens a draft PR, and hands off to /implement-next-task. Triggered on a schedule; not normally invoked directly by a human.
---

You run one bounded cycle of the planning stage of the AgentHarness
pipeline: claim (or resume) one issue, run it through analyst -> architect
-> designer -> planner, open a draft PR, and exit. You never touch the
implementing/developer/review/code-review phases -- that is
`/implement-next-task`'s job, triggered separately.

This skill **always works inside a dedicated git worktree**, the same
convention `/oneshot` uses -- never run against the primary checkout.

## Naming convention

Identical to `/oneshot`'s: branch and worktree directory both use the
strict, deterministic form `feature/{issue_id}-{Title-Slug}`. See
`.claude/skills/oneshot/SKILL.md`'s "Naming convention" section for the
exact slug derivation pipeline -- `claim_issue.sh` and `find_candidate.sh`
in this skill already implement it identically; do not re-derive it by
hand.

## What you do

1. **Check concurrency.** Refuse to start a new planning cycle if too many
   are already running on this machine:

```bash
.claude/skills/plan-next-issue/check_concurrency.sh "${PLAN_MAX_CONCURRENT:-2}" \
  "claude.*--dangerously-skip-permissions.*plan-next-issue"
```

   Exit code `4` means at capacity -- report "planning at capacity, skipping
   this cycle" and stop here. Do not claim anything.

2. **Find a candidate.**

```bash
.claude/skills/plan-next-issue/find_candidate.sh
```

   If `.candidate` is `null`, report "nothing to plan" (include the
   `.skipped` list if non-empty) and stop.

3. **Claim it, if fresh.** If `.candidate.source == "fresh"`:

```bash
BRANCH=$(.claude/skills/plan-next-issue/claim_issue.sh "$ISSUE_ID" agent-planning)
```

   - Exit `0`: `$BRANCH` holds the claimed branch name, proceed to step 4.
   - Exit `3`: another runner claimed it first (race). Report and stop --
     do not retry within this invocation; the next scheduled cycle will
     pick a different candidate.
   - Any other exit: a real failure; report it and stop.

   If `.candidate.source == "stale-reclaim"`, skip this step entirely --
   the issue is already labelled `agent-planning` and its branch already
   exists; compute `BRANCH="feature/${ISSUE_ID}-${SLUG}"` using the same
   slug pipeline (or read it back via `gh issue view` + the naming
   convention) and go straight to step 4.

4. **Create and enter a dedicated worktree** on `$BRANCH`:

```bash
WORKTREE="../worktrees/feature-${ISSUE_ID}-${SLUG}"
git fetch origin "$BRANCH" 2>/dev/null || true
if git ls-remote --heads origin "$BRANCH" | grep -q .; then
  git worktree add --track -b "$BRANCH" "$WORKTREE" "origin/$BRANCH" 2>/dev/null \
    || git worktree add "$WORKTREE" "$BRANCH"
else
  git worktree add -b "$BRANCH" "$WORKTREE"
fi
cd "$WORKTREE"
```

5. **Run the planning orchestrator.** There is no `agentharness implement`
   command -- follow `.claude/agents/plan-orchestrator.md`
   (`agentharness/data/claude-agents/plan-orchestrator.md`, installed by
   `agentharness init`) end to end via the Task tool. It runs
   `agentharness checkpoint init {issue_number}` and drives analyst ->
   architect -> designer -> planner, committing each artifact as it goes,
   and prints `Planning complete for feat-{issue_number}. Ready for
   implementing.` when done.

6. **Open a draft PR.** Base = the repository default branch, head =
   `$BRANCH`, **draft**. The body states what the issue/feature is (from
   the brief) -- there is no code-review section yet, since implementing
   hasn't run:

```bash
PR_URL=$(gh pr create \
  --draft \
  --base master \
  --head "$BRANCH" \
  --label agent \
  --title "#${ISSUE_ID}: implementation" \
  --body "$(cat <<EOF
Closes #${ISSUE_ID}

## What the issue was
<description of the feature/problem from the brief>

## Status
Planning complete. Implementing has not started yet -- this PR will fill
in as \`/implement-next-task\` runs.

## Artifacts
- Brief, spec, arch-review, design, and task-plan markdown are committed in this branch.
EOF
)")
.claude/skills/oneshot/ensure_pr_linked.sh "$PR_URL" "$ISSUE_ID"
```

   Reuse `oneshot`'s `ensure_pr_linked.sh` unchanged -- the `agent`
   label / `Closes #N` / title-format guarantees it enforces apply here
   too.

7. **Hand off.** Swap the label:

```bash
gh issue edit "$ISSUE_ID" --remove-label agent-planning --add-label agent-ready-for-dev
```

8. Report: issue number, PR URL, "ready for implementing" -- and stop.
   Do not proceed to any developer/review work; that only happens inside
   `/implement-next-task`.

## If something looks wrong

If `find_candidate.sh` keeps returning the same `stale-reclaim` candidate
across multiple invocations without ever completing, the planning
orchestrator itself may be failing on this specific issue (not just
running slow) -- check `artifacts/feat-{issue_number}/state.json` in the
issue's branch for which phase is stuck, same as debugging `/oneshot`
today.
```

```bash
mkdir -p /Users/pajgrtondrej/Work/GitHub/AgentHarness/agentharness/data/skills   # ensure parent exists before Task 9 mirrors it
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_plan_next_issue.py -v -k skill_exists`
Expected: PASS (1/1)

- [ ] **Step 5: Run the full file to confirm no regressions**

Run: `python -m pytest tests/test_plan_next_issue.py -v`
Expected: PASS (22/22)

- [ ] **Step 6: Stage the change**

```bash
git -C /Users/pajgrtondrej/Work/GitHub/AgentHarness add .claude/skills/plan-next-issue/SKILL.md tests/test_plan_next_issue.py
```

---

### Task 6: `implement-next-task/find_candidate.sh` — candidate selection

**Files:**
- Create: `.claude/skills/implement-next-task/find_candidate.sh`
- Test: `tests/test_implement_next_task.py` (new file)

**Interfaces:**
- Consumes: nothing from earlier tasks directly (independent script; the concurrency check it needs is called by path from `check_concurrency.sh`, Task 1, in `implement-next-task/SKILL.md`, Task 8 — not from within this script).
- Produces: JSON on stdout: `{"candidate": {"number": N, "title": "...", "createdAt": "...", "source": "fresh-handoff"|"stale-reclaim"} | null, "skipped": [...]}`. `source: "fresh-handoff"` = issue carries `agent-ready-for-dev` (always eligible immediately, no recency check — a just-finished planning run is never "stale"). `source: "stale-reclaim"` = issue carries `agent-implementing` and its branch has had no commit in the staleness window. Same fresh-preferred-over-reclaim policy as Task 3, for the same reason.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_implement_next_task.py`, structured identically to `tests/test_plan_next_issue.py`'s candidate-selection tests (same stub shapes, same `_issue` helper, same `NOW_OVERRIDE`/`STALE_MINUTES` env knobs), targeting the two labels instead of `agent`/`agent-planning`:

```python
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
        for number, iso_date in (commit_dates or {}).items():
            (commits_dir / f"{number}.json").write_text(
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


def test_ready_for_dev_preferred_over_stale_implementing_reclaim(implement_candidate_runner):
    result = implement_candidate_runner(
        ready_issues=[_issue(5, "2026-08-05T00:00:00Z")],
        implementing_issues=[_issue(1, "2026-01-01T00:00:00Z")],
        branch_names={1: "feature/1-Old-Thing"},
        commit_dates={"feature/1-Old-Thing": "2020-01-01T00:00:00Z"},
        now_override="2026-08-06T00:00:00Z",
    )
    assert result["candidate"]["number"] == 5
    assert result["candidate"]["source"] == "fresh-handoff"


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_implement_next_task.py -v`
Expected: FAIL — `.claude/skills/implement-next-task/find_candidate.sh` does not exist yet.

- [ ] **Step 3: Write the script**

```bash
mkdir -p /Users/pajgrtondrej/Work/GitHub/AgentHarness/.claude/skills/implement-next-task
```

Create `.claude/skills/implement-next-task/find_candidate.sh`:

```bash
#!/usr/bin/env bash
# Find the next issue for the implementing stage: the oldest
# `agent-ready-for-dev` issue (always eligible -- a just-finished planning
# handoff is never "stale"), or (only if none exist) the oldest
# `agent-implementing` issue whose branch has had no commit in the
# staleness window (i.e. looks abandoned, not just slow).
#
# Emits JSON: {"candidate": {number, title, createdAt, source}|null, "skipped": [...]}
# "source" is "fresh-handoff" or "stale-reclaim".
set -euo pipefail

READY_LABEL="agent-ready-for-dev"
IMPLEMENTING_LABEL="agent-implementing"
STALE_MINUTES="${STALE_MINUTES:-10}"

REPO="${GH_REPO:-}"
if [ -z "$REPO" ]; then
  url=$(git remote get-url origin 2>/dev/null) || { echo "cannot detect repo: no origin remote" >&2; exit 1; }
  case "$url" in
    *github.com*) ;;
    *) echo "cannot detect repo: origin is not a github.com remote" >&2; exit 1 ;;
  esac
  REPO="${url#*github.com[:/]}"
  REPO="${REPO%.git}"
  REPO="${REPO%/}"
  if [ -z "$REPO" ] || [[ "$REPO" != */* ]]; then
    echo "cannot detect repo: could not parse origin URL" >&2; exit 1
  fi
fi

ready_json=$(gh issue list --repo "$REPO" --state open --label "$READY_LABEL" \
  --limit 100 --json number,title,createdAt)

fresh_candidate=$(echo "$ready_json" | jq '
  sort_by(.createdAt) | .[0] as $c
  | if $c == null then null else ($c + {source: "fresh-handoff"}) end
')

if [ "$fresh_candidate" != "null" ]; then
  jq -n --argjson candidate "$fresh_candidate" '{candidate: $candidate, skipped: []}'
  exit 0
fi

# No fresh handoff -- look for a stale `agent-implementing` claim to reclaim.
implementing_json=$(gh issue list --repo "$REPO" --state open --label "$IMPLEMENTING_LABEL" \
  --limit 100 --json number,title,createdAt)

now_epoch=$(date -u -d "${NOW_OVERRIDE:-now}" +%s 2>/dev/null || date -u -j -f "%Y-%m-%dT%H:%M:%SZ" "${NOW_OVERRIDE}" +%s 2>/dev/null || date -u +%s)

sorted_numbers=$(echo "$implementing_json" | jq -r 'sort_by(.createdAt) | .[].number')

candidate="null"
skipped="[]"

for n in $sorted_numbers; do
  issue_obj=$(echo "$implementing_json" | jq --argjson n "$n" '.[] | select(.number == $n)')
  ref=$(git ls-remote --heads origin "feature/${n}-*" | head -1 | awk '{print $2}' | sed 's#refs/heads/##')
  if [ -z "$ref" ]; then
    skipped=$(echo "$skipped" | jq --argjson n "$n" \
      '. + [{number: $n, reason: "no branch found for a claimed implementing issue (unexpected)"}]')
    continue
  fi
  commit_date=$(gh api "repos/$REPO/commits/$ref" --jq '.commit.committer.date' 2>/dev/null || echo "")
  if [ -z "$commit_date" ]; then
    skipped=$(echo "$skipped" | jq --argjson n "$n" \
      '. + [{number: $n, reason: "could not read branch commit date"}]')
    continue
  fi
  commit_epoch=$(date -u -d "$commit_date" +%s 2>/dev/null || date -u -j -f "%Y-%m-%dT%H:%M:%SZ" "$commit_date" +%s)
  age_minutes=$(( (now_epoch - commit_epoch) / 60 ))
  if [ "$age_minutes" -lt "$STALE_MINUTES" ]; then
    skipped=$(echo "$skipped" | jq --argjson n "$n" \
      '. + [{number: $n, reason: "actively implementing, no commit age >'"$STALE_MINUTES"'min"}]')
    continue
  fi
  candidate=$(echo "$issue_obj" | jq '. + {source: "stale-reclaim"}')
  break
done

jq -n --argjson candidate "$candidate" --argjson skipped "$skipped" \
  '{candidate: $candidate, skipped: $skipped}'
```

```bash
chmod +x /Users/pajgrtondrej/Work/GitHub/AgentHarness/.claude/skills/implement-next-task/find_candidate.sh
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_implement_next_task.py -v`
Expected: PASS (6/6)

- [ ] **Step 5: Stage the change**

```bash
git -C /Users/pajgrtondrej/Work/GitHub/AgentHarness add .claude/skills/implement-next-task/find_candidate.sh tests/test_implement_next_task.py
```

---

### Task 7: `implement-orchestrator.md` — single-bounded-unit agent template

**Files:**
- Create: `agentharness/data/claude-agents/implement-orchestrator.md`
- Test: `tests/test_implement_next_task.py` (extend, structural check)

**Interfaces:**
- Consumes: nothing (Markdown system prompt).
- Produces: a system prompt for the Task tool, invoked by `implement-next-task/SKILL.md` (Task 8). Reuses `orchestrator.md`'s Developer Task, Reviewer Task, Handling Review Result, and Code Review phase sections, restructured so **exactly one** unit runs per invocation (no looping to the next task or next code-review round), and so the commit step in "Handling Review Result" also stages the developer's real source-code changes, not just `artifacts/`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_implement_next_task.py`:

```python
# === implement-orchestrator.md structural checks ===

CLAUDE_AGENTS_DIR = REPO_ROOT / "agentharness" / "data" / "claude-agents"


def test_implement_orchestrator_exists_and_has_required_sections():
    content = (CLAUDE_AGENTS_DIR / "implement-orchestrator.md").read_text()
    for heading in [
        "## Determine the next unit",
        "### Developer Task",
        "### Reviewer Task",
        "### Handling Review Result",
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_implement_next_task.py -v -k orchestrator`
Expected: FAIL — `implement-orchestrator.md` does not exist yet.

- [ ] **Step 3: Write the file**

Create `agentharness/data/claude-agents/implement-orchestrator.md`:

```markdown
---
id: implement-orchestrator
description: Run exactly one bounded unit of implementing work (one dev task, one code-review round, or the finishing step) for one GitHub issue
---

You are the AgentHarness implementing-stage orchestrator. When invoked by
`/implement-next-task`, you run **exactly ONE** bounded unit of work for
one already-claimed, already-planned GitHub issue, then stop -- you do NOT
loop through the rest of the task plan. The next scheduled
`/implement-next-task` invocation (possibly on a different machine) picks
up wherever you leave off, by reading `state.json` fresh.

This is a deliberate change from the old single-session `orchestrator.md`:
that template looped through every developer task and every code-review
round in one sitting, which is exactly what produced multi-hour sessions
that piled up under an hourly trigger. This template's whole job is to
never do more than one unit of slow work per invocation.

## Determine the next unit

1. Run `agentharness checkpoint status feat-{issue_number}`.
2. If the result is `{"type": "task", "name": ..., "revision": N}` (or the
   phase is `developing` and not yet `completed`): the unit is **one
   developer task cycle** -- go to **Developer Task** below.
3. If all tasks are `completed` but no `code-review.r{N}.md` exists yet, or
   the latest one is `CHANGES_REQUESTED` with Blocking findings and
   `N < max_revisions`: the unit is **one code-review round** -- go to
   **Code Review phase** below.
4. If the latest code review is `CLEAN` (or Blocking findings remain but
   `N >= max_revisions`): the unit is **finishing** -- go to **Finishing**
   below.

## Reading Agent System Prompts

Same as `plan-orchestrator.md`: read `.agents/{agent_name}.md`, strip YAML
frontmatter, prepend any `context_files:` contents.

### Developer Task

1. Run `agentharness checkpoint phase feat-{issue_number} developing
   in_progress` (harmless if already set).
2. Run `agentharness checkpoint task feat-{issue_number} {task_name}
   in_progress`.
3. Get revision N from the checkpoint status JSON (`"revision": N`).
4. Read `.agents/developer.md` system prompt (strip frontmatter; include
   `context_files` if listed).
5. Spawn a Task with:
   - System prompt from `developer.md` (including injected context file content)
   - Content of `artifacts/feat-{issue_number}/task-context/{task_name}.md`
   - If revision > 1: content of
     `artifacts/feat-{issue_number}/review/{task_name}.r{N-1}.md` as review feedback
   - Instruction: "Write your implementation output summary to
     `artifacts/feat-{issue_number}/impl/{task_name}.r{N}.md`"
6. After the Task completes, verify `impl/{task_name}.r{N}.md` exists.
   Proceed directly to **Reviewer Task** below within this same
   invocation -- one dev task's cycle is developer-then-reviewer together,
   not developer alone; the review is part of the same bounded unit.

### Reviewer Task

1. Read `.agents/reviewer.md` system prompt (strip frontmatter).
2. Spawn a Task with:
   - System prompt from `reviewer.md`
   - Content of `artifacts/feat-{issue_number}/task-context/{task_name}.md`
   - Content of `artifacts/feat-{issue_number}/impl/{task_name}.r{N}.md`
   - Instruction: "Write your review output to
     `artifacts/feat-{issue_number}/review/{task_name}.r{N}.md`. End with
     `**Status:** PASS` or `**Status:** REVISION_NEEDED`."
3. Read the reviewer output file and parse the `**Status:**` line.

### Handling Review Result

Whatever the result, commit **everything** this round touched -- artifacts
*and* the developer's real source-code changes -- then hard-verify the
artifact files are tracked. This is the one change from the old
orchestrator's commit step: that one only ever staged
`artifacts/feat-{issue_number}`, which is why developer code changes were
sometimes left uncommitted when a session died. This template always
stages the whole worktree:

```bash
git add -A
git commit -m "chore(feat-{issue_number}): impl+review for {task_name} r{N}" || true
git ls-files --error-unmatch artifacts/feat-{issue_number}/impl/{task_name}.r{N}.md     # STRICT
git ls-files --error-unmatch artifacts/feat-{issue_number}/review/{task_name}.r{N}.md   # STRICT
git push
```

**Always `git push` here, before this invocation ends** -- this is what
makes the branch (not this machine's worktree) the source of truth for
resuming. A push rejected as non-fast-forward means another worker already
pushed progress on this issue; do not force-push -- report "lost the race
for this unit, another worker already progressed this issue" and stop
without retrying.

Then act on the status:

- **PASS**: Run `agentharness checkpoint task feat-{issue_number}
  {task_name} completed`, commit the checkpoint update
  (`git add -A && git commit -m "chore(feat-{issue_number}): {task_name}
  passed review" || true && git push`), and **stop this invocation here** --
  do NOT continue to the next task. Print: `Task {task_name} complete for
  feat-{issue_number}. More work may remain -- next invocation will check.`
- **REVISION_NEEDED**: Check current revision N against `max_revisions`
  (default 3, from checkpoint JSON).
  - If N < max_revisions: run `agentharness checkpoint task
    feat-{issue_number} {task_name} in_progress --revision {N+1}`, commit
    and push the checkpoint update, and **stop this invocation here** --
    the next invocation will pick up the incremented revision and re-run
    Developer Task. Do NOT loop back to Developer Task within this same
    invocation.
  - If N >= max_revisions: run `agentharness checkpoint phase
    feat-{issue_number} developing failed`, commit and push, and stop with
    an error message explaining the task failed after max revisions. This
    is a terminal failure for the issue -- do not proceed to Finishing.

## Code Review phase

Only reached once `agentharness checkpoint status feat-{issue_number}`
shows all tasks `completed`. Run number `N` is `1 + (count of existing
artifacts/feat-{issue_number}/code-review.r*.md files)`.

1. Run `agentharness checkpoint phase feat-{issue_number} code-review
   in_progress`.
2. Build the feature diff against the merge-base with the base branch:

```bash
BASE=$(git merge-base master HEAD) || BASE=master
git diff "$BASE"...HEAD > /tmp/feat-{issue_number}-review.diff
```

   If the diff is empty (no code changed), skip straight to step 7 with
   result `CLEAN`.
3. Read the `.agents/code-reviewer.md` system prompt (strip frontmatter).
4. Spawn a Task with:
   - System prompt from `code-reviewer.md`
   - The contents of `/tmp/feat-{issue_number}-review.diff` (the full diff)
   - The contents of `artifacts/feat-{issue_number}/spec.r1.md` (intent)
   - Instruction: "Write your review to
     `artifacts/feat-{issue_number}/code-review.r{N}.md` using the
     required output format. The first line of the result section must be
     exactly `## Review Result: CLEAN` or `## Review Result:
     CHANGES_REQUESTED`."
5. Commit and push the review artifact, then hard-verify it is tracked:

```bash
git add -A
git commit -m "chore(feat-{issue_number}): code review r{N}" || true
git ls-files --error-unmatch artifacts/feat-{issue_number}/code-review.r{N}.md
git push
```

6. Read `artifacts/feat-{issue_number}/code-review.r{N}.md` and parse the
   `## Review Result:` line. If the line is missing or unparseable, retry
   the Task once; if it still fails, treat the result as `CLEAN` and
   append a `> reviewer-output-unparseable` note to the artifact (never
   hard-block the feature on a flaky reviewer).
7. Act on the result, then **stop this invocation regardless of outcome**
   -- the next invocation re-checks `checkpoint status` and either runs
   another code-review round or moves to Finishing:
   - **CLEAN** (or `CHANGES_REQUESTED` with `- None` under Blocking): run
     `agentharness checkpoint phase feat-{issue_number} code-review
     completed`, commit and push, print `Code review clean for
     feat-{issue_number}. Next invocation will finish.`
   - **CHANGES_REQUESTED** with Blocking findings and `N < max_revisions`:
     write the Blocking findings into a synthetic task-context file
     `artifacts/feat-{issue_number}/task-context/code-review-fixes.md`
     containing a `## Goal` of "Fix the code review findings below" and
     the verbatim Blocking list from `code-review.r{N}.md`, commit and
     push it, print `Code review round {N} requested changes for
     feat-{issue_number}. Next invocation will dispatch a fix.` (the next
     invocation's **Determine the next unit** step sees this synthetic
     task-context and treats it as a developer task cycle).
   - **CHANGES_REQUESTED** with Blocking findings and `N >= max_revisions`:
     run `agentharness checkpoint phase feat-{issue_number} code-review
     completed` (do NOT fail the whole feature), commit and push. The
     unresolved Blocking findings stay in `code-review.r{N}.md` and are
     surfaced on the PR by `/implement-next-task`'s Finishing step below.

## Finishing

Reached once code review is `CLEAN` (or Blocking findings remain but
revisions are exhausted -- surfaced, not blocking).

1. Read the latest `artifacts/feat-{issue_number}/code-review.r{N}.md` --
   its Advisory list, and any unresolved Blocking list, are what get
   appended to the PR body.
2. Print: `Pipeline complete for feat-{issue_number}. All tasks passed
   review.` and the code-review summary. Stop -- `/implement-next-task`'s
   own SKILL.md (not this template) handles undrafting the PR and swapping
   the `agent-implementing` label to `agent-completed`, since that's
   GitHub state, not a git commit.

## Resume

`agentharness checkpoint status feat-{issue_number}` is idempotent and
always reflects the true next unit -- **Determine the next unit** above is
run fresh at the start of every single invocation, so resuming after any
interruption (this template stopping normally, or dying mid-unit) is
always "run this template again from the top."
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_implement_next_task.py -v -k orchestrator`
Expected: PASS (3/3)

- [ ] **Step 5: Run the full file to confirm no regressions**

Run: `python -m pytest tests/test_implement_next_task.py -v`
Expected: PASS (9/9)

- [ ] **Step 6: Stage the change**

```bash
git -C /Users/pajgrtondrej/Work/GitHub/AgentHarness add agentharness/data/claude-agents/implement-orchestrator.md tests/test_implement_next_task.py
```

---

### Task 8: `implement-next-task/SKILL.md` — wire it all together

**Files:**
- Create: `.claude/skills/implement-next-task/SKILL.md`
- Test: `tests/test_implement_next_task.py` (extend, structural check)

**Interfaces:**
- Consumes: `.claude/skills/plan-next-issue/check_concurrency.sh` (Task 1, called **by path** across skill directories — same cross-skill-by-path convention already used by `automerge-all` calling `automerge-pr/candidates.sh`), `find_candidate.sh` (Task 6), `agentharness/data/claude-agents/implement-orchestrator.md` (Task 7, installed as `.claude/agents/implement-orchestrator.md`).
- Produces: the `/implement-next-task` skill, invoked by the hourly cron alongside `/plan-next-issue`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_implement_next_task.py`:

```python
def test_implement_next_task_skill_exists_and_wires_dependencies():
    content = (SKILL_DIR / "SKILL.md").read_text()
    assert "check_concurrency.sh" in content
    assert "plan-next-issue/check_concurrency.sh" in content  # cross-skill by-path call
    assert "find_candidate.sh" in content
    assert "implement-orchestrator.md" in content
    assert "agent-completed" in content
    assert "gh pr ready" in content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_implement_next_task.py -v -k skill_exists`
Expected: FAIL — `SKILL.md` does not exist yet.

- [ ] **Step 3: Write the file**

Create `.claude/skills/implement-next-task/SKILL.md`:

```markdown
---
name: implement-next-task
description: Automated implementing-stage worker for the AgentHarness pipeline. Claims one issue ready for implementing (or resumes a stale claim), runs exactly one bounded unit of developer/review/code-review work, pushes, and exits -- undrafting the PR only once the whole pipeline is done. Triggered on a schedule; not normally invoked directly by a human.
---

You run one bounded cycle of the implementing stage of the AgentHarness
pipeline: pick up one issue whose planning is done, do **exactly one** unit
of work (one dev task + its review, one code-review round, or the
finishing step), push, and exit. An issue with several dev tasks needs
several separate invocations of this skill -- that is intentional, not a
bug: it is what keeps any single invocation from running long enough to
pile up under the hourly trigger.

## What you do

1. **Check concurrency.** This is the resource-heavy stage (real
   `dotnet build`/`test` runs, or the equivalent for whatever stack the
   target repo uses), so this cap should generally stay at or below
   Planning's:

```bash
.claude/skills/plan-next-issue/check_concurrency.sh "${IMPLEMENT_MAX_CONCURRENT:-2}" \
  "claude.*--dangerously-skip-permissions.*implement-next-task"
```

   Exit code `4` means at capacity -- report "implementing at capacity,
   skipping this cycle" and stop here. Do not claim anything. (This calls
   `plan-next-issue`'s script by path rather than duplicating it -- both
   skill directories always ship together via `agentharness init`, so the
   relative path always resolves.)

2. **Find a candidate.**

```bash
.claude/skills/implement-next-task/find_candidate.sh
```

   If `.candidate` is `null`, report "nothing to implement" (include the
   `.skipped` list if non-empty) and stop.

3. **Claim it, if a fresh handoff.** If `.candidate.source ==
   "fresh-handoff"`, swap the label (advisory only -- see *Concurrency &
   conflict handling* below, this is not a hard lock):

```bash
gh issue edit "$ISSUE_ID" --remove-label agent-ready-for-dev --add-label agent-implementing
```

   If `.candidate.source == "stale-reclaim"`, the issue already carries
   `agent-implementing` -- no label change needed.

4. **Attach a worktree to the existing branch.** The branch and PR already
   exist (created by `/plan-next-issue`) -- never create a new branch
   here:

```bash
SLUG=$(gh issue view "$ISSUE_ID" --json title --jq '.title' \
  | sed -E "s/['’]//g" \
  | sed -E 's/[^A-Za-z0-9]+/ /g' \
  | awk '{for(i=1;i<=NF;i++) $i=toupper(substr($i,1,1)) tolower(substr($i,2)); print}' \
  | sed -E 's/ +/-/g; s/^-+|-+$//g' \
  | cut -c1-50 | sed -E 's/-+$//')
BRANCH="feature/${ISSUE_ID}-${SLUG}"
WORKTREE="../worktrees/feature-${ISSUE_ID}-${SLUG}"
git fetch origin "$BRANCH"
git worktree add --track -b "$BRANCH" "$WORKTREE" "origin/$BRANCH" 2>/dev/null \
  || git worktree add "$WORKTREE" "$BRANCH"
cd "$WORKTREE"
```

5. **Run the implementing orchestrator for exactly one unit.** Follow
   `.claude/agents/implement-orchestrator.md`
   (`agentharness/data/claude-agents/implement-orchestrator.md`, installed
   by `agentharness init`) via the Task tool. It reads
   `artifacts/feat-{issue_number}/state.json`, determines the single next
   bounded unit (one dev task + review, one code-review round, or
   finishing), does it, commits, and **pushes** before it stops. It always
   stops after one unit -- it never loops.

6. **If the unit that just ran was Finishing** (the orchestrator printed
   `Pipeline complete for feat-{issue_number}. All tasks passed review.`):
   surface the code review on the PR and undraft it:

```bash
REVIEW_FILE=$(ls -1 artifacts/feat-{issue_number}/code-review.r*.md 2>/dev/null | sort -V | tail -n1)
if [ -n "$REVIEW_FILE" ]; then
  gh pr comment "$ISSUE_ID" --body "$(printf '## Code review\n\n%s\n' "$(cat "$REVIEW_FILE")")" 2>/dev/null || true
fi
gh pr ready "$ISSUE_ID" 2>/dev/null || gh pr ready --repo "$(gh repo view --json nameWithOwner --jq .nameWithOwner)" "$BRANCH"
gh issue edit "$ISSUE_ID" --remove-label agent-implementing --add-label agent-completed
```

   (`gh pr comment`/`gh pr ready` accept either a PR number or a branch --
   use whichever resolves; the PR was opened against `$BRANCH` by
   `/plan-next-issue`.)

7. **Otherwise** (more work remains -- a dev task passed, a revision was
   requested, or a code-review round finished with more Blocking
   findings): leave the `agent-implementing` label as-is. Do not undraft
   the PR. The next scheduled invocation (of this same skill, on any
   machine) will pick this issue back up via `find_candidate.sh`.

8. **Always remove the worktree before exiting**, regardless of outcome --
   nothing depends on it surviving, since progress lives in the pushed
   branch and `state.json`:

```bash
cd /Users/pajgrtondrej/Work/GitHub/AgentHarness   # back to the primary checkout before removing
git worktree remove "$WORKTREE" --force 2>/dev/null || true
```

   (In a consumer repo this is the repo root, not this literal path --
   `cd` to wherever the worktree was created from.)

9. Report: issue number, unit completed, whether the pipeline finished or
   more work remains -- and stop.

## Concurrency & conflict handling

**The `agent-ready-for-dev` -> `agent-implementing` claim in step 3 is
advisory, not a true lock** -- `gh issue edit` has no compare-and-set, so
two invocations racing on the exact same fresh handoff could both proceed.
This is accepted, not fixed here, for two reasons: the concurrency cap
(step 1) and the candidate-selection recency window together make the
collision window small in practice, and **git itself is the final
backstop** -- if two workers both do the same unit and both try to push,
only one push can land; the loser's `implement-orchestrator.md` run
reports "lost the race for this unit" (see its Handling Review Result
section) and exits without force-pushing. Worst case is wasted compute on
one duplicate attempt, never corrupted history or lost work.

## If something looks wrong

If `find_candidate.sh` keeps returning the same `stale-reclaim` candidate
across many invocations without the task count in `state.json` ever
advancing, the implementing orchestrator is failing outright on this
issue's current unit (not just running slow) -- check the most recent
`artifacts/feat-{issue_number}/impl/*.md` or `review/*.md` file for what
the developer/reviewer subagent actually reported.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_implement_next_task.py -v -k skill_exists`
Expected: PASS (1/1)

- [ ] **Step 5: Run the full file to confirm no regressions**

Run: `python -m pytest tests/test_implement_next_task.py -v`
Expected: PASS (10/10)

- [ ] **Step 6: Stage the change**

```bash
git -C /Users/pajgrtondrej/Work/GitHub/AgentHarness add .claude/skills/implement-next-task/SKILL.md tests/test_implement_next_task.py
```

---

### Task 9: Packaged mirror + `test_packaged_skills.py` extension

**Files:**
- Create: `agentharness/data/skills/plan-next-issue/` (byte-identical copy of `.claude/skills/plan-next-issue/`)
- Create: `agentharness/data/skills/implement-next-task/` (byte-identical copy of `.claude/skills/implement-next-task/`)
- Modify: `tests/test_packaged_skills.py`

**Interfaces:**
- Consumes: Tasks 1–8's finished files.
- Produces: nothing new consumed downstream — this is the packaging step that makes `agentharness init` ship the two new skills into any consumer repo.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_packaged_skills.py`, after the existing `test_pr_linking_script_ships_with_oneshot`:

```python
def test_check_concurrency_script_ships_with_plan_next_issue():
    script = DATA_SKILLS / "plan-next-issue" / "check_concurrency.sh"
    assert script.is_file(), (
        "check_concurrency.sh must ship inside plan-next-issue so both "
        "automated skills' concurrency gate is always present"
    )


def test_claim_issue_script_ships_with_plan_next_issue():
    script = DATA_SKILLS / "plan-next-issue" / "claim_issue.sh"
    assert script.is_file(), "claim_issue.sh must ship inside plan-next-issue"


def test_find_candidate_scripts_ship_with_both_new_skills():
    assert (DATA_SKILLS / "plan-next-issue" / "find_candidate.sh").is_file()
    assert (DATA_SKILLS / "implement-next-task" / "find_candidate.sh").is_file()


def test_new_orchestrator_templates_ship_in_claude_agents_data():
    agents_dir = REPO_ROOT / "agentharness" / "data" / "claude-agents"
    assert (agents_dir / "plan-orchestrator.md").is_file()
    assert (agents_dir / "implement-orchestrator.md").is_file()
```

- [ ] **Step 2: Run the full packaged-skills test file to verify the new tests fail**

Run: `python -m pytest tests/test_packaged_skills.py -v`
Expected: `test_ships_the_full_skill_set` FAILS (the two new `.claude/skills/` directories aren't mirrored into `agentharness/data/skills/` yet — set equality mismatch); the four new tests above also FAIL (files don't exist under `agentharness/data/skills/` yet). `test_new_orchestrator_templates_ship_in_claude_agents_data` PASSES already (Tasks 4 and 7 wrote those files directly under `agentharness/data/claude-agents/`, which was never a mirrored/duplicated tree — confirm this by checking the assertion targets the same path Tasks 4/7 already wrote to, so this one is a no-op sanity check, not a real gap).

- [ ] **Step 3: Create the mirror**

```bash
mkdir -p /Users/pajgrtondrej/Work/GitHub/AgentHarness/agentharness/data/skills/plan-next-issue
mkdir -p /Users/pajgrtondrej/Work/GitHub/AgentHarness/agentharness/data/skills/implement-next-task
cp /Users/pajgrtondrej/Work/GitHub/AgentHarness/.claude/skills/plan-next-issue/*.sh /Users/pajgrtondrej/Work/GitHub/AgentHarness/.claude/skills/plan-next-issue/SKILL.md /Users/pajgrtondrej/Work/GitHub/AgentHarness/agentharness/data/skills/plan-next-issue/
cp /Users/pajgrtondrej/Work/GitHub/AgentHarness/.claude/skills/implement-next-task/*.sh /Users/pajgrtondrej/Work/GitHub/AgentHarness/.claude/skills/implement-next-task/SKILL.md /Users/pajgrtondrej/Work/GitHub/AgentHarness/agentharness/data/skills/implement-next-task/
chmod +x /Users/pajgrtondrej/Work/GitHub/AgentHarness/agentharness/data/skills/plan-next-issue/*.sh
chmod +x /Users/pajgrtondrej/Work/GitHub/AgentHarness/agentharness/data/skills/implement-next-task/*.sh
diff -r /Users/pajgrtondrej/Work/GitHub/AgentHarness/.claude/skills/plan-next-issue /Users/pajgrtondrej/Work/GitHub/AgentHarness/agentharness/data/skills/plan-next-issue
diff -r /Users/pajgrtondrej/Work/GitHub/AgentHarness/.claude/skills/implement-next-task /Users/pajgrtondrej/Work/GitHub/AgentHarness/agentharness/data/skills/implement-next-task
```

Both `diff -r` calls must print nothing (byte-identical) before moving on.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_packaged_skills.py -v`
Expected: PASS (all tests, including the pre-existing ones)

- [ ] **Step 5: Run the entire test suite to confirm no regressions anywhere**

Run: `python -m pytest tests/ -v`
Expected: PASS (every test, old and new)

- [ ] **Step 6: Stage the change**

```bash
git -C /Users/pajgrtondrej/Work/GitHub/AgentHarness add agentharness/data/skills/plan-next-issue agentharness/data/skills/implement-next-task tests/test_packaged_skills.py
git -C /Users/pajgrtondrej/Work/GitHub/AgentHarness status --short
```

---

### Task 10: Manual end-to-end dry run + commit/rollout decision

This task cannot be automated — it validates that a real Claude Code agent
following these two SKILL.md files, against a real (low-stakes) GitHub
issue, actually behaves as designed. Unlike Tasks 1–9, there is no pytest
step here; this is a checklist for whoever runs the plan (human or
subagent) to execute by hand.

**Files:** none new.

- [ ] **Step 1: Pick a real, low-stakes test issue** in a repo you control
  (not `Anela.Heblo` production work) — e.g. open a throwaway issue in
  `onpaj/harness` itself labelled `agent`, with a trivial one-file change
  as its ask, so the dev-task phase finishes fast and doesn't risk a long
  `dotnet build`/`test` run.

- [ ] **Step 2: Invoke `/plan-next-issue` once** (not via the hourly cron
  — directly, so you can watch it). Confirm: it claims the issue
  (`agent` → `agent-planning`), runs analyst→architect→designer→planner,
  opens a **draft** PR, and swaps the label to `agent-ready-for-dev`.

- [ ] **Step 3: Invoke `/implement-next-task` repeatedly** (once per dev
  task in the plan, plus once for code review, plus once for finishing —
  however many units the test issue's plan produces). After each
  invocation, confirm on GitHub: a new commit landed on the PR's branch,
  the PR is still draft (until the final invocation), and the issue's
  label is unchanged (still `agent-implementing`) between units.

- [ ] **Step 4: Confirm the finishing invocation** undrafts the PR, adds
  the code-review comment, and swaps the label to `agent-completed`.

- [ ] **Step 5: Test the concurrency gate directly** — start two
  `/implement-next-task` invocations back to back against different
  candidate issues with `IMPLEMENT_MAX_CONCURRENT=1`; confirm the second
  one reports "at capacity" and exits without claiming anything.

- [ ] **Step 6: Test the staleness reclaim** — manually stop an
  `/implement-next-task` invocation mid-unit (Ctrl-C or kill the process),
  wait past `STALE_MINUTES`, then run `find_candidate.sh` directly and
  confirm it returns that issue as a `stale-reclaim` candidate; run
  `/implement-next-task` again and confirm it resumes from the correct
  unit (reads `state.json` off the pushed branch, not anything local).

- [ ] **Step 7: Ask the user how they want the commits from Tasks 1–9
  handled.** Per Global Constraints, nothing in this plan has been
  committed yet — nine tasks' worth of changes are staged (`git status`
  should show them). Do not run `git commit` until the user explicitly
  says to; when they do, follow their usual commit-message conventions
  (see this repo's `git log` for style) rather than inventing a new one.

- [ ] **Step 8: Ask the user about rollout** — specifically, whether to
  retarget the existing hourly Orca cron on `hermes` from `/chopchop` to
  `/plan-next-issue` + `/implement-next-task` now, or leave `/chopchop`
  running in parallel for a trial period first. The Orca automation config
  itself lives outside this repo (see the design doc's investigation),
  so this plan cannot make that change directly — it needs to happen
  wherever the cron is actually configured, with the user's go-ahead.

---

## Self-Review Notes

**Spec coverage:** every section of the design doc maps to a task —
architecture (Tasks 5, 8), label state machine (Tasks 2, 3, 6, 8),
`plan-next-issue` (Tasks 1–5), `implement-next-task` (Tasks 1, 6–8),
concurrency & staleness (Task 1, folded into Tasks 3/6), durability
principle (Task 7's "stage the whole worktree, always push" change),
relationship to existing components (explicit non-changes called out in
Global Constraints), limits (staleness window is an env-var default, not
hardcoded, so it's tunable without a code change per the design's own
caveat that it's unmeasured).

**Placeholder scan:** no TBD/TODO markers. Two intentionally-deferred
decisions from the design doc are resolved explicitly in Global
Constraints (manual `/oneshot` stays, unchanged) rather than left open.

**Type/interface consistency:** `find_candidate.sh`'s JSON shape
(`candidate`/`skipped`, `source` field) is identical in structure between
Tasks 3 and 6, differing only in label names and `source` string values —
checked side by side while writing Task 6 against Task 3's finished
script. `check_concurrency.sh`'s exit-code contract (0/4/2) is used
identically in both `SKILL.md` files (Tasks 5, 8).
