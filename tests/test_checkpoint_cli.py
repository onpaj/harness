"""Tests for agentharness checkpoint CLI subcommands."""

import json
from pathlib import Path
from click.testing import CliRunner
from agentharness.cli import main


def test_checkpoint_init_creates_state_file(tmp_path):
    runner = CliRunner()
    result = runner.invoke(
        main, ["checkpoint", "init", "123"],
        catch_exceptions=False,
        env={"AGENTHARNESS_BASE_DIR": str(tmp_path)},
    )
    assert result.exit_code == 0
    assert (tmp_path / "artifacts" / "feat-123" / "state.json").exists()


def test_checkpoint_init_idempotent(tmp_path):
    runner = CliRunner()
    runner.invoke(main, ["checkpoint", "init", "123"], env={"AGENTHARNESS_BASE_DIR": str(tmp_path)})
    result = runner.invoke(main, ["checkpoint", "init", "123"], env={"AGENTHARNESS_BASE_DIR": str(tmp_path)})
    assert result.exit_code == 0


def test_checkpoint_phase_updates_status(tmp_path):
    runner = CliRunner()
    runner.invoke(main, ["checkpoint", "init", "123"], env={"AGENTHARNESS_BASE_DIR": str(tmp_path)})
    result = runner.invoke(
        main, ["checkpoint", "phase", "feat-123", "analyzing", "completed"],
        env={"AGENTHARNESS_BASE_DIR": str(tmp_path)},
    )
    assert result.exit_code == 0
    from agentharness.checkpoint import load_checkpoint
    cp = load_checkpoint("feat-123", base_dir=tmp_path)
    assert cp.phases["analyzing"].status == "completed"


def test_checkpoint_tasks_populates_list(tmp_path):
    runner = CliRunner()
    runner.invoke(main, ["checkpoint", "init", "123"], env={"AGENTHARNESS_BASE_DIR": str(tmp_path)})
    result = runner.invoke(
        main, ["checkpoint", "tasks", "feat-123", "setup-models,api-endpoints"],
        env={"AGENTHARNESS_BASE_DIR": str(tmp_path)},
    )
    assert result.exit_code == 0
    from agentharness.checkpoint import load_checkpoint
    cp = load_checkpoint("feat-123", base_dir=tmp_path)
    assert len(cp.tasks) == 2


def test_checkpoint_task_updates_status(tmp_path):
    runner = CliRunner()
    runner.invoke(main, ["checkpoint", "init", "123"], env={"AGENTHARNESS_BASE_DIR": str(tmp_path)})
    runner.invoke(main, ["checkpoint", "tasks", "feat-123", "setup-models"],
                  env={"AGENTHARNESS_BASE_DIR": str(tmp_path)})
    result = runner.invoke(
        main, ["checkpoint", "task", "feat-123", "setup-models", "completed"],
        env={"AGENTHARNESS_BASE_DIR": str(tmp_path)},
    )
    assert result.exit_code == 0


def test_checkpoint_task_with_revision(tmp_path):
    runner = CliRunner()
    runner.invoke(main, ["checkpoint", "init", "123"], env={"AGENTHARNESS_BASE_DIR": str(tmp_path)})
    runner.invoke(main, ["checkpoint", "tasks", "feat-123", "setup-models"],
                  env={"AGENTHARNESS_BASE_DIR": str(tmp_path)})
    result = runner.invoke(
        main, ["checkpoint", "task", "feat-123", "setup-models", "in_progress", "--revision", "2"],
        env={"AGENTHARNESS_BASE_DIR": str(tmp_path)},
    )
    assert result.exit_code == 0
    from agentharness.checkpoint import load_checkpoint
    cp = load_checkpoint("feat-123", base_dir=tmp_path)
    assert cp.tasks[0].revision == 2


def test_checkpoint_status_returns_json(tmp_path):
    runner = CliRunner()
    runner.invoke(main, ["checkpoint", "init", "123"], env={"AGENTHARNESS_BASE_DIR": str(tmp_path)})
    result = runner.invoke(
        main, ["checkpoint", "status", "feat-123"],
        env={"AGENTHARNESS_BASE_DIR": str(tmp_path)},
    )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["type"] == "phase"
    assert data["name"] == "analyzing"
