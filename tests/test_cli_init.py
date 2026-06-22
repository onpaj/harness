"""Tests for agentharness init installing claude-agents skills."""

from pathlib import Path
from unittest.mock import patch
from click.testing import CliRunner
from agentharness.cli import main, GITIGNORE_MARKER


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


# --- symlink mode ---

def _run_symlink(tmp_path, *extra):
    runner = CliRunner()
    with patch("agentharness.cli._write_env"):
        return runner.invoke(
            main, ["init", "--dir", str(tmp_path), "--symlink", *extra], catch_exceptions=False
        )


def test_symlink_creates_resolving_symlinks(tmp_path):
    result = _run_symlink(tmp_path)
    assert result.exit_code == 0

    agent = tmp_path / ".claude" / "agents" / "orchestrator.md"
    skill = tmp_path / ".claude" / "skills" / "oneshot"
    assert agent.is_symlink(), result.output
    assert skill.is_symlink(), result.output
    # Resolve into the installed package data dir, not into the consumer repo.
    assert agent.resolve().is_file()
    assert (skill.resolve() / "SKILL.md").is_file()


def test_symlink_writes_gitignore_block(tmp_path):
    _run_symlink(tmp_path)
    gitignore = (tmp_path / ".gitignore").read_text()
    assert GITIGNORE_MARKER in gitignore
    assert "/.claude/skills/oneshot" in gitignore
    assert "/.claude/agents/orchestrator.md" in gitignore


def test_symlink_is_idempotent(tmp_path):
    _run_symlink(tmp_path)
    skill = tmp_path / ".claude" / "skills" / "oneshot"
    target_before = skill.resolve()
    _run_symlink(tmp_path)
    assert skill.is_symlink()
    assert skill.resolve() == target_before
    # gitignore block is rewritten, not duplicated
    gitignore = (tmp_path / ".gitignore").read_text()
    assert gitignore.count(GITIGNORE_MARKER) == 1


def test_symlink_force_converts_existing_copy(tmp_path):
    # First copy (default mode), then convert with --symlink --force
    runner = CliRunner()
    with patch("agentharness.cli._write_env"):
        runner.invoke(main, ["init", "--dir", str(tmp_path)], catch_exceptions=False)
    agent = tmp_path / ".claude" / "agents" / "orchestrator.md"
    assert agent.is_file() and not agent.is_symlink()

    _run_symlink(tmp_path, "--force")
    assert agent.is_symlink()


def test_symlink_without_force_keeps_existing_copy(tmp_path):
    runner = CliRunner()
    with patch("agentharness.cli._write_env"):
        runner.invoke(main, ["init", "--dir", str(tmp_path)], catch_exceptions=False)
    agent = tmp_path / ".claude" / "agents" / "orchestrator.md"
    original = agent.read_text()

    result = _run_symlink(tmp_path)  # no --force
    assert not agent.is_symlink()
    assert agent.read_text() == original
    assert "committed copy exists" in result.output


def test_symlink_falls_back_to_copy_on_oserror(tmp_path):
    with patch("agentharness.cli.os.symlink", side_effect=OSError("nope")):
        result = _run_symlink(tmp_path)
    assert result.exit_code == 0
    agent = tmp_path / ".claude" / "agents" / "orchestrator.md"
    assert agent.is_file() and not agent.is_symlink()
    # copy fallbacks are not gitignored
    gitignore = tmp_path / ".gitignore"
    if gitignore.exists():
        assert "/.claude/agents/orchestrator.md" not in gitignore.read_text()
