# Implement Skill as Orchestrator — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Python observer + queue infrastructure with a single Claude Code `/implement` skill that drives the entire pipeline by spawning subagents via the Task tool, using local filesystem artifacts and a JSON checkpoint for state.

**Architecture:** The orchestrator is a Claude Code session (the `implement.md` skill). It reads a GitHub issue for the brief, runs each pipeline phase by spawning a Task subagent, and checkpoints progress after each phase to `artifacts/feat-{issue}/state.json`. The Python package is reduced to CLI utilities and the checkpoint helper.

**Tech Stack:** Python 3.11+, Click, Pydantic v2, pytest, Rich/Textual (TUI), gh CLI, Claude Code Task tool

---

## File Map

### Create
- `agentharness/checkpoint.py` — checkpoint CRUD with atomic JSON writes
- `agentharness/data/claude-agents/implement.md` — orchestrator skill (installed by `agentharness init`)
- `tests/test_checkpoint.py` — unit tests for checkpoint module

### Modify
- `agentharness/models.py` — replace all models with `Checkpoint`, `PhaseCheckpoint`, `TaskCheckpoint`
- `agentharness/config.py` — remove Azure/queue config; keep only `max_revisions`, `agent_paths`, GitHub detection for `init`
- `agentharness/cli.py` — remove observer/queue commands; add `checkpoint` subcommand group; update `status`/`list` to read checkpoints
- `agentharness/tui.py` — rewrite to glob and read checkpoint files directly (no storage backends)
- `agentharness/brainstorm.py` — keep only `start_brainstorm()`, strip all upload/enqueue/queue code
- `pyproject.toml` — remove azure-storage-blob, azure-storage-queue, aiohttp, httpx dependencies

### Delete
- `agentharness/observer.py`
- `agentharness/run_task.py`
- `agentharness/worker.py`
- `agentharness/agent_runner.py`
- `agentharness/storage_protocol.py`
- `agentharness/storage.py`
- `agentharness/state_manager.py`
- `agentharness/state_change.py`
- `agentharness/auto_mode.py`
- `agentharness/dispatcher.py`
- `agentharness/azure_artifacts.py`
- `agentharness/azure_queue.py`
- `agentharness/azure_state.py`
- `agentharness/github_queue.py`
- `agentharness/github_artifacts.py`
- `agentharness/github_state.py`
- `agentharness/github_client.py`
- `agentharness/github_labels.py`
- `agentharness/worktree_manager.py`
- `agentharness/tui_state_change.py`
- All test files corresponding to deleted modules (listed in Task 10)

---

## Task 1: Replace models.py with checkpoint models

**Files:**
- Modify: `agentharness/models.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_checkpoint.py
from datetime import datetime, UTC
from agentharness.models import Checkpoint, PhaseCheckpoint, TaskCheckpoint

def test_checkpoint_defaults():
    cp = Checkpoint(feature_id="feat-123", issue_number=123)
    assert cp.phases["analyzing"].status == "pending"
    assert cp.phases["analyzing"].updated_at is None
    assert cp.tasks == []
    assert cp.max_revisions == 3

def test_checkpoint_phase_names():
    cp = Checkpoint(feature_id="feat-123", issue_number=123)
    # developing is included for display; next_pending_phase() skips it
    expected = {"analyzing", "architecting", "designing", "planning", "developing"}
    assert set(cp.phases.keys()) == expected

def test_task_checkpoint_defaults():
    t = TaskCheckpoint(name="setup-models")
    assert t.status == "pending"
    assert t.revision == 1
    assert t.updated_at is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /path/to/project && .venv/bin/pytest tests/test_checkpoint.py::test_checkpoint_defaults -v
```
Expected: `ImportError` or `AttributeError` — `Checkpoint` does not exist yet.

- [ ] **Step 3: Replace agentharness/models.py with new models**

Keep `AgentDefinition` alongside the new checkpoint models — it is still used by `prompt_builder.py` and `brainstorm.py`.

`_PIPELINE_PHASES` omits `"developing"` because `next_pending_phase()` must fall through to task logic when the 4 main phases are done; `"developing"` is tracked in the phases dict for informational display only.

```python
"""Pydantic models for AgentHarness checkpoint and agent definitions."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

# Phases returned by next_pending_phase() — "developing" is omitted so the
# orchestrator falls through to task-level dispatch when planning is done.
_PIPELINE_PHASES = ["analyzing", "architecting", "designing", "planning"]
# All phases stored in the checkpoint (developing is informational).
_ALL_PHASES = [*_PIPELINE_PHASES, "developing"]


class PhaseCheckpoint(BaseModel):
    status: str = "pending"   # pending | in_progress | completed | failed
    updated_at: datetime | None = None


class TaskCheckpoint(BaseModel):
    name: str
    status: str = "pending"   # pending | in_progress | completed | failed
    revision: int = 1
    updated_at: datetime | None = None


def _default_phases() -> dict[str, PhaseCheckpoint]:
    return {phase: PhaseCheckpoint() for phase in _ALL_PHASES}


class Checkpoint(BaseModel):
    feature_id: str
    issue_number: int
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    max_revisions: int = 3
    phases: dict[str, PhaseCheckpoint] = Field(default_factory=_default_phases)
    tasks: list[TaskCheckpoint] = Field(default_factory=list)

    def next_pending_phase(self) -> str | None:
        for phase in _PIPELINE_PHASES:
            info = self.phases.get(phase)
            if info and info.status in ("pending", "in_progress"):
                return phase
        return None

    def next_pending_task(self) -> TaskCheckpoint | None:
        return next(
            (t for t in self.tasks if t.status in ("pending", "in_progress")),
            None,
        )

    def all_tasks_complete(self) -> bool:
        return bool(self.tasks) and all(
            t.status in ("completed", "failed") for t in self.tasks
        )


# AgentDefinition is kept for prompt_builder.py and brainstorm.py.
class AgentDefinition(BaseModel):
    id: str
    display_name: str = ""
    model: str
    phase: str
    max_turns: int = 20
    allowed_tools: list[str] | None = None
    output_format: str = "markdown"
    visibility_timeout: int = 600
    retry_limit: int = 3
    output_parsing: str = "none"
    output_file_glob: str | None = None
    context_files: list[str] | None = None
    system_prompt: str
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/test_checkpoint.py::test_checkpoint_defaults tests/test_checkpoint.py::test_checkpoint_phase_names tests/test_checkpoint.py::test_task_checkpoint_defaults -v
```
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add agentharness/models.py tests/test_checkpoint.py
git commit -m "feat: replace models with checkpoint-centric Checkpoint, PhaseCheckpoint, TaskCheckpoint"
```

---

## Task 2: Implement checkpoint.py with atomic read/write

**Files:**
- Create: `agentharness/checkpoint.py`
- Modify: `tests/test_checkpoint.py`

- [ ] **Step 1: Add failing tests for checkpoint CRUD**

Append to `tests/test_checkpoint.py`:

```python
import json
import pytest
from pathlib import Path
from agentharness.checkpoint import (
    init_checkpoint,
    load_checkpoint,
    save_checkpoint,
    update_phase,
    update_task,
    set_tasks,
    query_next,
)

def test_init_checkpoint_creates_file(tmp_path):
    cp = init_checkpoint(123, base_dir=tmp_path)
    state_file = tmp_path / "artifacts" / "feat-123" / "state.json"
    assert state_file.exists()
    data = json.loads(state_file.read_text())
    assert data["feature_id"] == "feat-123"
    assert data["issue_number"] == 123

def test_init_checkpoint_idempotent(tmp_path):
    init_checkpoint(123, base_dir=tmp_path)
    cp1 = load_checkpoint("feat-123", base_dir=tmp_path)
    init_checkpoint(123, base_dir=tmp_path)
    cp2 = load_checkpoint("feat-123", base_dir=tmp_path)
    assert cp1.created_at == cp2.created_at  # not overwritten

def test_update_phase_sets_timestamp(tmp_path):
    init_checkpoint(123, base_dir=tmp_path)
    update_phase("feat-123", "analyzing", "completed", base_dir=tmp_path)
    cp = load_checkpoint("feat-123", base_dir=tmp_path)
    assert cp.phases["analyzing"].status == "completed"
    assert cp.phases["analyzing"].updated_at is not None

def test_set_tasks_populates_list(tmp_path):
    init_checkpoint(123, base_dir=tmp_path)
    set_tasks("feat-123", ["setup-models", "api-endpoints"], base_dir=tmp_path)
    cp = load_checkpoint("feat-123", base_dir=tmp_path)
    assert len(cp.tasks) == 2
    assert cp.tasks[0].name == "setup-models"
    assert cp.tasks[1].status == "pending"

def test_update_task_increments_revision(tmp_path):
    init_checkpoint(123, base_dir=tmp_path)
    set_tasks("feat-123", ["setup-models"], base_dir=tmp_path)
    update_task("feat-123", "setup-models", "in_progress", base_dir=tmp_path)
    update_task("feat-123", "setup-models", "in_progress", revision=2, base_dir=tmp_path)
    cp = load_checkpoint("feat-123", base_dir=tmp_path)
    assert cp.tasks[0].revision == 2

def test_query_next_returns_pending_phase(tmp_path):
    init_checkpoint(123, base_dir=tmp_path)
    result = query_next("feat-123", base_dir=tmp_path)
    assert result["type"] == "phase"
    assert result["name"] == "analyzing"

def test_query_next_returns_pending_task_after_planning(tmp_path):
    init_checkpoint(123, base_dir=tmp_path)
    for phase in ["analyzing", "architecting", "designing", "planning"]:
        update_phase("feat-123", phase, "completed", base_dir=tmp_path)
    set_tasks("feat-123", ["setup-models"], base_dir=tmp_path)
    result = query_next("feat-123", base_dir=tmp_path)
    assert result["type"] == "task"
    assert result["name"] == "setup-models"

def test_query_next_returns_complete_when_done(tmp_path):
    init_checkpoint(123, base_dir=tmp_path)
    for phase in ["analyzing", "architecting", "designing", "planning", "developing"]:
        update_phase("feat-123", phase, "completed", base_dir=tmp_path)
    set_tasks("feat-123", ["setup-models"], base_dir=tmp_path)
    update_task("feat-123", "setup-models", "completed", base_dir=tmp_path)
    result = query_next("feat-123", base_dir=tmp_path)
    assert result["type"] == "complete"

def test_atomic_write_uses_temp_rename(tmp_path, monkeypatch):
    init_checkpoint(123, base_dir=tmp_path)
    state_file = tmp_path / "artifacts" / "feat-123" / "state.json"
    original_mtime = state_file.stat().st_mtime
    update_phase("feat-123", "analyzing", "completed", base_dir=tmp_path)
    assert state_file.stat().st_mtime >= original_mtime
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/test_checkpoint.py -k "test_init_checkpoint" -v
```
Expected: `ImportError` — `agentharness.checkpoint` does not exist.

- [ ] **Step 3: Create agentharness/checkpoint.py**

```python
"""Checkpoint CRUD for AgentHarness pipeline state."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agentharness.models import Checkpoint, PhaseCheckpoint, TaskCheckpoint

_DEFAULT_BASE = Path(".")


def _state_path(feature_id: str, base_dir: Path) -> Path:
    return base_dir / "artifacts" / feature_id / "state.json"


def _load_raw(feature_id: str, base_dir: Path) -> dict:
    path = _state_path(feature_id, base_dir)
    return json.loads(path.read_text())


def _save_raw(feature_id: str, data: dict, base_dir: Path) -> None:
    path = _state_path(feature_id, base_dir)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str))
    os.replace(tmp, path)


def init_checkpoint(issue_number: int, base_dir: Path = _DEFAULT_BASE) -> Checkpoint:
    feature_id = f"feat-{issue_number}"
    path = _state_path(feature_id, base_dir)
    if path.exists():
        return load_checkpoint(feature_id, base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    cp = Checkpoint(feature_id=feature_id, issue_number=issue_number)
    _save_raw(feature_id, cp.model_dump(mode="json"), base_dir)
    return cp


def load_checkpoint(feature_id: str, base_dir: Path = _DEFAULT_BASE) -> Checkpoint:
    return Checkpoint.model_validate(_load_raw(feature_id, base_dir))


def save_checkpoint(cp: Checkpoint, base_dir: Path = _DEFAULT_BASE) -> None:
    _save_raw(cp.feature_id, cp.model_dump(mode="json"), base_dir)


def update_phase(
    feature_id: str,
    phase: str,
    status: str,
    base_dir: Path = _DEFAULT_BASE,
) -> None:
    cp = load_checkpoint(feature_id, base_dir)
    new_phases = {
        **cp.phases,
        phase: PhaseCheckpoint(status=status, updated_at=datetime.now(UTC)),
    }
    updated = cp.model_copy(update={"phases": new_phases})
    save_checkpoint(updated, base_dir)


def update_task(
    feature_id: str,
    task_name: str,
    status: str,
    revision: int | None = None,
    base_dir: Path = _DEFAULT_BASE,
) -> None:
    cp = load_checkpoint(feature_id, base_dir)
    new_tasks = []
    for t in cp.tasks:
        if t.name == task_name:
            new_tasks.append(t.model_copy(update={
                "status": status,
                "updated_at": datetime.now(UTC),
                **({"revision": revision} if revision is not None else {}),
            }))
        else:
            new_tasks.append(t)
    updated = cp.model_copy(update={"tasks": new_tasks})
    save_checkpoint(updated, base_dir)


def set_tasks(
    feature_id: str,
    task_names: list[str],
    base_dir: Path = _DEFAULT_BASE,
) -> None:
    cp = load_checkpoint(feature_id, base_dir)
    tasks = [TaskCheckpoint(name=name) for name in task_names]
    updated = cp.model_copy(update={"tasks": tasks})
    save_checkpoint(updated, base_dir)


def query_next(
    feature_id: str,
    base_dir: Path = _DEFAULT_BASE,
) -> dict[str, Any]:
    cp = load_checkpoint(feature_id, base_dir)
    # next_pending_phase() only returns from [analyzing, architecting, designing, planning]
    phase = cp.next_pending_phase()
    if phase:
        return {"type": "phase", "name": phase}
    # All pipeline phases done — dispatch by task
    task = cp.next_pending_task()
    if task:
        return {"type": "task", "name": task.name, "revision": task.revision}
    return {"type": "complete"}


def list_checkpoints(base_dir: Path = _DEFAULT_BASE) -> list[Checkpoint]:
    artifacts = base_dir / "artifacts"
    if not artifacts.exists():
        return []
    checkpoints = []
    for state_file in sorted(artifacts.glob("feat-*/state.json")):
        try:
            checkpoints.append(Checkpoint.model_validate(json.loads(state_file.read_text())))
        except Exception:
            continue
    return checkpoints
```

- [ ] **Step 4: Run all checkpoint tests**

```bash
.venv/bin/pytest tests/test_checkpoint.py -v
```
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add agentharness/checkpoint.py tests/test_checkpoint.py
git commit -m "feat: add checkpoint.py with atomic read/write and phase/task state management"
```

---

## Task 3: Add checkpoint CLI subcommand

**Files:**
- Modify: `agentharness/cli.py` (add only the checkpoint group — do not touch other commands yet)

- [ ] **Step 1: Write failing test**

```python
# append to tests/test_checkpoint.py
from click.testing import CliRunner
from agentharness.cli import main

def test_cli_checkpoint_init(tmp_path):
    runner = CliRunner()
    result = runner.invoke(main, ["checkpoint", "init", "123"], catch_exceptions=False,
                           env={"AGENTHARNESS_BASE_DIR": str(tmp_path)})
    assert result.exit_code == 0
    assert (tmp_path / "artifacts" / "feat-123" / "state.json").exists()

def test_cli_checkpoint_phase(tmp_path):
    runner = CliRunner()
    runner.invoke(main, ["checkpoint", "init", "123"],
                  env={"AGENTHARNESS_BASE_DIR": str(tmp_path)})
    result = runner.invoke(main, ["checkpoint", "phase", "feat-123", "analyzing", "completed"],
                           env={"AGENTHARNESS_BASE_DIR": str(tmp_path)})
    assert result.exit_code == 0

def test_cli_checkpoint_status_json(tmp_path):
    runner = CliRunner()
    runner.invoke(main, ["checkpoint", "init", "123"],
                  env={"AGENTHARNESS_BASE_DIR": str(tmp_path)})
    result = runner.invoke(main, ["checkpoint", "status", "feat-123"],
                           env={"AGENTHARNESS_BASE_DIR": str(tmp_path)})
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["type"] == "phase"
    assert data["name"] == "analyzing"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/test_checkpoint.py -k "test_cli_checkpoint" -v
```
Expected: FAIL — no `checkpoint` subcommand exists.

- [ ] **Step 3: Add checkpoint command group to cli.py**

Add this block to `agentharness/cli.py` (after the existing imports, before the `main` group):

```python
import json as _json
from agentharness.checkpoint import (
    init_checkpoint as _cp_init,
    update_phase as _cp_phase,
    update_task as _cp_task,
    set_tasks as _cp_set_tasks,
    query_next as _cp_query,
)

def _base_dir() -> Path:
    env = os.environ.get("AGENTHARNESS_BASE_DIR")
    return Path(env) if env else Path(".")
```

Then add the command group (before the final `if __name__ == "__main__"` if present, otherwise at the end):

```python
@main.group("checkpoint")
def checkpoint_group() -> None:
    """Manage pipeline checkpoint state."""


@checkpoint_group.command("init")
@click.argument("issue_number", type=int)
def checkpoint_init(issue_number: int) -> None:
    """Create state.json for issue (idempotent)."""
    _cp_init(issue_number, base_dir=_base_dir())
    console.print(f"[green]checkpoint init:[/green] feat-{issue_number}")


@checkpoint_group.command("phase")
@click.argument("feature_id")
@click.argument("phase")
@click.argument("status")
def checkpoint_phase(feature_id: str, phase: str, status: str) -> None:
    """Update a phase status in the checkpoint."""
    _cp_phase(feature_id, phase, status, base_dir=_base_dir())


@checkpoint_group.command("task")
@click.argument("feature_id")
@click.argument("task_name")
@click.argument("status")
@click.option("--revision", type=int, default=None)
def checkpoint_task(feature_id: str, task_name: str, status: str, revision: int | None) -> None:
    """Update a task status in the checkpoint."""
    _cp_task(feature_id, task_name, status, revision=revision, base_dir=_base_dir())


@checkpoint_group.command("tasks")
@click.argument("feature_id")
@click.argument("task_names")
def checkpoint_tasks(feature_id: str, task_names: str) -> None:
    """Populate task list (comma-separated names) after planning."""
    names = [n.strip() for n in task_names.split(",") if n.strip()]
    _cp_set_tasks(feature_id, names, base_dir=_base_dir())


@checkpoint_group.command("status")
@click.argument("feature_id")
def checkpoint_status(feature_id: str) -> None:
    """Print next pending phase or task as JSON."""
    result = _cp_query(feature_id, base_dir=_base_dir())
    click.echo(_json.dumps(result))
```

Also add `import os` to the top-level imports in `cli.py` if not already present.

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/test_checkpoint.py -k "test_cli_checkpoint" -v
```
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add agentharness/cli.py tests/test_checkpoint.py
git commit -m "feat: add checkpoint CLI subcommand group (init, phase, task, tasks, status)"
```

---

## Task 4: Simplify config.py

**Files:**
- Modify: `agentharness/config.py`

The new config only needs: `max_revisions`, `agent_paths` (map of role → .agents/*.md path), and GitHub detection for `init`. Remove `StorageConfig`, `QueueConfig`, `DefaultsConfig`, `storage_backend`, and all Azure/queue fields.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_config_new.py
import json
from pathlib import Path
import pytest
from agentharness.config import Config, load_config

def write_config(tmp_path: Path, data: dict) -> Path:
    config_dir = tmp_path / ".pipeline"
    config_dir.mkdir()
    config_file = config_dir / "config.json"
    config_file.write_text(json.dumps(data))
    return config_file

def test_minimal_config_loads():
    cfg = Config(max_revisions=3)
    assert cfg.max_revisions == 3

def test_load_config_defaults(tmp_path):
    cfg_path = write_config(tmp_path, {})
    cfg = load_config(cfg_path)
    assert cfg.max_revisions == 3

def test_load_config_max_revisions(tmp_path):
    cfg_path = write_config(tmp_path, {"max_revisions": 5})
    cfg = load_config(cfg_path)
    assert cfg.max_revisions == 5
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/test_config_new.py -v
```
Expected: Tests that import new `Config` shape will fail if fields don't match.

- [ ] **Step 3: Rewrite agentharness/config.py**

```python
"""Configuration loading for AgentHarness."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel


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
    config = Config.model_validate(raw)
    config.config_dir = config_path.resolve().parent
    return config
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/test_config_new.py tests/test_config.py -v
```
Expected: `test_config_new.py` passes; `test_config.py` will fail on removed fields — that is expected and those tests are deleted in Task 10.

- [ ] **Step 5: Commit**

```bash
git add agentharness/config.py tests/test_config_new.py
git commit -m "refactor: simplify config.py — remove Azure/queue config, keep only max_revisions and GitHub detection"
```

---

## Task 5: Write the implement.md orchestrator skill

**Files:**
- Create: `agentharness/data/claude-agents/implement.md`

This skill replaces the queue-based pipeline. It is invoked as `/implement 123` and drives the full agent pipeline via the Task tool.

- [ ] **Step 1: Create the directory**

```bash
mkdir -p agentharness/data/claude-agents
```

- [ ] **Step 2: Create agentharness/data/claude-agents/implement.md**

```markdown
---
id: implement
description: Orchestrate the full AgentHarness pipeline for a GitHub issue
---

You are the AgentHarness pipeline orchestrator. When invoked as `/implement {issue_number}`, you drive the complete feature pipeline by spawning subagents via the Task tool.

## Setup

1. Extract the issue number from your input args (the number after `/implement`).
2. Run: `gh issue view {issue_number} --json body,title` and save the `body` field to `artifacts/feat-{issue_number}/brief.md` (create the directory if needed).
3. Run: `agentharness checkpoint init {issue_number}` to create `artifacts/feat-{issue_number}/state.json` (idempotent — safe to run on resume).
4. Read the checkpoint to determine what is already complete: `agentharness checkpoint status feat-{issue_number}` — this returns JSON like `{"type": "phase", "name": "analyzing"}` or `{"type": "task", "name": "setup-models", "revision": 1}` or `{"type": "complete"}`.

## Phase Loop

Run phases in order: `analyzing` → `architecting` → `designing` → `planning`. Skip any phase whose status is already `completed` (check via the checkpoint status command).

For each phase, before spawning the Task:
- Run `agentharness checkpoint phase feat-{issue_number} {phase} in_progress`
- Read the agent system prompt from `.agents/{agent_name}.md` (strip the YAML frontmatter, use only the Markdown body as the system prompt)
- Read all input artifacts for the phase (paths listed below)
- Spawn Task with the assembled prompt (system prompt + artifact contents)
- After Task completes, write its output to the output artifact path
- Run `agentharness checkpoint phase feat-{issue_number} {phase} completed`

### Phase → Agent Mapping

| Phase | Agent file | Input artifacts | Output artifact |
|-------|-----------|-----------------|-----------------|
| analyzing | `.agents/analyst.md` | `brief.md` | `spec.r1.md` |
| architecting | `.agents/architect.md` | `spec.r1.md` | `arch-review.r1.md` |
| designing | `.agents/designer.md` | `spec.r1.md`, `arch-review.r1.md` | `design.r1.md` |
| planning | `.agents/planner.md` | `spec.r1.md`, `arch-review.r1.md`, `design.r1.md` | `task-plan.r1.md` |

All paths are relative to `artifacts/feat-{issue_number}/`.

## Task Extraction (after planning)

After `task-plan.r1.md` is written:
1. Parse `### task:` headers from the file — each header like `### task: setup-models` defines one task.
2. Run: `agentharness checkpoint tasks feat-{issue_number} "task-a,task-b,task-c"` with the comma-separated task names.
3. For each task, write a task-context file to `artifacts/feat-{issue_number}/task-context/{task_name}.md` containing the section from `task-plan.r1.md` under that task's `### task:` header (everything until the next `### task:` header or end of file).

## Developer/Reviewer Loop

Process tasks serially. For each task (in order), skip if its status is already `completed`.

### Developer Task

1. Run `agentharness checkpoint task feat-{issue_number} {task_name} in_progress`
2. Read the current revision: `agentharness checkpoint status feat-{issue_number}` returns `{"type": "task", "name": "...", "revision": N}`
3. Read `.agents/developer.md` system prompt (strip frontmatter)
4. Also read the developer's context_files from the frontmatter (the `context_files:` list) and include their contents in the prompt
5. Spawn Task with:
   - System prompt from developer.md (including injected context file content)
   - Content of `artifacts/feat-{issue_number}/task-context/{task_name}.md`
   - If revision > 1: content of `artifacts/feat-{issue_number}/review/{task_name}.r{N-1}.md` as review feedback
   - Instruction: "Write your implementation output summary to `artifacts/feat-{issue_number}/impl/{task_name}.r{N}.md`"
6. After Task completes, verify `impl/{task_name}.r{N}.md` exists.

### Reviewer Task

1. Read `.agents/reviewer.md` system prompt (strip frontmatter)
2. Spawn Task with:
   - System prompt from reviewer.md
   - Content of `artifacts/feat-{issue_number}/task-context/{task_name}.md`
   - Content of `artifacts/feat-{issue_number}/impl/{task_name}.r{N}.md`
   - Instruction: "Write your review output to `artifacts/feat-{issue_number}/review/{task_name}.r{N}.md`. End with `**Status:** PASS` or `**Status:** REVISION_NEEDED`."
3. Read the reviewer output file and parse `**Status:**` line.

### Handling Review Result

- **PASS**: Run `agentharness checkpoint task feat-{issue_number} {task_name} completed`. Move to next task.
- **REVISION_NEEDED**: Check current revision against `max_revisions` (default 3, read from checkpoint).
  - If revision < max_revisions: increment revision with `agentharness checkpoint task feat-{issue_number} {task_name} in_progress --revision {N+1}`, then repeat Developer Task with the new revision.
  - If revision >= max_revisions: run `agentharness checkpoint phase feat-{issue_number} developing failed` and stop with an error message.

## Completion

After all tasks are `completed`:
1. Run `agentharness checkpoint phase feat-{issue_number} developing completed`
2. Print: `Pipeline complete for feat-{issue_number}. All tasks passed review.`

## Resume

If interrupted and re-invoked with the same issue number, steps 3–4 (checkpoint init + status) will detect already-completed phases and tasks. Skip them and resume from the first pending phase or task.
```

- [ ] **Step 3: Verify the file exists**

```bash
ls -la agentharness/data/claude-agents/implement.md
```

- [ ] **Step 4: Commit**

```bash
git add agentharness/data/claude-agents/implement.md
git commit -m "feat: add implement.md orchestrator skill — single Claude session drives full pipeline via Task tool"
```

---

## Task 6: Install implement skill via agentharness init

**Files:**
- Modify: `agentharness/cli.py` (update `init_project` command)

`agentharness init` currently installs from `data/agents/` → `.agents/` and `data/skills/` → `.claude/skills/`. It must also install from `data/claude-agents/` → `.claude/agents/`.

- [ ] **Step 1: Write failing test**

```python
# tests/test_cli_init.py
import shutil
from pathlib import Path
from click.testing import CliRunner
from agentharness.cli import main

def test_init_installs_implement_skill(tmp_path):
    runner = CliRunner()
    result = runner.invoke(main, ["init", "--dir", str(tmp_path)])
    assert result.exit_code == 0
    skill_file = tmp_path / ".claude" / "agents" / "implement.md"
    assert skill_file.exists(), f"implement.md not installed, output: {result.output}"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest tests/test_cli_init.py::test_init_installs_implement_skill -v
```
Expected: FAIL — `.claude/agents/implement.md` is not installed.

- [ ] **Step 3: Update init_project in cli.py**

Find the `init_project` function in `cli.py`. After the existing `flat_destinations` loop (which copies `.agents/` and `.pipeline/`), add:

```python
    # Install Claude Code skills to .claude/agents/
    claude_agents_src = data_root / "claude-agents"
    if claude_agents_src.exists():
        dst_claude_agents = target / ".claude" / "agents"
        dst_claude_agents.mkdir(parents=True, exist_ok=True)
        for src_file in claude_agents_src.iterdir():
            dst_file = dst_claude_agents / src_file.name
            if dst_file.exists() and not force:
                console.print(f"[dim]skip[/dim] {dst_file.relative_to(target)} (use --force to overwrite)")
                continue
            shutil.copy2(src_file, dst_file)
            console.print(f"[green]wrote[/green] {dst_file.relative_to(target)}")
```

Also update the final print from `"Run agentharness observe"` to `"Run /implement <issue> in Claude Code"`:

```python
    console.print("\n[bold]Done.[/bold] Run [bold]/implement <issue-number>[/bold] in Claude Code to start the pipeline.")
```

- [ ] **Step 4: Run test**

```bash
.venv/bin/pytest tests/test_cli_init.py::test_init_installs_implement_skill -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agentharness/cli.py tests/test_cli_init.py
git commit -m "feat: agentharness init now installs implement.md to .claude/agents/"
```

---

## Task 7: Rewrite tui.py to read checkpoint files

**Files:**
- Modify: `agentharness/tui.py`

The TUI currently imports from `storage.py`, `dispatcher.py`, `state_manager.py`, `state_change.py`, and `tui_state_change.py` — all being deleted. Rewrite it to read `Checkpoint` objects from local filesystem by globbing `artifacts/feat-*/state.json`.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_tui_checkpoint.py
import json
from pathlib import Path
import pytest
from agentharness.tui import _load_all_checkpoints

def test_load_all_checkpoints_empty(tmp_path):
    result = _load_all_checkpoints(base_dir=tmp_path)
    assert result == []

def test_load_all_checkpoints_reads_state_files(tmp_path):
    from agentharness.checkpoint import init_checkpoint, update_phase
    init_checkpoint(123, base_dir=tmp_path)
    init_checkpoint(456, base_dir=tmp_path)
    update_phase("feat-123", "analyzing", "completed", base_dir=tmp_path)
    result = _load_all_checkpoints(base_dir=tmp_path)
    assert len(result) == 2
    ids = {cp.feature_id for cp in result}
    assert ids == {"feat-123", "feat-456"}

def test_load_all_checkpoints_skips_corrupt_files(tmp_path):
    (tmp_path / "artifacts" / "feat-bad").mkdir(parents=True)
    (tmp_path / "artifacts" / "feat-bad" / "state.json").write_text("not json")
    result = _load_all_checkpoints(base_dir=tmp_path)
    assert result == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/test_tui_checkpoint.py -v
```
Expected: `ImportError` — `_load_all_checkpoints` does not exist.

- [ ] **Step 3: Rewrite agentharness/tui.py**

Replace the entire file with a simplified Textual TUI that reads checkpoints:

```python
"""Textual TUI for real-time pipeline monitoring."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import DataTable, Footer, Header

from agentharness.checkpoint import list_checkpoints
from agentharness.models import Checkpoint

_REFRESH_SECONDS = 2.0
_BASE_DIR = Path(".")

log = logging.getLogger(__name__)


def _load_all_checkpoints(base_dir: Path = _BASE_DIR) -> list[Checkpoint]:
    return list_checkpoints(base_dir)


def _phase_summary(cp: Checkpoint) -> str:
    completed = sum(1 for p in cp.phases.values() if p.status == "completed")
    total = len(cp.phases)
    in_progress = next(
        (name for name, p in cp.phases.items() if p.status == "in_progress"), None
    )
    if in_progress:
        return f"{in_progress} ({completed}/{total})"
    if completed == total:
        return "done"
    return f"{completed}/{total} phases"


def _task_summary(cp: Checkpoint) -> str:
    if not cp.tasks:
        return "—"
    completed = sum(1 for t in cp.tasks if t.status == "completed")
    total = len(cp.tasks)
    return f"{completed}/{total}"


def _overall_status(cp: Checkpoint) -> str:
    if any(p.status == "failed" for p in cp.phases.values()):
        return "failed"
    if any(t.status == "failed" for t in cp.tasks):
        return "failed"
    if cp.all_tasks_complete():
        return "done"
    if any(p.status == "in_progress" for p in cp.phases.values()):
        return "running"
    if any(t.status == "in_progress" for t in cp.tasks):
        return "running"
    return "pending"


_STATUS_COLORS = {
    "done": "green",
    "failed": "red",
    "running": "yellow",
    "pending": "dim",
}


class PipelineMonitor(App):
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
    ]

    CSS = """
    DataTable { height: 1fr; }
    """

    def compose(self) -> ComposeResult:
        yield Header()
        yield DataTable(id="features")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#features", DataTable)
        table.add_columns("Feature", "Status", "Phase", "Tasks", "Updated")
        self._refresh_table()
        self.set_interval(_REFRESH_SECONDS, self._refresh_table)

    def _refresh_table(self) -> None:
        table = self.query_one("#features", DataTable)
        table.clear()
        checkpoints = _load_all_checkpoints()
        for cp in checkpoints:
            status = _overall_status(cp)
            color = _STATUS_COLORS.get(status, "white")
            updated = max(
                (p.updated_at for p in cp.phases.values() if p.updated_at),
                default=cp.created_at,
            )
            updated_str = updated.strftime("%H:%M:%S") if updated else "—"
            table.add_row(
                cp.feature_id,
                Text(status, style=color),
                _phase_summary(cp),
                _task_summary(cp),
                updated_str,
            )

    def action_refresh(self) -> None:
        self._refresh_table()


def run_monitor(config=None) -> None:
    app = PipelineMonitor()
    app.run()
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/test_tui_checkpoint.py -v
```
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add agentharness/tui.py tests/test_tui_checkpoint.py
git commit -m "refactor: rewrite tui.py to read checkpoint files directly, remove all storage backend dependencies"
```

---

## Task 8: Simplify brainstorm.py

**Files:**
- Modify: `agentharness/brainstorm.py`

Keep only `start_brainstorm()` and `run_brainstorm_session()`. Remove `upload_brief_file`, `enqueue_planner`, `_convert_raw_issue`, and all GitHub/storage imports.

- [ ] **Step 1: Write failing test**

```python
# tests/test_brainstorm_simple.py
from unittest.mock import patch, MagicMock
from pathlib import Path
from agentharness.brainstorm import start_brainstorm, run_brainstorm_session

def test_start_brainstorm_calls_execvp(tmp_path):
    agent_path = tmp_path / ".agents" / "brainstorm.md"
    agent_path.parent.mkdir(parents=True)
    agent_path.write_text("---\nid: brainstorm\nmodel: claude-sonnet-4-6\nphase: brainstorming\nmax_turns: 50\nallowed_tools: []\n---\nYou are a brainstorm agent.")
    with patch("os.execvp") as mock_exec:
        with patch("pathlib.Path.cwd", return_value=tmp_path):
            try:
                start_brainstorm(config=None)
            except Exception:
                pass
        # execvp should have been called (or start_brainstorm found the agent)
```

- [ ] **Step 2: Rewrite agentharness/brainstorm.py**

```python
"""Interactive brainstorm session — the human-in-the-loop entry point."""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)

_BRAINSTORM_AGENT = Path(".agents/brainstorm.md")


def run_brainstorm_session(work_dir: Path, agent_path: Path) -> None:
    """Launch claude interactively with the brainstorm agent prompt.

    Uses os.execvp so the claude process inherits the terminal directly.
    """
    from agentharness.context_files import format_context_section, resolve_context_files
    from agentharness.prompt_builder import load_agent_definition

    agent_def = load_agent_definition(agent_path)
    project_root = agent_path.parent.parent

    system_prompt = agent_def.system_prompt
    if agent_def.context_files:
        resolved = resolve_context_files(agent_def.context_files, project_root)
        if resolved:
            system_prompt = format_context_section(resolved) + "\n\n" + system_prompt

    cmd = [
        "claude",
        "--system-prompt", system_prompt,
        "--model", agent_def.model,
    ]
    if agent_def.max_turns:
        cmd += ["--max-turns", str(agent_def.max_turns)]

    os.execvp("claude", cmd)


def start_brainstorm(config=None) -> None:
    """Start an interactive brainstorm session."""
    agent_path = _BRAINSTORM_AGENT
    if not agent_path.exists():
        raise FileNotFoundError(
            f"Brainstorm agent not found at {agent_path}. "
            "Run 'agentharness init' first."
        )
    with tempfile.TemporaryDirectory() as tmpdir:
        run_brainstorm_session(Path(tmpdir), agent_path)
```

- [ ] **Step 3: Run test**

```bash
.venv/bin/pytest tests/test_brainstorm_simple.py -v
```
Expected: PASS (or skip if execvp path is tricky to mock — the key is no import errors)

- [ ] **Step 4: Commit**

```bash
git add agentharness/brainstorm.py tests/test_brainstorm_simple.py
git commit -m "refactor: simplify brainstorm.py — remove upload/queue code, keep only start_brainstorm and run_brainstorm_session"
```

---

## Task 9: Remove observer commands and update status/list in cli.py

**Files:**
- Modify: `agentharness/cli.py`

Remove: `observe`, `_observe`, `run-task`, `submit`, `convert`, `logs` commands and all related imports.
Update: `status` and `list` to read checkpoints; `brainstorm` to not pass config.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_cli_new.py
import json
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/test_cli_new.py -v
```
Expected: FAIL — `status`/`list` still use storage backends, `observe` still exists.

- [ ] **Step 3: Rewrite cli.py**

Replace the entire file with the trimmed version below. Keep only: `brainstorm`, `init`, `watch`, `status`, `list`, `checkpoint` commands.

```python
"""Click CLI entry points for AgentHarness."""

from __future__ import annotations

import json as _json
import os
import re
import subprocess
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table
from rich import box

from agentharness.config import load_config
from agentharness.checkpoint import (
    init_checkpoint as _cp_init,
    load_checkpoint,
    update_phase as _cp_phase,
    update_task as _cp_task,
    set_tasks as _cp_set_tasks,
    query_next as _cp_query,
    list_checkpoints,
)

console = Console()


def _base_dir() -> Path:
    env = os.environ.get("AGENTHARNESS_BASE_DIR")
    return Path(env) if env else Path(".")


def _run_cmd(cmd: list[str], cwd: Path | None = None) -> str | None:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=5, cwd=cwd)
        return r.stdout.strip() if r.returncode == 0 else None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def _gh_login_if_needed() -> str | None:
    token = _run_cmd(["gh", "auth", "token"])
    if token:
        return token
    gh_available = _run_cmd(["gh", "--version"]) is not None
    if not gh_available:
        return None
    console.print("[yellow]gh CLI is installed but not authenticated.[/yellow]")
    if click.confirm("Run gh auth login now?", default=True):
        subprocess.run(["gh", "auth", "login"], check=False)
        return _run_cmd(["gh", "auth", "token"])
    return None


def _detect_github_env(target: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    token = _gh_login_if_needed()
    if token:
        values["GITHUB_TOKEN"] = token
    remote_url = _run_cmd(["git", "remote", "get-url", "origin"], cwd=target)
    if remote_url:
        m = re.search(r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?$", remote_url)
        if m:
            values["GITHUB_OWNER"] = m.group(1)
            values["GITHUB_RUNS_REPO"] = m.group(2)
    return values


def _read_env_file(env_file: Path) -> dict[str, str]:
    existing: dict[str, str] = {}
    if not env_file.exists():
        return existing
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            existing[k.strip()] = v.strip()
    return existing


def _write_env(target: Path, force: bool) -> None:
    env_file = target / ".env"
    existing = _read_env_file(env_file)
    detected = _detect_github_env(target)
    KEYS = ["GITHUB_TOKEN", "GITHUB_OWNER", "GITHUB_RUNS_REPO"]
    missing = [k for k in KEYS if k not in existing]
    if not missing and not force:
        console.print("[dim]skip[/dim] .env (all values already present)")
        return
    keys_to_set = KEYS if force else missing
    console.print(f"\n[bold]Environment setup[/bold] ({'updating' if existing else 'creating'} .env)")
    new_values: dict[str, str] = {}
    for key in keys_to_set:
        if key in detected:
            new_values[key] = detected[key]
            display = detected[key][:8] + "…" if key == "GITHUB_TOKEN" else detected[key]
            console.print(f"  [dim]auto-detected[/dim] {key}={display}")
        else:
            value = click.prompt(key, default="", hide_input=key == "GITHUB_TOKEN", show_default=False, prompt_suffix=": ")
            new_values[key] = value
    raw = ""
    if env_file.exists():
        raw_lines = env_file.read_text().splitlines(keepends=True)
        harness_start = next(
            (i for i, l in enumerate(raw_lines) if l.strip() == "# Generated by agentharness init"),
            None,
        )
        raw = "".join(raw_lines[:harness_start] if harness_start is not None else raw_lines)
    all_harness = {**{k: existing[k] for k in KEYS if k in existing}, **new_values}
    harness_section = "# Generated by agentharness init\n" + "".join(
        f"{k}={v}\n" for k, v in all_harness.items() if v
    )
    separator = "\n" if raw and not raw.endswith("\n\n") else ""
    env_file.write_text(raw + separator + harness_section)
    action = "updated" if existing else "wrote"
    console.print(f"[green]{action}[/green] .env")


@click.group()
@click.option("--config", "config_path", default=None, type=click.Path(), help="Path to config.json")
@click.pass_context
def main(ctx: click.Context, config_path: str | None) -> None:
    """AgentHarness — autonomous agentic development pipeline."""
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = Path(config_path) if config_path else None


@main.command()
@click.pass_context
def brainstorm(ctx: click.Context) -> None:
    """Start an interactive brainstorm session to define a feature brief."""
    from agentharness.brainstorm import start_brainstorm
    start_brainstorm()


@main.command("init")
@click.option("--dir", "target_dir", default=".", show_default=True, type=click.Path())
@click.option("--force", is_flag=True, help="Overwrite existing files")
@click.pass_context
def init_project(ctx: click.Context, target_dir: str, force: bool) -> None:
    """Copy agent definitions and pipeline config into a project directory."""
    import shutil
    data_root = Path(__file__).parent / "data"
    target = Path(target_dir).resolve()

    if not data_root.exists():
        console.print("[red]Data files not found in package — reinstall agentharness.[/red]")
        sys.exit(1)

    flat_destinations = [
        (data_root / "agents", target / ".agents"),
        (data_root / "pipeline", target / ".pipeline"),
    ]
    for src, dst in flat_destinations:
        if not src.exists():
            continue
        dst.mkdir(parents=True, exist_ok=True)
        for src_file in src.iterdir():
            dst_file = dst / src_file.name
            if dst_file.exists() and not force:
                console.print(f"[dim]skip[/dim] {dst_file.relative_to(target)}")
                continue
            shutil.copy2(src_file, dst_file)
            console.print(f"[green]wrote[/green] {dst_file.relative_to(target)}")

    # Install Claude Code skills to .claude/agents/
    claude_agents_src = data_root / "claude-agents"
    if claude_agents_src.exists():
        dst_claude_agents = target / ".claude" / "agents"
        dst_claude_agents.mkdir(parents=True, exist_ok=True)
        for src_file in claude_agents_src.iterdir():
            dst_file = dst_claude_agents / src_file.name
            if dst_file.exists() and not force:
                console.print(f"[dim]skip[/dim] {dst_file.relative_to(target)}")
                continue
            shutil.copy2(src_file, dst_file)
            console.print(f"[green]wrote[/green] {dst_file.relative_to(target)}")

    skills_src = data_root / "skills"
    if skills_src.exists():
        for skill_dir in skills_src.iterdir():
            if not skill_dir.is_dir():
                continue
            dst_skill = target / ".claude" / "skills" / skill_dir.name
            dst_skill.mkdir(parents=True, exist_ok=True)
            for src_file in skill_dir.iterdir():
                dst_file = dst_skill / src_file.name
                if dst_file.exists() and not force:
                    console.print(f"[dim]skip[/dim] {dst_file.relative_to(target)}")
                    continue
                shutil.copy2(src_file, dst_file)
                console.print(f"[green]wrote[/green] {dst_file.relative_to(target)}")

    _write_env(target, force)
    console.print("\n[bold]Done.[/bold] Run [bold]/implement <issue-number>[/bold] in Claude Code to start the pipeline.")


@main.command()
@click.pass_context
def watch(ctx: click.Context) -> None:
    """Open real-time TUI monitoring all pipeline features."""
    from agentharness.tui import run_monitor
    run_monitor()


@main.command()
@click.argument("feature_id")
def status(feature_id: str) -> None:
    """Show the current status of a feature."""
    base = _base_dir()
    try:
        cp = load_checkpoint(feature_id, base_dir=base)
    except (FileNotFoundError, ValueError):
        console.print(f"[red]Feature not found:[/red] {feature_id}")
        sys.exit(1)

    console.print(f"\n[bold]Feature:[/bold] {cp.feature_id}")
    console.print(f"[bold]Issue:[/bold]   #{cp.issue_number}")
    console.print(f"[bold]Created:[/bold] {cp.created_at.strftime('%Y-%m-%d %H:%M:%S UTC')}")

    console.print("\n[bold]Phases:[/bold]")
    for phase, info in cp.phases.items():
        icon = {"completed": "[green]✓[/green]", "in_progress": "[yellow]▶[/yellow]",
                "pending": "[dim]○[/dim]", "failed": "[red]✗[/red]"}.get(info.status, "?")
        ts = f"  [dim]{info.updated_at.strftime('%H:%M:%S')}[/dim]" if info.updated_at else ""
        console.print(f"  {icon} {phase:<14} {info.status}{ts}")

    if cp.tasks:
        console.print("\n[bold]Tasks:[/bold]")
        table = Table(box=box.SIMPLE, show_header=True, header_style="bold")
        table.add_column("Task", style="cyan")
        table.add_column("Status")
        table.add_column("Rev")
        for t in cp.tasks:
            style = {"completed": "[green]", "failed": "[red]", "in_progress": "[yellow]"}.get(t.status, "[dim]")
            table.add_row(t.name, f"{style}{t.status}[/]", str(t.revision))
        console.print(table)


@main.command("list")
def list_features() -> None:
    """List all features in the pipeline."""
    checkpoints = list_checkpoints(base_dir=_base_dir())
    if not checkpoints:
        console.print("[dim]No features found.[/dim]")
        return
    table = Table(box=box.SIMPLE, show_header=True, header_style="bold")
    table.add_column("Feature", style="cyan")
    table.add_column("Issue")
    table.add_column("Phases")
    table.add_column("Tasks")
    table.add_column("Created")
    for cp in checkpoints:
        completed_phases = sum(1 for p in cp.phases.values() if p.status == "completed")
        completed_tasks = sum(1 for t in cp.tasks if t.status == "completed")
        table.add_row(
            cp.feature_id,
            f"#{cp.issue_number}",
            f"{completed_phases}/{len(cp.phases)}",
            f"{completed_tasks}/{len(cp.tasks)}" if cp.tasks else "—",
            cp.created_at.strftime("%Y-%m-%d %H:%M"),
        )
    console.print(table)


# Checkpoint subcommands

@main.group("checkpoint")
def checkpoint_group() -> None:
    """Manage pipeline checkpoint state."""


@checkpoint_group.command("init")
@click.argument("issue_number", type=int)
def checkpoint_init(issue_number: int) -> None:
    """Create state.json for issue (idempotent)."""
    _cp_init(issue_number, base_dir=_base_dir())
    console.print(f"[green]checkpoint init:[/green] feat-{issue_number}")


@checkpoint_group.command("phase")
@click.argument("feature_id")
@click.argument("phase")
@click.argument("status")
def checkpoint_phase(feature_id: str, phase: str, status: str) -> None:
    """Update a phase status in the checkpoint."""
    _cp_phase(feature_id, phase, status, base_dir=_base_dir())


@checkpoint_group.command("task")
@click.argument("feature_id")
@click.argument("task_name")
@click.argument("status")
@click.option("--revision", type=int, default=None)
def checkpoint_task(feature_id: str, task_name: str, status: str, revision: int | None) -> None:
    """Update a task status in the checkpoint."""
    _cp_task(feature_id, task_name, status, revision=revision, base_dir=_base_dir())


@checkpoint_group.command("tasks")
@click.argument("feature_id")
@click.argument("task_names")
def checkpoint_tasks(feature_id: str, task_names: str) -> None:
    """Populate task list (comma-separated names) after planning."""
    names = [n.strip() for n in task_names.split(",") if n.strip()]
    _cp_set_tasks(feature_id, names, base_dir=_base_dir())


@checkpoint_group.command("status")
@click.argument("feature_id")
def checkpoint_status(feature_id: str) -> None:
    """Print next pending phase or task as JSON."""
    result = _cp_query(feature_id, base_dir=_base_dir())
    click.echo(_json.dumps(result))
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/test_cli_new.py tests/test_cli_init.py -v
```
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add agentharness/cli.py tests/test_cli_new.py
git commit -m "refactor: trim cli.py — remove observer/queue commands, update status/list to read checkpoints"
```

---

## Task 10: Delete removed modules and their tests

**Files:** All modules being deleted and their test files.

- [ ] **Step 1: Delete Python modules**

```bash
rm agentharness/observer.py
rm agentharness/run_task.py
rm agentharness/worker.py
rm agentharness/agent_runner.py
rm agentharness/storage_protocol.py
rm agentharness/storage.py
rm agentharness/state_manager.py
rm agentharness/state_change.py
rm agentharness/auto_mode.py
rm agentharness/dispatcher.py
rm agentharness/azure_artifacts.py
rm agentharness/azure_queue.py
rm agentharness/azure_state.py
rm agentharness/github_queue.py
rm agentharness/github_artifacts.py
rm agentharness/github_state.py
rm agentharness/github_client.py
rm agentharness/github_labels.py
rm agentharness/worktree_manager.py
rm agentharness/tui_state_change.py
```

- [ ] **Step 2: Delete corresponding test files**

```bash
rm tests/test_agent_runner_build_command.py
rm tests/test_agent_runner_cwd.py
rm tests/test_agent_runner_parse.py
rm tests/test_auto_mode.py
rm tests/test_backend_parity.py
rm tests/test_brainstorm_epic.py
rm tests/test_brainstorm_github.py
rm tests/test_brainstorm_pipeline_config.py
rm tests/test_cli_convert.py
rm tests/test_cli_epic_gating.py
rm tests/test_config.py
rm tests/test_dispatcher.py
rm tests/test_dispatcher_github.py
rm tests/test_dispatcher_worktree.py
rm tests/test_epic_dispatch.py
rm tests/test_github_artifacts.py
rm tests/test_github_client.py
rm tests/test_github_client_retry.py
rm tests/test_github_labels.py
rm tests/test_github_queue.py
rm tests/test_github_state.py
rm tests/test_models.py
rm tests/test_observer_auto_mode.py
rm tests/test_observer_concurrency.py
rm tests/test_observer_epic.py
rm tests/test_observer_sweeper.py
rm tests/test_run_task.py
rm tests/test_state_change.py
rm tests/test_state_manager.py
rm tests/test_state_manager_worktree.py
rm tests/test_storage_factory.py
rm tests/test_tui_copy_name.py
rm tests/test_tui_refresh_resilience.py
rm tests/test_tui_state_change.py
rm tests/test_worktree_manager.py
```

- [ ] **Step 3: Run full test suite — expect clean pass**

```bash
.venv/bin/pytest tests/ -v
```
Expected: All remaining tests PASS. If any test imports a deleted module, fix the import.

- [ ] **Step 4: Update pyproject.toml to remove unused dependencies**

Remove from `dependencies` in `pyproject.toml`:
- `azure-storage-blob`
- `azure-storage-queue`
- `aiohttp`
- `httpx[http2]`

Keep: `pydantic`, `pyyaml`, `click`, `rich`, `textual`, `python-dotenv`

- [ ] **Step 5: Reinstall and verify imports**

```bash
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -c "import agentharness.cli; import agentharness.checkpoint; import agentharness.tui; print('OK')"
```
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "chore: delete observer/queue/backend modules and their tests; remove unused dependencies"
```

---

## Task 11: End-to-end verification

- [ ] **Step 1: Run full test suite**

```bash
.venv/bin/pytest tests/ -v --tb=short
```
Expected: All PASS, no import errors.

- [ ] **Step 2: Verify checkpoint CLI smoke test**

```bash
agentharness checkpoint init 999
agentharness checkpoint status feat-999
# Expected: {"type": "phase", "name": "analyzing"}
agentharness checkpoint phase feat-999 analyzing completed
agentharness checkpoint status feat-999
# Expected: {"type": "phase", "name": "architecting"}
```

- [ ] **Step 3: Verify agentharness init installs implement skill**

```bash
mkdir /tmp/test-init && agentharness init --dir /tmp/test-init
ls /tmp/test-init/.claude/agents/implement.md
# Expected: file exists
```

- [ ] **Step 4: Verify TUI launches without errors**

```bash
timeout 3 agentharness watch || true
# Expected: Textual app launches and exits cleanly (or timeout)
```

- [ ] **Step 5: Verify status/list work on a real checkpoint**

```bash
agentharness checkpoint init 42
agentharness status feat-42
agentharness list
```
Expected: both commands display checkpoint data.

- [ ] **Step 6: Final commit**

```bash
git add -A
git commit -m "chore: verify end-to-end checkpoint workflow and clean up remaining references"
```
