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
            updates: dict[str, Any] = {"status": status, "updated_at": datetime.now(UTC)}
            if revision is not None:
                updates["revision"] = revision
            new_tasks.append(t.model_copy(update=updates))
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
