"""Tests for _lib/decline_issue.sh -- the durable "declined" marker that keeps
a declined issue from heading the queue on every later run, plus the
end-to-end "declined issue is not re-picked" property against the real
find_candidate.sh scripts."""
import json
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
DECLINE = REPO_ROOT / ".claude" / "skills" / "_lib" / "decline_issue.sh"
PLAN_FIND = REPO_ROOT / ".claude" / "skills" / "plan-next-task" / "find_candidate.sh"

# One stateful fake `gh`: labels live in $GH_STATE/labels (one per line), so
# a label added by decline_issue.sh is visible to the later `issue list`.
GH_STUB = """\
#!/usr/bin/env bash
echo "$*" >> "$GH_STATE/calls.log"
labels_json() {
  jq -R . "$GH_STATE/labels" | jq -sc '[.[] | {name: .}]'
}
case "$1 $2" in
  "issue view")
    if [ -n "$GH_FAIL_VIEW" ]; then echo "boom" >&2; exit 1; fi
    jq -R . "$GH_STATE/labels" | jq -sc '[.[]]' ;;
  "issue edit")
    [ -n "$GH_FAIL_EDIT" ] && { echo "HTTP 403" >&2; exit 1; }
    while [ $# -gt 0 ]; do
      [ "$1" = "--add-label" ] && echo "$2" >> "$GH_STATE/labels"
      shift
    done ;;
  "issue comment") [ -n "$GH_FAIL_COMMENT" ] && { echo "nope" >&2; exit 1; }; echo ok ;;
  "label create") exit 0 ;;
  "issue list")
    printf '[{"number":7,"title":"Hard one","createdAt":"2026-07-01T00:00:00Z","labels":%s},{"number":8,"title":"Easy","createdAt":"2026-08-01T00:00:00Z","labels":[{"name":"agent"}]}]' "$(labels_json)" ;;
  *) exit 1 ;;
esac
"""

GIT_STUB = """\
#!/usr/bin/env bash
if [ "$1" = "ls-remote" ]; then exit 0; fi
exec /usr/bin/git "$@"
"""


@pytest.fixture
def env(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("gh", GH_STUB), ("git", GIT_STUB)):
        (bin_dir / name).write_text(body)
        (bin_dir / name).chmod(0o755)
    state = tmp_path / "state"
    state.mkdir()
    (state / "labels").write_text("agent\n")
    base = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "GH_STATE": str(state),
        "GH_REPO": "onpaj/harness",
    }
    return base, state


def _decline(base, extra=None, reason="needs a product decision"):
    proc = subprocess.run(
        [str(DECLINE), "--issue", "7", "--reason", reason],
        capture_output=True, text=True, env={**base, **(extra or {})},
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_decline_adds_blocked_label_and_comments(env):
    base, state = env
    out = _decline(base)
    assert out["status"] == "declined"
    assert "agent-blocked" in (state / "labels").read_text().split()
    calls = (state / "calls.log").read_text()
    assert "issue comment 7" in calls


def test_decline_is_idempotent_and_does_not_comment_twice(env):
    base, state = env
    _decline(base)
    out = _decline(base)
    assert out["status"] == "already-blocked"
    assert (state / "calls.log").read_text().count("issue comment") == 1


def test_comment_failure_still_leaves_the_label_in_place(env):
    base, state = env
    out = _decline(base, {"GH_FAIL_COMMENT": "1"})
    assert out["status"] == "declined"
    assert "could not post the comment" in out["detail"]
    assert "agent-blocked" in (state / "labels").read_text().split()


def test_label_failure_is_reported_as_error(env):
    base, _ = env
    out = _decline(base, {"GH_FAIL_EDIT": "1"})
    assert out["status"] == "error"
    assert "agent-blocked" in out["detail"]


def test_missing_reason_is_a_usage_error(env):
    base, _ = env
    proc = subprocess.run([str(DECLINE), "--issue", "7"], capture_output=True, text=True, env=base)
    assert proc.returncode == 1


def test_declined_issue_is_not_repicked_by_plan_find_candidate(env):
    base, _ = env
    first = subprocess.run([str(PLAN_FIND)], capture_output=True, text=True, env=base, cwd=REPO_ROOT)
    assert json.loads(first.stdout)["candidate"]["number"] == 7

    _decline(base)

    second = subprocess.run([str(PLAN_FIND)], capture_output=True, text=True, env=base, cwd=REPO_ROOT)
    result = json.loads(second.stdout)
    assert result["candidate"]["number"] == 8
    assert any(s["number"] == 7 for s in result["skipped"])
