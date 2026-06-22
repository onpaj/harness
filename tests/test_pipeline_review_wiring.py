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
