"""Tests for implement-next-task/finish_pr.sh — the Finishing step.

The bug this script exists to prevent: the undraft is the only step in
Finishing with no REST equivalent (GraphQL `markPullRequestReadyForReview`
only), and it can fail while looking like it succeeded. The previous inline
version applied `agent-completed` to the issue *before* verifying, retried
with `2>/dev/null || true`, and never re-checked — so a failed undraft left a
draft PR behind an issue marked complete. Nothing downstream rescues that:
/automerge-pr and /hygiene-pr both skip drafts by design, and the issue has
already left the `agent-implementing` pool that would otherwise reclaim it.

So the invariant under test is narrow and absolute: `agent-completed` is
applied only to an issue whose PR is confirmed out of draft.
"""
import json
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / ".claude" / "skills" / "implement-next-task" / "finish_pr.sh"

ISSUE = 3939
BRANCH = "feature/3939-coverage-gap"

GH_STUB = """\
#!/usr/bin/env bash
echo "$*" >> "$GH_LOG"
case "$1 $2" in
  "pr ready")
    if [ -n "${UNDRAFT_TAKES_EFFECT:-}" ]; then echo ready > "$STATE_DIR/draft"; exit 0; fi
    echo "GraphQL error: [{\"type\":\"FORBIDDEN\"}]" >&2
    exit 1 ;;
  "pr view")
    if [ "$(cat "$STATE_DIR/draft")" = "ready" ]; then echo false; else echo true; fi
    exit 0 ;;
  "issue edit")
    if [ -n "${ISSUE_EDIT_FAILS:-}" ]; then exit 1; fi
    rm_l=""; add_l=""; prev=""
    for a in "$@"; do
      case "$prev" in
        --remove-label) rm_l="$a" ;;
        --add-label)    add_l="$a" ;;
      esac
      prev="$a"
    done
    jq -c --arg r "$rm_l" --arg a "$add_l" \
      '[.[] | select(. != $r)] + [$a] | unique' "$STATE_DIR/labels.json" > "$STATE_DIR/labels.next"
    mv "$STATE_DIR/labels.next" "$STATE_DIR/labels.json"
    exit 0 ;;
  "issue view") cat "$STATE_DIR/labels.json"; exit 0 ;;
  "label create") exit 0 ;;
  "pr edit")     exit 0 ;;
  "pr comment")  exit 0 ;;
esac
echo "unexpected gh call: $*" >&2
exit 1
"""


@pytest.fixture
def finish(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "gh"
    stub.write_text(GH_STUB)
    stub.chmod(0o755)

    state = tmp_path / "state"
    state.mkdir()
    (state / "draft").write_text("draft\n")
    (state / "labels.json").write_text(json.dumps(["agent-implementing", "coverage-gap"]))
    log = tmp_path / "gh.log"

    def run(undraft_takes_effect: bool, issue_edit_fails: bool = False):
        env = {
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "GH_LOG": str(log),
            "STATE_DIR": str(state),
            "GH_REPO": "onpaj/Anela.Heblo",
        }
        if undraft_takes_effect:
            env["UNDRAFT_TAKES_EFFECT"] = "1"
        if issue_edit_fails:
            env["ISSUE_EDIT_FAILS"] = "1"
        proc = subprocess.run(
            [str(SCRIPT), "--issue", str(ISSUE), "--branch", BRANCH],
            capture_output=True, text=True, env=env, cwd=REPO_ROOT,
        )
        assert proc.returncode == 0, proc.stderr
        return (
            json.loads(proc.stdout),
            json.loads((state / "labels.json").read_text()),
            log.read_text() if log.exists() else "",
        )

    return run


def test_reports_completed_once_the_pr_is_confirmed_out_of_draft(finish):
    result, labels, _ = finish(undraft_takes_effect=True)

    assert result["status"] == "completed"
    assert "agent-completed" in labels
    assert "agent-implementing" not in labels


def test_never_applies_agent_completed_to_a_pr_still_in_draft(finish):
    # The regression itself. `pr ready` fails, the PR stays a draft, and the
    # issue must NOT reach its terminal label on the strength of that.
    result, labels, _ = finish(undraft_takes_effect=False)

    assert result["status"] == "needs-human"
    assert "agent-completed" not in labels


def test_routes_a_stuck_draft_to_a_human_and_flags_the_pr(finish):
    result, labels, log = finish(undraft_takes_effect=False)

    assert "agent-needs-human" in labels
    assert "agent-implementing" not in labels
    assert "pr edit" in log and "needs-work" in log, "the PR must be flagged needs-work"
    assert "pr comment" in log, "a stuck draft must leave a durable explanation"
    assert "FORBIDDEN" in result["detail"], "the underlying error must survive into the detail"


def test_retries_the_undraft_once_before_giving_up(finish):
    _, _, log = finish(undraft_takes_effect=False)

    assert log.count("pr ready") == 2


def test_reports_unconfirmed_when_the_label_swap_does_not_stick(finish):
    # PR is genuinely out of draft, but the issue could not be moved. That is
    # neither "finished" nor "needs a human to undraft" — say so precisely.
    result, labels, _ = finish(undraft_takes_effect=True, issue_edit_fails=True)

    assert result["status"] == "unconfirmed"
    assert "agent-completed" not in labels
