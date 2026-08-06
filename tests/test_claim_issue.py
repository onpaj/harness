"""Tests for the /oneshot claim_issue.sh atomic claim script."""
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / ".claude" / "skills" / "oneshot" / "claim_issue.sh"

GH_STUB = """\
#!/usr/bin/env bash
# Fake `gh` for tests. Behavior is driven by env vars:
#   GH_STUB_TITLE     — issue title served by `gh issue view`
#   GH_STUB_REF_MODE  — `gh api .../git/refs` outcome: ok | exists | fail
# Every invocation's argv is appended to $GH_STUB_LOG.
echo "$*" >> "$GH_STUB_LOG"
if [ "$1" = "issue" ] && [ "$2" = "view" ]; then
  echo "$GH_STUB_TITLE"
  exit 0
fi
if [ "$1" = "repo" ] && [ "$2" = "view" ]; then
  echo "master"
  exit 0
fi
if [ "$1" = "api" ]; then
  case "$GH_STUB_REF_MODE" in
    ok) echo '{}'; exit 0 ;;
    exists) echo "HTTP 422: Reference already exists" >&2; exit 1 ;;
    *) echo "HTTP 500: boom" >&2; exit 1 ;;
  esac
fi
if [ "$1" = "issue" ] && [ "$2" = "edit" ]; then
  exit 0
fi
exit 1
"""

GIT_STUB = """\
#!/usr/bin/env bash
# Fake `git` for tests. `ls-remote --heads` serves $GH_STUB_EXISTING_BRANCH
# (one ref line) when set; `ls-remote origin refs/heads/...` serves the base
# SHA. Argv is appended to $GH_STUB_LOG.
echo "git $*" >> "$GH_STUB_LOG"
if [ "$1" = "ls-remote" ] && [ "$2" = "--heads" ]; then
  if [ -n "$GH_STUB_EXISTING_BRANCH" ]; then
    printf 'abc123\\trefs/heads/%s\\n' "$GH_STUB_EXISTING_BRANCH"
  fi
  exit 0
fi
if [ "$1" = "ls-remote" ]; then
  printf 'basesha\\t%s\\n' "$3"
  exit 0
fi
exit 1
"""


@pytest.fixture
def claim_runner(tmp_path):
    """Put fake `gh` and `git` on PATH; returns a function running
    claim_issue.sh against a canned title / remote-branch / API outcome."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("gh", GH_STUB), ("git", GIT_STUB)):
        stub = bin_dir / name
        stub.write_text(body)
        stub.chmod(0o755)
    log = tmp_path / "stub.log"
    log.touch()

    def run(issue, title="Add Widget Support", ref_mode="ok", existing_branch=""):
        env = {
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "GH_STUB_TITLE": title,
            "GH_STUB_REF_MODE": ref_mode,
            "GH_STUB_EXISTING_BRANCH": existing_branch,
            "GH_STUB_LOG": str(log),
        }
        result = subprocess.run(
            ["bash", str(SCRIPT), *issue],
            capture_output=True, text=True, env=env,
        )
        return result, log.read_text()

    return run


def test_claims_unclaimed_issue(claim_runner):
    result, log = claim_runner(["42"])
    assert result.returncode == 0
    assert result.stdout.strip() == "feature/42-Add-Widget-Support"
    # The claim ref is created before the advisory label swap.
    api_idx = log.index("api repos/{owner}/{repo}/git/refs")
    label_idx = log.index("issue edit 42 --add-label agent-wip --remove-label agent")
    assert api_idx < label_idx


def test_slug_matches_oneshot_convention(claim_runner):
    result, _ = claim_runner(["9863"], title="What's This About?")
    assert result.returncode == 0
    assert result.stdout.strip() == "feature/9863-Whats-This-About"


def test_existing_remote_branch_means_already_claimed(claim_runner):
    result, log = claim_runner(["42"], existing_branch="feature/42-Old-Slug")
    assert result.returncode == 3
    assert "already claimed" in result.stderr
    # No ref creation and no label swap were attempted.
    assert "api repos" not in log
    assert "issue edit" not in log


def test_lost_race_exits_3(claim_runner):
    result, log = claim_runner(["42"], ref_mode="exists")
    assert result.returncode == 3
    assert "lost the race" in result.stderr
    assert "issue edit" not in log


def test_api_failure_exits_1(claim_runner):
    result, _ = claim_runner(["42"], ref_mode="fail")
    assert result.returncode == 1
    assert "failed to create claim ref" in result.stderr


def test_usage_errors_exit_2(claim_runner):
    for argv in ([], ["not-a-number"]):
        result, _ = claim_runner(argv)
        assert result.returncode == 2
