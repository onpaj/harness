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
    "create_artifact_store",
    "create_task_queue",
    "create_state_manager",
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


def create_artifact_store(config, feature_id: str | None = None):
    """Return ArtifactStorage backend based on config.storage_backend."""
    if config.storage_backend == "github":
        from agentharness.github_artifacts import GitHubArtifactStore
        if feature_id is None:
            raise ValueError("feature_id is required for GitHub artifact store")
        return GitHubArtifactStore.from_config(config, feature_id)
    from azure.storage.blob.aio import BlobServiceClient
    client = BlobServiceClient.from_connection_string(config.storage.connection_string)
    return AzureArtifactStore(client, config.storage.container)


def create_task_queue(config, queue_name: str):
    """Return TaskQueue backend for a single queue based on config.storage_backend."""
    if config.storage_backend == "github":
        from agentharness.github_queue import GitHubTaskQueue
        return GitHubTaskQueue.from_config(config, queue_name)
    return AzureTaskQueue.from_connection_string(config.storage.connection_string, queue_name)


def create_state_manager(config):
    """Return StateBackend based on config.storage_backend."""
    if config.storage_backend == "github":
        from agentharness.github_state import GitHubStateManager
        return GitHubStateManager.from_config(config)
    from agentharness.state_manager import AzureStateManager
    return AzureStateManager.from_config(config)
