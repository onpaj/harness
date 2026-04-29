"""Unit tests for config loading and validation."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from agentharness.config import ConfigValidationError, GitHubConfig, _parse_github_remote, load_config


def write_config(tmp_path: Path, data: dict) -> Path:
    config_dir = tmp_path / ".pipeline"
    config_dir.mkdir()
    config_file = config_dir / "config.json"
    config_file.write_text(json.dumps(data))
    return config_file


def base_config(**queue_overrides) -> dict:
    queues = {"designer-queue": {"agent": ".agents/designer.md", **queue_overrides}}
    return {"queues": queues}


class TestContextFilesValidation:
    def test_list_of_strings_parses_successfully(self, tmp_path):
        cfg_path = write_config(
            tmp_path,
            base_config(context_files=["/docs/tokens.md", "standards.md"]),
        )
        config = load_config(cfg_path)
        cf = config.queues["designer-queue"].context_files
        assert cf == ["/docs/tokens.md", "standards.md"]

    def test_without_context_files_defaults_to_none(self, tmp_path):
        cfg_path = write_config(tmp_path, base_config())
        config = load_config(cfg_path)
        assert config.queues["designer-queue"].context_files is None

    def test_empty_list_normalizes_to_none(self, tmp_path):
        cfg_path = write_config(tmp_path, base_config(context_files=[]))
        config = load_config(cfg_path)
        assert config.queues["designer-queue"].context_files is None

    def test_string_value_raises_config_validation_error(self, tmp_path):
        cfg_path = write_config(tmp_path, base_config(context_files="single_string"))
        with pytest.raises(ConfigValidationError, match="context_files must be a list of strings"):
            load_config(cfg_path)

    def test_integer_value_raises_config_validation_error(self, tmp_path):
        cfg_path = write_config(tmp_path, base_config(context_files=42))
        with pytest.raises(ConfigValidationError, match="context_files must be a list of strings"):
            load_config(cfg_path)

    def test_list_with_non_string_element_raises_config_validation_error(self, tmp_path):
        cfg_path = write_config(tmp_path, base_config(context_files=["/valid", 123]))
        with pytest.raises(ConfigValidationError, match="context_files must be a list of strings"):
            load_config(cfg_path)

    def test_error_message_includes_queue_name(self, tmp_path):
        cfg_path = write_config(tmp_path, base_config(context_files="bad"))
        with pytest.raises(ConfigValidationError, match="designer-queue"):
            load_config(cfg_path)

    def test_error_message_includes_actual_type(self, tmp_path):
        cfg_path = write_config(tmp_path, base_config(context_files=42))
        with pytest.raises(ConfigValidationError, match="int"):
            load_config(cfg_path)


class TestConfigDir:
    def test_config_dir_is_set_to_parent_of_config_file(self, tmp_path):
        cfg_path = write_config(tmp_path, base_config())
        config = load_config(cfg_path)
        assert config.config_dir == cfg_path.resolve().parent

    def test_config_dir_differs_from_cwd(self, tmp_path):
        cfg_path = write_config(tmp_path, base_config())
        config = load_config(cfg_path)
        assert config.config_dir == (tmp_path / ".pipeline").resolve()


class TestWorktreeConfig:
    def test_use_worktrees_defaults_to_false(self, tmp_path):
        cfg_path = write_config(tmp_path, base_config())
        config = load_config(cfg_path)
        assert config.use_worktrees is False

    def test_worktree_base_dir_defaults_to_dotworktrees(self, tmp_path):
        cfg_path = write_config(tmp_path, base_config())
        config = load_config(cfg_path)
        assert config.worktree_base_dir == ".worktrees"

    def test_worktree_base_branch_defaults_to_none(self, tmp_path):
        cfg_path = write_config(tmp_path, base_config())
        config = load_config(cfg_path)
        assert config.worktree_base_branch is None

    def test_use_worktrees_true_parses(self, tmp_path):
        cfg_path = write_config(tmp_path, {**base_config(), "use_worktrees": True})
        config = load_config(cfg_path)
        assert config.use_worktrees is True

    def test_use_worktrees_string_true_raises(self, tmp_path):
        cfg_path = write_config(tmp_path, {**base_config(), "use_worktrees": "true"})
        with pytest.raises(ConfigValidationError, match="use_worktrees"):
            load_config(cfg_path)

    def test_use_worktrees_string_false_raises(self, tmp_path):
        cfg_path = write_config(tmp_path, {**base_config(), "use_worktrees": "false"})
        with pytest.raises(ConfigValidationError, match="use_worktrees"):
            load_config(cfg_path)

    def test_use_worktrees_integer_raises(self, tmp_path):
        cfg_path = write_config(tmp_path, {**base_config(), "use_worktrees": 1})
        with pytest.raises(ConfigValidationError, match="use_worktrees"):
            load_config(cfg_path)

    def test_use_worktrees_error_references_config_path(self, tmp_path):
        cfg_path = write_config(tmp_path, {**base_config(), "use_worktrees": "yes"})
        with pytest.raises(ConfigValidationError, match=str(cfg_path)):
            load_config(cfg_path)

    def test_absolute_worktree_base_dir_raises(self, tmp_path):
        cfg_path = write_config(tmp_path, {**base_config(), "worktree_base_dir": "/absolute/path"})
        with pytest.raises(ConfigValidationError, match="worktree_base_dir"):
            load_config(cfg_path)

    def test_dotdot_in_worktree_base_dir_raises(self, tmp_path):
        cfg_path = write_config(tmp_path, {**base_config(), "worktree_base_dir": "../outside"})
        with pytest.raises(ConfigValidationError, match="worktree_base_dir"):
            load_config(cfg_path)

    def test_nested_dotdot_in_worktree_base_dir_raises(self, tmp_path):
        cfg_path = write_config(tmp_path, {**base_config(), "worktree_base_dir": ".worktrees/../etc"})
        with pytest.raises(ConfigValidationError, match="worktree_base_dir"):
            load_config(cfg_path)

    def test_relative_worktree_base_dir_parses(self, tmp_path):
        cfg_path = write_config(tmp_path, {**base_config(), "worktree_base_dir": "infra/worktrees"})
        config = load_config(cfg_path)
        assert config.worktree_base_dir == "infra/worktrees"

    def test_worktree_base_branch_string_parses(self, tmp_path):
        cfg_path = write_config(tmp_path, {**base_config(), "worktree_base_branch": "main"})
        config = load_config(cfg_path)
        assert config.worktree_base_branch == "main"

    def test_worktree_base_branch_null_parses(self, tmp_path):
        cfg_path = write_config(tmp_path, {**base_config(), "worktree_base_branch": None})
        config = load_config(cfg_path)
        assert config.worktree_base_branch is None


class TestParseGithubRemote:
    def _mock_remote(self, url: str):
        return patch("subprocess.check_output", return_value=url)

    def test_https_url(self):
        with self._mock_remote("https://github.com/acme/my-project.git"):
            assert _parse_github_remote() == ("acme", "my-project")

    def test_https_url_without_dotgit(self):
        with self._mock_remote("https://github.com/acme/my-project"):
            assert _parse_github_remote() == ("acme", "my-project")

    def test_ssh_url(self):
        with self._mock_remote("git@github.com:acme/my-project.git"):
            assert _parse_github_remote() == ("acme", "my-project")

    def test_non_github_remote_raises(self):
        with self._mock_remote("https://gitlab.com/acme/my-project.git"):
            with pytest.raises(RuntimeError, match="does not look like a GitHub repo"):
                _parse_github_remote()

    def test_git_failure_raises(self):
        import subprocess
        with patch("subprocess.check_output", side_effect=subprocess.CalledProcessError(128, "git")):
            with pytest.raises(RuntimeError, match="git remote get-url origin"):
                _parse_github_remote()


class TestGitHubConfigAutoDetect:
    def test_owner_falls_back_to_remote(self, monkeypatch):
        monkeypatch.delenv("GITHUB_OWNER", raising=False)
        with patch("agentharness.config._parse_github_remote", return_value=("acme", "proj")):
            cfg = GitHubConfig()
            assert cfg.owner == "acme"

    def test_runs_repo_falls_back_to_remote(self, monkeypatch):
        monkeypatch.delenv("GITHUB_RUNS_REPO", raising=False)
        with patch("agentharness.config._parse_github_remote", return_value=("acme", "proj")):
            cfg = GitHubConfig()
            assert cfg.runs_repo == "proj"

    def test_env_var_overrides_remote(self, monkeypatch):
        monkeypatch.setenv("GITHUB_OWNER", "override-org")
        cfg = GitHubConfig()
        assert cfg.owner == "override-org"

    def test_runs_repo_env_var_overrides_remote(self, monkeypatch):
        monkeypatch.setenv("GITHUB_RUNS_REPO", "override-repo")
        cfg = GitHubConfig()
        assert cfg.runs_repo == "override-repo"


class TestGitHubConfigFeatureMarker:
    def test_github_config_default_feature_marker(self):
        """GitHubConfig.feature_marker defaults to 'agent' when not specified."""
        cfg = GitHubConfig()
        assert cfg.feature_marker == "agent"

    def test_github_config_accepts_custom_feature_marker(self):
        """GitHubConfig.feature_marker accepts a user-supplied value."""
        cfg = GitHubConfig(feature_marker="my-label")
        assert cfg.feature_marker == "my-label"

    def test_load_config_reads_feature_marker_from_json(self, tmp_path: Path):
        """load_config wires github.feature_marker from config.json."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({
            "storage_backend": "github",
            "github": {"feature_marker": "custom-marker"},
            "queues": {},
        }))
        config = load_config(config_path)
        assert config.github.feature_marker == "custom-marker"

    def test_load_config_defaults_feature_marker_when_missing(self, tmp_path: Path):
        """load_config falls back to 'agent' when github.feature_marker is omitted."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({
            "storage_backend": "github",
            "github": {},
            "queues": {},
        }))
        config = load_config(config_path)
        assert config.github.feature_marker == "agent"

    def test_github_config_default_subtask_marker(self):
        """GitHubConfig.subtask_marker defaults to 'agent-subtask' when not specified."""
        cfg = GitHubConfig()
        assert cfg.subtask_marker == "agent-subtask"

    def test_github_config_accepts_custom_subtask_marker(self):
        """GitHubConfig.subtask_marker accepts a user-supplied value."""
        cfg = GitHubConfig(subtask_marker="my-subtask-label")
        assert cfg.subtask_marker == "my-subtask-label"


class TestExistingBehaviorUnchanged:
    def test_queues_and_agent_paths_still_parsed(self, tmp_path):
        data = {
            "queues": {
                "planner-queue": {"agent": ".agents/planner.md"},
                "developer-queue": {"agent": ".agents/developer.md"},
            }
        }
        cfg_path = write_config(tmp_path, data)
        config = load_config(cfg_path)
        assert set(config.queue_names()) == {"planner-queue", "developer-queue"}
        assert config.queues["planner-queue"].agent == ".agents/planner.md"

    def test_defaults_parsed(self, tmp_path):
        data = {"queues": {}, "defaults": {"dead_letter_threshold": 5}}
        cfg_path = write_config(tmp_path, data)
        config = load_config(cfg_path)
        assert config.defaults.dead_letter_threshold == 5

    def test_storage_config_parsed(self, tmp_path):
        data = {"queues": {}, "storage": {"container": "my-container"}}
        cfg_path = write_config(tmp_path, data)
        config = load_config(cfg_path)
        assert config.storage.container == "my-container"


class TestStorageFactoriesThreadFeatureMarker:
    def test_storage_factories_thread_feature_marker_to_github_classes(self, tmp_path: Path, monkeypatch):
        """Both factories produce GitHub instances carrying the configured marker."""
        import os
        from agentharness.storage import create_state_manager, create_task_queue

        monkeypatch.setenv("GITHUB_TOKEN", "ghp_dummy_for_test")
        monkeypatch.setenv("GITHUB_OWNER", "acme")
        monkeypatch.setenv("GITHUB_RUNS_REPO", "runs")

        config_path = tmp_path / ".pipeline" / "config.json"
        config_path.parent.mkdir(parents=True)
        config_path.write_text(json.dumps({
            "storage_backend": "github",
            "github": {"feature_marker": "wired-through"},
            "queues": {"analyst-queue": {"agent": ".agents/analyst.md"}},
        }))
        config = load_config(config_path)

        queue = create_task_queue(config, "analyst-queue")
        state = create_state_manager(config)

        assert queue._subtask_marker == "agent-subtask"
        assert state._feature_marker == "wired-through"


class TestMaxAnalystIterationsConfig:
    def test_default_value_is_two(self):
        from agentharness.config import Config
        cfg = Config()
        assert cfg.max_analyst_iterations == 2

    def test_load_config_uses_default_when_absent(self, tmp_path):
        cfg_path = write_config(tmp_path, {
            "storage_backend": "azure",
            "queues": {},
        })
        cfg = load_config(cfg_path)
        assert cfg.max_analyst_iterations == 2

    def test_load_config_reads_explicit_value(self, tmp_path):
        cfg_path = write_config(tmp_path, {
            "storage_backend": "azure",
            "queues": {},
            "max_analyst_iterations": 5,
        })
        cfg = load_config(cfg_path)
        assert cfg.max_analyst_iterations == 5

    def test_load_config_zero_disables_loop(self, tmp_path):
        cfg_path = write_config(tmp_path, {
            "storage_backend": "azure",
            "queues": {},
            "max_analyst_iterations": 0,
        })
        cfg = load_config(cfg_path)
        assert cfg.max_analyst_iterations == 0
