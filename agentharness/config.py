"""Configuration loading for AgentHarness."""

from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from pydantic import BaseModel


class QueueConfig(BaseModel):
    agent: str


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
    return Config.model_validate(raw)
