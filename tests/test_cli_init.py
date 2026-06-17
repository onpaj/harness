"""Tests for agentharness init installing claude-agents skills."""

from unittest.mock import patch
from click.testing import CliRunner
from agentharness.cli import main


def test_init_installs_oneshot_skill(tmp_path):
    runner = CliRunner()
    with patch("agentharness.cli._write_env"):
        result = runner.invoke(main, ["init", "--dir", str(tmp_path)], catch_exceptions=False)
    assert result.exit_code == 0
    skill_file = tmp_path / ".claude" / "agents" / "oneshot.md"
    assert skill_file.exists(), f"oneshot.md not installed. Output: {result.output}"


def test_init_skips_existing_without_force(tmp_path):
    runner = CliRunner()
    with patch("agentharness.cli._write_env"):
        # First run
        runner.invoke(main, ["init", "--dir", str(tmp_path)])
        skill_file = tmp_path / ".claude" / "agents" / "oneshot.md"
        original_mtime = skill_file.stat().st_mtime
        # Second run without --force
        runner.invoke(main, ["init", "--dir", str(tmp_path)])
    assert skill_file.stat().st_mtime == original_mtime  # not overwritten


def test_init_overwrites_with_force(tmp_path):
    runner = CliRunner()
    with patch("agentharness.cli._write_env"):
        runner.invoke(main, ["init", "--dir", str(tmp_path)])
        skill_file = tmp_path / ".claude" / "agents" / "oneshot.md"
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
