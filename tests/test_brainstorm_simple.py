"""Tests for simplified brainstorm.py."""

from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
from agentharness.brainstorm import start_brainstorm, run_brainstorm_session


def test_start_brainstorm_raises_when_agent_missing(tmp_path):
    with patch("agentharness.brainstorm._BRAINSTORM_AGENT", tmp_path / ".agents" / "brainstorm.md"):
        with pytest.raises(FileNotFoundError, match="Brainstorm agent not found"):
            start_brainstorm()


def test_run_brainstorm_session_calls_execvp(tmp_path):
    agent_path = tmp_path / ".agents" / "brainstorm.md"
    agent_path.parent.mkdir(parents=True)
    agent_path.write_text(
        "---\n"
        "id: brainstorm\n"
        "model: claude-sonnet-4-6\n"
        "phase: brainstorming\n"
        "max_turns: 50\n"
        "allowed_tools: []\n"
        "---\n"
        "You are a brainstorm agent."
    )
    with patch("os.execvp") as mock_execvp:
        run_brainstorm_session(tmp_path, agent_path)
    mock_execvp.assert_called_once()
    call_args = mock_execvp.call_args
    assert call_args[0][0] == "claude"
    cmd = call_args[0][1]
    assert "--system-prompt" in cmd
    assert "--model" in cmd
    assert "claude-sonnet-4-6" in cmd


def test_brainstorm_module_has_no_queue_imports():
    import importlib
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "brainstorm", "agentharness/brainstorm.py"
    )
    # Read source to check for deleted imports
    source = open("agentharness/brainstorm.py").read()
    assert "github_client" not in source
    assert "azure" not in source.lower()
    assert "storage" not in source
    assert "enqueue" not in source
    assert "upload_brief" not in source
