"""Configuration loading for AgentHarness."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict


class ConfigError(Exception):
    """Raised when config.json fails validation."""


ConfigValidationError = ConfigError


def _parse_github_remote() -> tuple[str, str]:
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
            f"Remote URL {url!r} does not look like a GitHub repo."
        )
    return match.group(1), match.group(2)


class GitHubConfig(BaseModel):
    token_env: str = "GITHUB_TOKEN"
    owner_env: str = "GITHUB_OWNER"
    runs_repo_env: str = "GITHUB_RUNS_REPO"

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


class Config(BaseModel):
    model_config = ConfigDict(extra="ignore")
    max_revisions: int = 3
    github: GitHubConfig = GitHubConfig()
    config_dir: Path = Path(".")


_DEFAULT_CONFIG_PATH = Path(".pipeline/config.json")


def load_config(path: Path | None = None) -> Config:
    config_path = path or _DEFAULT_CONFIG_PATH
    load_dotenv(config_path.resolve().parent.parent / ".env")
    if not config_path.exists():
        raise FileNotFoundError(
            f"Pipeline config not found at {config_path}. "
            "Create .pipeline/config.json or pass --config."
        )
    raw = json.loads(config_path.read_text())
    return Config.model_validate({**raw, "config_dir": config_path.resolve().parent})
