import os
from pathlib import Path

ORCHESTRATOR = Path("agentharness/data/claude-agents/orchestrator.md")


def test_orchestrator_defines_code_review_phase():
    body = ORCHESTRATOR.read_text(encoding="utf-8")
    assert "## Code Review phase" in body
    assert "code-review.r{N}.md" in body
    assert "merge-base master HEAD" in body
    # Reads the new agent.
    assert ".agents/code-reviewer.md" in body


def test_orchestrator_no_longer_skips_review_on_at_claude():
    body = ORCHESTRATOR.read_text(encoding="utf-8")
    # The Skip-Review Check and its @claude trigger must be gone.
    assert "Skip-Review Check" not in body
    assert "@claude" not in body


ONESHOT = Path(".claude/skills/oneshot/SKILL.md")


def test_oneshot_skill_drops_at_claude_trigger():
    body = ONESHOT.read_text(encoding="utf-8")
    assert "@claude" not in body


def test_oneshot_skill_attaches_code_review_to_pr_body():
    body = ONESHOT.read_text(encoding="utf-8")
    assert "code-review.r" in body
    assert "Code review" in body or "Code Review" in body


# The script ships beside the oneshot skill so `agentharness init` copies it
# into the target repo along with the rest of the skill directory.
ENSURE_PR_LINKED = Path(".claude/skills/oneshot/ensure_pr_linked.sh")


def test_oneshot_skill_invokes_ensure_pr_linked():
    body = ONESHOT.read_text(encoding="utf-8")
    assert ".claude/skills/oneshot/ensure_pr_linked.sh" in body


def test_ensure_pr_linked_script_exists_and_is_executable():
    assert ENSURE_PR_LINKED.exists()
    assert os.access(ENSURE_PR_LINKED, os.X_OK)


def test_oneshot_skill_uses_issue_id_variable_in_pr_title():
    # The title must use the real $ISSUE_ID shell var, not the brittle
    # "{issue_id}" placeholder the LLM had to hand-substitute (which sometimes
    # collapsed the title to a bare "implementation").
    body = ONESHOT.read_text(encoding="utf-8")
    assert '--title "#${ISSUE_ID}: implementation"' in body
    assert '--title "#{issue_id}: implementation"' not in body


def test_ensure_pr_linked_enforces_title_format():
    script = ENSURE_PR_LINKED.read_text(encoding="utf-8")
    assert 'gh pr edit "$PR" --title' in script
    assert 'TITLE_RE="^#${ISSUE}: .+"' in script
