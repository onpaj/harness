"""Pydantic models for AgentHarness checkpoint and agent definitions."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field

# Phases that next_pending_phase() considers — "developing" is intentionally
# omitted so the orchestrator falls through to task-level dispatch once planning
# is complete. "developing" is stored in the phases dict for display only.
_PIPELINE_PHASES = ["analyzing", "architecting", "designing", "planning"]
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
