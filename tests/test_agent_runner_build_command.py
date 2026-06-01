"""Tests for _build_command permission-mode and allowed-tools flags."""

from __future__ import annotations

from agentharness.agent_runner import _build_command
from agentharness.models import AgentDefinition


def _make_agent_def(**overrides) -> AgentDefinition:
    defaults = dict(
        id="test-agent",
        model="claude-sonnet-4-6",
        phase="testing",
        system_prompt="You are a test agent.",
        visibility_timeout=600,
    )
    return AgentDefinition(**{**defaults, **overrides})


def test_allowed_tools_adds_bypass_and_allowed_tools_flag():
    agent_def = _make_agent_def(allowed_tools=["bash", "read"])
    cmd = _build_command(agent_def, "do work")
    assert "--permission-mode" in cmd
    assert "bypassPermissions" in cmd
    assert "--allowedTools" in cmd
    idx = cmd.index("--allowedTools")
    assert "bash" in cmd[idx + 1]


def test_output_file_glob_adds_bypass_with_restricted_tools():
    """output_file_glob agents get bypassPermissions + Write/Edit only (no Bash)."""
    agent_def = _make_agent_def(allowed_tools=[], output_file_glob="spec.md")
    cmd = _build_command(agent_def, "analyse")
    assert "--permission-mode" in cmd
    assert "bypassPermissions" in cmd
    assert "--allowedTools" in cmd
    idx = cmd.index("--allowedTools")
    allowed = cmd[idx + 1]
    assert "write" in allowed
    assert "edit" in allowed
    assert "bash" not in allowed


def test_no_tools_no_glob_no_bypass():
    agent_def = _make_agent_def(allowed_tools=[], output_file_glob=None)
    cmd = _build_command(agent_def, "review")
    assert "--permission-mode" not in cmd
    assert "--allowedTools" not in cmd


def test_both_tools_and_glob_adds_both_flags():
    agent_def = _make_agent_def(allowed_tools=["write"], output_file_glob="design.md")
    cmd = _build_command(agent_def, "design")
    assert "--permission-mode" in cmd
    assert "bypassPermissions" in cmd
    assert "--allowedTools" in cmd
