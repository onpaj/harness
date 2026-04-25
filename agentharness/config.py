"""Configuration loading for AgentHarness."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

from pydantic import BaseModel


class ConfigValidationError(Exception):
    """Raised when config.json fails validation."""


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


class DefaultsConfig(BaseModel):
    dead_letter_threshold: int = 3
    max_revisions: int = 3
    poll_interval_seconds: float = 1.0


class Config(BaseModel):
    storage: StorageConfig = StorageConfig()
    queues: dict[str, QueueConfig] = {}
    defaults: DefaultsConfig = DefaultsConfig()
    config_dir: Path = Path(".")
    use_worktrees: bool = False
    worktree_base_dir: str = ".worktrees"
    worktree_base_branch: str | None = None

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
