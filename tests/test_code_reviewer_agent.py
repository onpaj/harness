from pathlib import Path

from agentharness.prompt_builder import load_agent_definition

AGENT_PATH = Path("agentharness/data/agents/code-reviewer.md")


def test_code_reviewer_agent_parses_with_runtime_fields():
    agent = load_agent_definition(AGENT_PATH)

    assert agent.id == "code-reviewer"
    assert agent.phase == "code-review"
    # Must be able to read real code, not just a text summary.
    assert agent.allowed_tools is not None
    assert "read" in agent.allowed_tools
    assert "bash" in agent.allowed_tools
    # Orchestrator parses the result itself; no built-in parser.
    assert agent.output_parsing == "none"
    assert agent.system_prompt.strip() != ""


def test_code_reviewer_prompt_defines_parseable_result_contract():
    body = AGENT_PATH.read_text(encoding="utf-8")

    # The exact tokens the orchestrator greps for must be present.
    assert "## Review Result: CLEAN | CHANGES_REQUESTED" in body
    assert "### Blocking (correctness)" in body
    assert "### Advisory (cleanup)" in body
