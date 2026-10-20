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


def test_init_overwrites_an_untracked_existing_file(tmp_path):
    # No manifest yet (a repo that predates it): there is no way to tell a
    # local edit from an old release, so the packaged version wins.
    runner = CliRunner()
    skill_file = tmp_path / ".claude" / "agents" / "orchestrator.md"
    skill_file.parent.mkdir(parents=True)
    skill_file.write_text("modified")
    with patch("agentharness.cli._write_env"):
        runner.invoke(main, ["init", "--dir", str(tmp_path)])
    assert skill_file.read_text() != "modified"


def test_init_keeps_a_file_edited_since_the_last_init(tmp_path):
    runner = CliRunner()
    skill_file = tmp_path / ".claude" / "agents" / "orchestrator.md"
    with patch("agentharness.cli._write_env"):
        runner.invoke(main, ["init", "--dir", str(tmp_path)])
        skill_file.write_text("local fix")
        result = runner.invoke(main, ["init", "--dir", str(tmp_path)], catch_exceptions=False)
    assert skill_file.read_text() == "local fix"
    assert "kept" in result.output and "orchestrator.md" in result.output


def test_init_keeps_a_locally_edited_skill_script(tmp_path):
    # The case that motivated the manifest: a cloud session's setup re-runs
    # init and used to revert a committed local fix to a skill script.
    runner = CliRunner()
    script = tmp_path / ".claude" / "skills" / "plan-next-task" / "find_candidate.sh"
    with patch("agentharness.cli._write_env"):
        runner.invoke(main, ["init", "--dir", str(tmp_path)])
        script.write_text("#!/usr/bin/env bash\n# local epic skip\n")
        runner.invoke(main, ["init", "--dir", str(tmp_path)])
    assert "local epic skip" in script.read_text()


def test_init_updates_an_unedited_file_when_the_package_changes(tmp_path):
    from agentharness.scaffold import MANIFEST_NAME
    runner = CliRunner()
    skill_file = tmp_path / ".claude" / "agents" / "orchestrator.md"
    with patch("agentharness.cli._write_env"):
        runner.invoke(main, ["init", "--dir", str(tmp_path)])
        packaged = skill_file.read_text()
        # Simulate an older release: file and its manifest record agree.
        import hashlib, json
        skill_file.write_text("old release")
        manifest_path = tmp_path / MANIFEST_NAME
        data = json.loads(manifest_path.read_text())
        data["files"][".claude/agents/orchestrator.md"] = hashlib.sha256(b"old release").hexdigest()
        manifest_path.write_text(json.dumps(data))
        runner.invoke(main, ["init", "--dir", str(tmp_path)])
    assert skill_file.read_text() == packaged


def test_init_overwrite_local_replaces_an_edited_file(tmp_path):
    runner = CliRunner()
    skill_file = tmp_path / ".claude" / "agents" / "orchestrator.md"
    with patch("agentharness.cli._write_env"):
        runner.invoke(main, ["init", "--dir", str(tmp_path)])
        skill_file.write_text("local fix")
        runner.invoke(main, ["init", "--dir", str(tmp_path), "--overwrite-local"])
    assert skill_file.read_text() != "local fix"


def test_init_writes_a_manifest_covering_installed_files(tmp_path):
    from agentharness.scaffold import MANIFEST_NAME, load_manifest
    runner = CliRunner()
    with patch("agentharness.cli._write_env"):
        runner.invoke(main, ["init", "--dir", str(tmp_path)])
    manifest = load_manifest(tmp_path)
    assert (tmp_path / MANIFEST_NAME).is_file()
    assert ".claude/agents/orchestrator.md" in manifest
    assert ".claude/skills/plan-next-task/find_candidate.sh" in manifest


def test_unreadable_manifest_is_treated_as_empty(tmp_path):
    from agentharness.scaffold import MANIFEST_NAME, load_manifest
    (tmp_path / MANIFEST_NAME).write_text("{not json")
    assert load_manifest(tmp_path) == {}


def test_init_accepts_legacy_force_flag_as_noop(tmp_path):
    runner = CliRunner()
    with patch("agentharness.cli._write_env"):
        result = runner.invoke(
            main, ["init", "--dir", str(tmp_path), "--force"], catch_exceptions=False
        )
    assert result.exit_code == 0
    agent_file = tmp_path / ".claude" / "agents" / "orchestrator.md"
    assert agent_file.exists()


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
