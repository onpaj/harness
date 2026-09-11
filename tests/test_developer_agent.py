"""Guards for the developer agent definition shipped by `agentharness init`."""
from pathlib import Path

from agentharness.prompt_builder import load_agent_definition

AGENT_PATH = Path("agentharness/data/agents/developer.md")


def test_developer_agent_parses_with_runtime_fields():
    agent = load_agent_definition(AGENT_PATH)

    assert agent.id == "developer"
    assert agent.phase == "developing"
    # It writes real code, so it needs real tools.
    assert agent.allowed_tools is not None
    assert {"bash", "read", "write"} <= set(agent.allowed_tools)
    # The orchestrator parses the `## Status:` line itself.
    assert agent.output_parsing == "none"
    assert agent.system_prompt.strip() != ""


def _hard_constraints(body: str) -> str:
    section = body.split("**Hard constraints", 1)[1].split("\n## ", 1)[0]
    return " ".join(section.split()).lower()


def test_developer_agent_requires_foreground_builds_with_a_timeout():
    """A backgrounded `dotnet build` leaves the agent waiting for a completion
    notification that never arrives in a non-interactive run, stalling the
    whole unit until a human resumes it."""
    constraints = _hard_constraints(AGENT_PATH.read_text(encoding="utf-8"))

    assert "foreground" in constraints
    assert "background" in constraints
    assert "timeout" in constraints
    assert "build" in constraints and "test" in constraints
