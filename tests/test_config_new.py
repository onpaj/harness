"""Tests for simplified config.py."""

import json
from pathlib import Path
import pytest
from agentharness.config import Config, GitHubConfig, ConfigError, ConfigValidationError, load_config


def write_config(tmp_path: Path, data: dict) -> Path:
    config_dir = tmp_path / ".pipeline"
    config_dir.mkdir()
    config_file = config_dir / "config.json"
    config_file.write_text(json.dumps(data))
    return config_file


def test_config_defaults():
    cfg = Config()
    assert cfg.max_revisions == 3
    assert isinstance(cfg.github, GitHubConfig)


def test_load_config_empty_json(tmp_path):
    cfg_path = write_config(tmp_path, {})
    cfg = load_config(cfg_path)
    assert cfg.max_revisions == 3


def test_load_config_max_revisions(tmp_path):
    cfg_path = write_config(tmp_path, {"max_revisions": 5})
    cfg = load_config(cfg_path)
    assert cfg.max_revisions == 5


def test_load_config_ignores_unknown_keys(tmp_path):
    # Old config keys like storage_backend, queues should be silently ignored
    cfg_path = write_config(tmp_path, {
        "storage_backend": "github",
        "queues": {"analyst-queue": {"agent": ".agents/analyst.md"}},
        "max_revisions": 2,
    })
    cfg = load_config(cfg_path)
    assert cfg.max_revisions == 2


def test_load_config_sets_config_dir(tmp_path):
    cfg_path = write_config(tmp_path, {})
    cfg = load_config(cfg_path)
    assert cfg.config_dir == cfg_path.resolve().parent


def test_load_config_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        load_config(Path("/nonexistent/config.json"))


def test_config_error_alias():
    assert ConfigValidationError is ConfigError


def test_github_config_defaults():
    gh = GitHubConfig()
    assert gh.token_env == "GITHUB_TOKEN"
    assert gh.owner_env == "GITHUB_OWNER"
    assert gh.runs_repo_env == "GITHUB_RUNS_REPO"
