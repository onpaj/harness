"""Tests for trimmed cli.py — status/list read checkpoints, observer removed."""

import pytest
from pathlib import Path
from click.testing import CliRunner
from agentharness.cli import main


def test_status_reads_checkpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTHARNESS_BASE_DIR", str(tmp_path))
    from agentharness.checkpoint import init_checkpoint, update_phase
    init_checkpoint(123, base_dir=tmp_path)
    update_phase("feat-123", "analyzing", "completed", base_dir=tmp_path)
    runner = CliRunner()
    result = runner.invoke(main, ["status", "feat-123"])
    assert result.exit_code == 0
    assert "feat-123" in result.output
    assert "analyzing" in result.output


def test_list_reads_checkpoints(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTHARNESS_BASE_DIR", str(tmp_path))
    from agentharness.checkpoint import init_checkpoint
    init_checkpoint(42, base_dir=tmp_path)
    runner = CliRunner()
    result = runner.invoke(main, ["list"])
    assert result.exit_code == 0
    assert "feat-42" in result.output


def test_observe_command_removed():
    runner = CliRunner()
    result = runner.invoke(main, ["observe"])
    assert result.exit_code != 0 or "No such command" in result.output
