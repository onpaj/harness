"""Artifact path helpers and backward-compatible re-exports."""

from __future__ import annotations

from agentharness.azure_artifacts import AzureArtifactStore
from agentharness.azure_queue import AzureTaskQueue
from agentharness.storage_protocol import RawMessage

# Backward-compatible aliases
ArtifactStore = AzureArtifactStore
PipelineQueue = AzureTaskQueue

__all__ = [
    "ArtifactStore",
    "PipelineQueue",
    "RawMessage",
    "AzureArtifactStore",
    "AzureTaskQueue",
    "artifact_path",
    "impl_artifact_path",
    "review_artifact_path",
    "task_review_artifact_path",
    "phase_artifact_path",
    "task_context_artifact_path",
    "state_blob_path",
]


def artifact_path(feature_id: str, name: str) -> str:
    return f"artifacts/{feature_id}/{name}"


def impl_artifact_path(feature_id: str, task_name: str, revision: int) -> str:
    return f"artifacts/{feature_id}/impl/{task_name}.r{revision}.md"


def review_artifact_path(feature_id: str, revision: int) -> str:
    return f"artifacts/{feature_id}/review/review.r{revision}.md"


def task_review_artifact_path(feature_id: str, task_name: str, revision: int) -> str:
    return f"artifacts/{feature_id}/review/{task_name}.r{revision}.md"


def phase_artifact_path(feature_id: str, phase_name: str, revision: int) -> str:
    return f"artifacts/{feature_id}/{phase_name}.r{revision}.md"


def task_context_artifact_path(feature_id: str, task_name: str) -> str:
    return f"artifacts/{feature_id}/task-context/{task_name}.md"


def state_blob_path(feature_id: str) -> str:
    return f"artifacts/{feature_id}/state.json"
