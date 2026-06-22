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
