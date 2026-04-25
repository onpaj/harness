"""Pydantic models for AgentHarness pipeline."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class FeatureStatus(str, Enum):
    brainstorming = "brainstorming"
    planning = "planning"
    architecting = "architecting"
    designing = "designing"
    developing = "developing"
    reviewing = "reviewing"
    dev_revision = "dev_revision"
    done = "done"
    failed = "failed"


class TaskStatus(str, Enum):
    queued = "queued"
    in_progress = "in_progress"
    completed = "completed"
    failed = "failed"


class PhaseStatus(str, Enum):
    pending = "pending"
    in_progress = "in_progress"
    completed = "completed"
    failed = "failed"


class PhaseInfo(BaseModel):
    status: PhaseStatus = PhaseStatus.pending
    started_at: datetime | None = None
    completed_at: datetime | None = None
    agent: str | None = None
    revision: int = 1


class TaskEntry(BaseModel):
    task_id: str
    phase: str
    status: TaskStatus = TaskStatus.queued
    revision: int = 1
    worker_id: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    output_artifact: str | None = None
    review_feedback: str | None = None


class HistoryEvent(BaseModel):
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    event: str
    phase: str | None = None
    task_id: str | None = None
    worker_id: str | None = None
    details: str | None = None


class PipelineConfig(BaseModel):
    max_revisions: int = 3
    current_revision_round: int = 0


class FeatureState(BaseModel):
    feature_id: str
    status: FeatureStatus = FeatureStatus.planning
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    brief_submitted_by: str | None = None
    phases: dict[str, PhaseInfo] = Field(default_factory=dict)
    tasks: list[TaskEntry] = Field(default_factory=list)
    history: list[HistoryEvent] = Field(default_factory=list)
    config: PipelineConfig = Field(default_factory=PipelineConfig)

    def with_event(self, event: str, **kwargs: Any) -> FeatureState:
        """Return new state with appended history event (immutable update)."""
        new_history = [*self.history, HistoryEvent(event=event, **kwargs)]
        return self.model_copy(update={"history": new_history, "updated_at": datetime.now(UTC)})

    def with_status(self, status: FeatureStatus) -> FeatureState:
        """Return new state with updated feature status."""
        return self.model_copy(update={"status": status, "updated_at": datetime.now(UTC)})

    def with_phase(self, phase: str, info: PhaseInfo) -> FeatureState:
        """Return new state with updated phase info."""
        new_phases = {**self.phases, phase: info}
        return self.model_copy(update={"phases": new_phases, "updated_at": datetime.now(UTC)})

    def with_task_update(self, task_id: str, **fields: Any) -> FeatureState:
        """Return new state with updated task entry."""
        new_tasks = [
            t.model_copy(update={**fields, "updated_at": datetime.now(UTC)}) if t.task_id == task_id else t
            for t in self.tasks
        ]
        return self.model_copy(update={"tasks": new_tasks, "updated_at": datetime.now(UTC)})

    def with_tasks_added(self, new_tasks: list[TaskEntry]) -> FeatureState:
        """Return new state with additional tasks appended."""
        return self.model_copy(
            update={"tasks": [*self.tasks, *new_tasks], "updated_at": datetime.now(UTC)}
        )

    def tasks_for_phase(self, phase: str) -> list[TaskEntry]:
        return [t for t in self.tasks if t.phase == phase]

    def all_tasks_complete(self, phase: str) -> bool:
        phase_tasks = self.tasks_for_phase(phase)
        return bool(phase_tasks) and all(t.status == TaskStatus.completed for t in phase_tasks)


class TaskMessage(BaseModel):
    feature_id: str
    task_id: str
    input_artifacts: list[str]
    output_artifact: str
    agent_role: str
    context: str | None = None
    revision: int = 1
    review_feedback: str | None = None
    work_dir: str | None = None  # local filesystem path; None → temp dir


class AgentDefinition(BaseModel):
    id: str
    display_name: str = ""
    model: str
    phase: str
    max_turns: int = 20
    allowed_tools: list[str] = Field(default_factory=list)
    output_format: str = "markdown"
    visibility_timeout: int = 600
    retry_limit: int = 3
    output_parsing: str = "none"
    system_prompt: str
