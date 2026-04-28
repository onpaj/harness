"""Parity tests — both backends implement the Protocols correctly."""

from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentharness.azure_artifacts import AzureArtifactStore
from agentharness.azure_queue import AzureTaskQueue
from agentharness.github_artifacts import GitHubArtifactStore
from agentharness.github_queue import GitHubTaskQueue
from agentharness.github_state import GitHubStateManager
from agentharness.models import FeatureState
from agentharness.state_manager import AzureStateManager
from agentharness.storage_protocol import ArtifactStorage, StateBackend, TaskQueue


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _protocol_methods(protocol_cls) -> list[str]:
    """Return the list of non-dunder method names declared on a Protocol."""
    return [
        name
        for name, member in inspect.getmembers(protocol_cls)
        if not name.startswith("_") and callable(member)
    ]


# ---------------------------------------------------------------------------
# Protocol method presence
# ---------------------------------------------------------------------------


class TestProtocolMethodPresence:
    def test_azure_artifact_store_has_all_artifact_storage_methods(self):
        for method in _protocol_methods(ArtifactStorage):
            assert hasattr(AzureArtifactStore, method), (
                f"AzureArtifactStore is missing Protocol method: {method!r}"
            )

    def test_github_artifact_store_has_all_artifact_storage_methods(self):
        for method in _protocol_methods(ArtifactStorage):
            assert hasattr(GitHubArtifactStore, method), (
                f"GitHubArtifactStore is missing Protocol method: {method!r}"
            )

    def test_azure_task_queue_has_all_task_queue_methods(self):
        for method in _protocol_methods(TaskQueue):
            assert hasattr(AzureTaskQueue, method), (
                f"AzureTaskQueue is missing Protocol method: {method!r}"
            )

    def test_github_task_queue_has_all_task_queue_methods(self):
        for method in _protocol_methods(TaskQueue):
            assert hasattr(GitHubTaskQueue, method), (
                f"GitHubTaskQueue is missing Protocol method: {method!r}"
            )

    def test_azure_state_manager_has_all_state_backend_methods(self):
        for method in _protocol_methods(StateBackend):
            assert hasattr(AzureStateManager, method), (
                f"AzureStateManager is missing Protocol method: {method!r}"
            )

    def test_github_state_manager_has_all_state_backend_methods(self):
        for method in _protocol_methods(StateBackend):
            assert hasattr(GitHubStateManager, method), (
                f"GitHubStateManager is missing Protocol method: {method!r}"
            )


# ---------------------------------------------------------------------------
# No-op contracts for Azure
# ---------------------------------------------------------------------------


class TestAzureNoOpContracts:
    def test_azure_artifact_store_get_work_dir_returns_none(self):
        # Arrange
        mock_service = MagicMock()
        store = AzureArtifactStore(blob_service=mock_service, container="test-container")

        # Act
        result = store.get_work_dir()

        # Assert
        assert result is None

    @pytest.mark.asyncio
    async def test_azure_state_manager_open_review_returns_none(self):
        # Arrange
        mock_service = MagicMock()
        mgr = AzureStateManager(blob_service=mock_service, container="test-container")

        # Act
        result = await mgr.open_review("feat-abc")

        # Assert
        assert result is None

    def test_move_to_dead_letter_azure_has_no_connection_string_param(self):
        sig = inspect.signature(AzureTaskQueue.move_to_dead_letter)
        assert "connection_string" not in sig.parameters

    def test_move_to_dead_letter_github_has_no_connection_string_param(self):
        sig = inspect.signature(GitHubTaskQueue.move_to_dead_letter)
        assert "connection_string" not in sig.parameters


# ---------------------------------------------------------------------------
# Signature alignment
# ---------------------------------------------------------------------------


class TestSignatureAlignment:
    def test_state_backend_create_has_brief_content_param(self):
        sig = inspect.signature(StateBackend.create)
        assert "brief_content" in sig.parameters

    def test_azure_state_manager_create_has_brief_content_param(self):
        sig = inspect.signature(AzureStateManager.create)
        assert "brief_content" in sig.parameters

    def test_github_state_manager_create_has_brief_content_param(self):
        sig = inspect.signature(GitHubStateManager.create)
        assert "brief_content" in sig.parameters

    def test_state_backend_list_features_return_annotation_is_list_of_feature_state(self):
        hints = inspect.get_annotations(StateBackend.list_features, eval_str=True)
        return_hint = hints.get("return")
        assert return_hint == list[FeatureState], (
            f"Expected list[FeatureState], got {return_hint!r}"
        )

    def test_artifact_storage_get_work_dir_is_not_a_coroutine(self):
        assert not inspect.iscoroutinefunction(ArtifactStorage.get_work_dir), (
            "ArtifactStorage.get_work_dir must be a sync method, not a coroutine"
        )

    def test_azure_artifact_store_get_work_dir_is_not_a_coroutine(self):
        assert not inspect.iscoroutinefunction(AzureArtifactStore.get_work_dir)

    def test_github_artifact_store_get_work_dir_is_not_a_coroutine(self):
        assert not inspect.iscoroutinefunction(GitHubArtifactStore.get_work_dir)

    def test_artifact_storage_commit_workdir_changes_is_a_coroutine(self):
        assert inspect.iscoroutinefunction(ArtifactStorage.commit_workdir_changes), (
            "ArtifactStorage.commit_workdir_changes must be async"
        )

    def test_azure_artifact_store_commit_workdir_changes_is_a_coroutine(self):
        assert inspect.iscoroutinefunction(AzureArtifactStore.commit_workdir_changes)

    def test_github_artifact_store_commit_workdir_changes_is_a_coroutine(self):
        assert inspect.iscoroutinefunction(GitHubArtifactStore.commit_workdir_changes)
