"""Configuration loading for AgentHarness."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pydantic import BaseModel


class ConfigValidationError(Exception):
    """Raised when config.json fails validation."""


# Alias for runtime environment issues (git version, OS, repo state)
ConfigError = ConfigValidationError


class QueueConfig(BaseModel):
    agent: str
    context_files: Any = None  # validated explicitly in load_config


class StorageConfig(BaseModel):
    connection_string_env: str = "AZURE_STORAGE_CONNECTION_STRING"
    container: str = "pipeline-artifacts"

    @property
    def connection_string(self) -> str:
        value = os.environ.get(self.connection_string_env)
        if not value:
            raise RuntimeError(
                f"Environment variable {self.connection_string_env!r} is not set. "
                "Set it to your Azure Storage connection string."
            )
        return value


def _parse_github_remote() -> tuple[str, str]:
    """Parse owner and repo from `git remote get-url origin`.

    Supports both HTTPS (https://github.com/owner/repo.git) and
    SSH (git@github.com:owner/repo.git) remote URLs.
    Raises RuntimeError if origin is not a GitHub remote or git fails.
    """
    try:
        url = subprocess.check_output(
            ["git", "remote", "get-url", "origin"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except subprocess.CalledProcessError:
        raise RuntimeError(
            "Could not detect GitHub repo: 'git remote get-url origin' failed. "
            "Set GITHUB_OWNER and GITHUB_RUNS_REPO env vars explicitly."
        )
    match = re.search(r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?$", url)
    if not match:
        raise RuntimeError(
            f"Remote URL {url!r} does not look like a GitHub repo. "
            "Set GITHUB_OWNER and GITHUB_RUNS_REPO env vars explicitly."
        )
    return match.group(1), match.group(2)


class GitHubConfig(BaseModel):
    token_env: str = "GITHUB_TOKEN"
    owner_env: str = "GITHUB_OWNER"      # optional — falls back to git remote
    runs_repo_env: str = "GITHUB_RUNS_REPO"  # optional — falls back to git remote
    clone_dir: str = ".worktrees"
    feature_marker: str = "agent"
    subtask_marker: str = "agent-subtask"

    @property
    def token(self) -> str:
        value = os.environ.get(self.token_env)
        if not value:
            raise RuntimeError(f"Environment variable {self.token_env!r} is not set.")
        return value

    @property
    def owner(self) -> str:
        return os.environ.get(self.owner_env) or _parse_github_remote()[0]

    @property
    def runs_repo(self) -> str:
        return os.environ.get(self.runs_repo_env) or _parse_github_remote()[1]


class DefaultsConfig(BaseModel):
    dead_letter_threshold: int = 3
    max_revisions: int = 3
    poll_interval_seconds: float = 1.0
    github_poll_interval_seconds: float = 60.0
    max_concurrent_workers: int = 1


class Config(BaseModel):
    storage: StorageConfig = StorageConfig()
    github: GitHubConfig = GitHubConfig()
    storage_backend: str = "azure"  # "azure" | "github"
    queues: dict[str, QueueConfig] = {}
    defaults: DefaultsConfig = DefaultsConfig()
    config_dir: Path = Path(".")
    use_worktrees: bool = False
    worktree_base_dir: str = ".worktrees"
    worktree_base_branch: str | None = None
    max_analyst_iterations: int = 2
    auto_mode: bool = False
    auto_mode_poll_seconds: float = 60.0

    def queue_names(self) -> list[str]:
        return list(self.queues.keys())

    def agent_path_for_queue(self, queue_name: str) -> Path:
        queue = self.queues.get(queue_name)
        if not queue:
            raise ValueError(f"Queue {queue_name!r} not found in config")
        return Path(queue.agent)


_DEFAULT_CONFIG_PATH = Path(".pipeline/config.json")


def load_config(path: Path | None = None) -> Config:
    config_path = path or _DEFAULT_CONFIG_PATH
    # .env lives in the project root (one level above .pipeline/)
    load_dotenv(config_path.resolve().parent.parent / ".env")
    if not config_path.exists():
        raise FileNotFoundError(
            f"Pipeline config not found at {config_path}. "
            "Create .pipeline/config.json or pass --config."
        )
    raw = json.loads(config_path.read_text())
    _validate_worktree_config(raw, config_path)
    config = Config.model_validate(raw)
    config.config_dir = config_path.resolve().parent
    _validate_and_normalize_context_files(config)
    return config


def _validate_worktree_config(raw: dict, config_path: Path) -> None:
    use_worktrees = raw.get("use_worktrees", False)
    if not isinstance(use_worktrees, bool):
        got = type(use_worktrees).__name__
        raise ConfigValidationError(
            f"'use_worktrees' in {config_path} must be a JSON boolean (true/false), got {got}. "
            "Remove quotes if you wrote \"true\" or \"false\" as a string."
        )

    base_dir = raw.get("worktree_base_dir", ".worktrees")
    if not isinstance(base_dir, str):
        raise ConfigValidationError(
            f"'worktree_base_dir' in {config_path} must be a string."
        )
    if base_dir.startswith("/"):
        raise ConfigValidationError(
            f"'worktree_base_dir' in {config_path} must be a relative path (no leading '/'). "
            f"Got: {base_dir!r}"
        )
    if ".." in Path(base_dir).parts:
        raise ConfigValidationError(
            f"'worktree_base_dir' in {config_path} must not contain '..'. "
            f"Got: {base_dir!r}"
        )


def _validate_and_normalize_context_files(config: Config) -> None:
    for queue_name, queue_config in config.queues.items():
        cf = queue_config.context_files
        if cf is None:
            continue
        if isinstance(cf, list) and len(cf) == 0:
            queue_config.context_files = None
            continue
        if not isinstance(cf, list) or not all(isinstance(s, str) for s in cf):
            got = type(cf).__name__
            raise ConfigValidationError(
                f"Agent '{queue_name}': context_files must be a list of strings, got {got}"
            )
