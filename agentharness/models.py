"""Pydantic models for AgentHarness pipeline."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class FeatureStatus(str, Enum):
    brainstorming = "brainstorming"
    brainstormed = "brainstormed"
    analyzing = "analyzing"
    questioning = "questioning"
    architecting = "architecting"
    designing = "designing"
    planning = "planning"
    developing = "developing"
    reviewing = "reviewing"
    dev_revision = "dev_revision"
    done = "done"
    failed = "failed"


class TaskStatus(str, Enum):
    pending = "pending"
    queued = "queued"
    in_progress = "in_progress"
    completed = "completed"
    failed = "failed"


class PhaseStatus(str, Enum):
    pending = "pending"
    in_progress = "in_progress"
    completed = "completed"
    failed = "failed"


class TokenUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens + self.cache_creation_tokens + self.cache_read_tokens

    def __add__(self, other: "TokenUsage") -> "TokenUsage":
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_creation_tokens=self.cache_creation_tokens + other.cache_creation_tokens,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
        )


class PhaseInfo(BaseModel):
    status: PhaseStatus = PhaseStatus.pending
    started_at: datetime | None = None
    completed_at: datetime | None = None
    agent: str | None = None
    revision: int = 1
    tokens_used: TokenUsage | None = None
    pid: int | None = None


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
    log_file: str | None = None
    queued_message: dict | None = None
    pid: int | None = None
    tokens_used: TokenUsage | None = None


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
    max_analyst_iterations: int = Field(default=2, ge=0)
    current_analyst_iteration: int = Field(default=0, ge=0)


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
    worktree_path: str | None = None
    branch_name: str | None = None
    cleanup_warning: str | None = None
    state_issue_number: int | None = None
    pr_number: int | None = None
    pr_url: str | None = None
    epic_parent: int | None = None
    epic_position: int | None = None
    epic_branch: str | None = None
    epic_total: int | None = None

    def with_event(self, event: str, **kwargs: Any) -> FeatureState:
        """Return new state with appended history event (immutable update)."""
        new_history = [*self.history, HistoryEvent(event=event, **kwargs)]
        return self.model_copy(update={"history": new_history, "updated_at": datetime.now(UTC)})

    def with_status(self, status: FeatureStatus) -> FeatureState:
        """Return new state with updated feature status."""
        return self.model_copy(update={"status": status, "updated_at": datetime.now(UTC)})

    def with_analyst_iteration_incremented(self) -> FeatureState:
        """Return new state with config.current_analyst_iteration += 1."""
        new_config = self.config.model_copy(
            update={"current_analyst_iteration": self.config.current_analyst_iteration + 1}
        )
        return self.model_copy(update={"config": new_config, "updated_at": datetime.now(UTC)})

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

    def with_pr(self, number: int, url: str) -> FeatureState:
        """Return new state with pr_number and pr_url set."""
        return self.model_copy(update={"pr_number": number, "pr_url": url, "updated_at": datetime.now(UTC)})

    def with_worktree_path(self, path: str) -> FeatureState:
        """Return new state with worktree_path set. Raises if already set to a different value."""
        if self.worktree_path is not None and self.worktree_path != path:
            raise ValueError(
                f"worktree_path is already set to {self.worktree_path!r}; "
                f"cannot overwrite with {path!r} (immutability invariant)"
            )
        return self.model_copy(update={"worktree_path": path, "updated_at": datetime.now(UTC)})

    def with_branch_name(self, branch_name: str) -> FeatureState:
        """Return new state with branch_name set."""
        return self.model_copy(update={"branch_name": branch_name, "updated_at": datetime.now(UTC)})

    def with_cleanup_warning(self, message: str) -> FeatureState:
        """Return new state with cleanup_warning set."""
        return self.model_copy(update={"cleanup_warning": message, "updated_at": datetime.now(UTC)})

    def with_tasks_added(self, new_tasks: list[TaskEntry]) -> FeatureState:
        """Return new state with additional tasks appended."""
        return self.model_copy(
            update={"tasks": [*self.tasks, *new_tasks], "updated_at": datetime.now(UTC)}
        )

    def with_tasks_cleared(self) -> FeatureState:
        """Return new state with tasks=[] (immutable copy). Used by manual rollback."""
        return self.model_copy(update={"tasks": [], "updated_at": datetime.now(UTC)})

    def total_tokens_used(self) -> TokenUsage:
        result = TokenUsage()
        for phase_info in self.phases.values():
            if phase_info.tokens_used:
                result = result + phase_info.tokens_used
        for task in self.tasks:
            if task.tokens_used:
                result = result + task.tokens_used
        return result

    @property
    def is_raw(self) -> bool:
        """True when this state was synthesised from a labelled issue with no state block.

        A raw feature has no recorded history events; the canonical signal is the
        absence of the ``brief_uploaded`` event that ``upload_brief`` emits. Only
        meaningful for ``FeatureState`` objects produced by ``list_features()`` or
        synthesised locally; do not trust after a write round-trip via ``get()``.
        """
        return not self.history

    def tasks_for_phase(self, phase: str) -> list[TaskEntry]:
        return [t for t in self.tasks if t.phase == phase]

    def next_pending_task(self, phase: str) -> TaskEntry | None:
        """Return the first pending task for a phase, or None."""
        return next(
            (t for t in self.tasks if t.phase == phase and t.status == TaskStatus.pending),
            None,
        )

    def all_tasks_complete(self, phase: str) -> bool:
        phase_tasks = self.tasks_for_phase(phase)
        terminal = {TaskStatus.completed, TaskStatus.failed}
        return bool(phase_tasks) and all(t.status in terminal for t in phase_tasks)


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
    state_issue_number: int | None = None


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
    system_prompt: str
