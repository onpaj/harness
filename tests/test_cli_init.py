"""Tests for agentharness init installing claude-agents skills."""

from pathlib import Path
from unittest.mock import patch
from click.testing import CliRunner
from agentharness.cli import main


def test_init_installs_orchestrator_agent(tmp_path):
    runner = CliRunner()
    with patch("agentharness.cli._write_env"):
        result = runner.invoke(main, ["init", "--dir", str(tmp_path)], catch_exceptions=False)
    assert result.exit_code == 0
    agent_file = tmp_path / ".claude" / "agents" / "orchestrator.md"
    assert agent_file.exists(), f"orchestrator.md not installed. Output: {result.output}"


def test_init_skips_existing_without_force(tmp_path):
    runner = CliRunner()
    with patch("agentharness.cli._write_env"):
        # First run
        runner.invoke(main, ["init", "--dir", str(tmp_path)])
        skill_file = tmp_path / ".claude" / "agents" / "orchestrator.md"
        original_mtime = skill_file.stat().st_mtime
        # Second run without --force
        runner.invoke(main, ["init", "--dir", str(tmp_path)])
    assert skill_file.stat().st_mtime == original_mtime  # not overwritten


def test_init_overwrites_with_force(tmp_path):
    runner = CliRunner()
    with patch("agentharness.cli._write_env"):
        runner.invoke(main, ["init", "--dir", str(tmp_path)])
        skill_file = tmp_path / ".claude" / "agents" / "orchestrator.md"
        # Modify it
        skill_file.write_text("modified")
        # Re-run with --force
        runner.invoke(main, ["init", "--dir", str(tmp_path), "--force"])
    # Should be restored to original
    assert skill_file.read_text() != "modified"


def test_init_prints_updated_message(tmp_path):
    runner = CliRunner()
    with patch("agentharness.cli._write_env"):
        result = runner.invoke(main, ["init", "--dir", str(tmp_path)], catch_exceptions=False)
    assert "/oneshot" in result.output


def test_init_installs_skills_as_real_files_with_pr_script(tmp_path):
    runner = CliRunner()
    with patch("agentharness.cli._write_env"):
        runner.invoke(main, ["init", "--dir", str(tmp_path)], catch_exceptions=False)
    skills = tmp_path / ".claude" / "skills"
    brainstorm = skills / "brainstorm" / "SKILL.md"
    assert brainstorm.is_file() and not brainstorm.is_symlink()
    # oneshot ships with its pr-linking script so the step works in consumer repos.
    assert (skills / "oneshot" / "ensure_pr_linked.sh").is_file()
