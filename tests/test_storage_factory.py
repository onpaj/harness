"""Unit tests for storage backend factory functions."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agentharness.azure_artifacts import AzureArtifactStore
from agentharness.azure_queue import AzureTaskQueue
from agentharness.config import Config
from agentharness.state_manager import StateManager
from agentharness.storage import create_artifact_store, create_state_manager, create_task_queue


_FAKE_CONN_STR = (
    "DefaultEndpointsProtocol=https;AccountName=fake;AccountKey="
    "ZmFrZWtleWZha2VrZXlmYWtla2V5ZmFrZWtleWZha2VrZXlmYWs=;EndpointSuffix=core.windows.net"
)


def _azure_config() -> Config:
    return Config.model_validate(
        {
            "storage_backend": "azure",
            "storage": {
                "connection_string_env": "FAKE_AZURE_CONN",
                "container": "test-container",
            },
        }
    )


def _github_config() -> Config:
    return Config.model_validate(
        {
            "storage_backend": "github",
            "github": {
                "token_env": "FAKE_GH_TOKEN",
                "owner_env": "FAKE_GH_OWNER",
                "runs_repo_env": "FAKE_GH_REPO",
                "clone_dir": ".runs-cache-test",
            },
        }
    )


@pytest.fixture
def fake_conn_str(monkeypatch):
    """Inject a fake Azure connection string env var."""
    monkeypatch.setenv("FAKE_AZURE_CONN", _FAKE_CONN_STR)


@pytest.fixture
def fake_blob_service_client():
    """Patch BlobServiceClient.from_connection_string to avoid real Azure calls."""
    mock_client = MagicMock()
    with patch(
        "azure.storage.blob.aio.BlobServiceClient.from_connection_string",
        return_value=mock_client,
    ) as patched:
        yield patched, mock_client


class TestCreateArtifactStore:
    def test_azure_config_returns_azure_artifact_store(self, fake_conn_str, fake_blob_service_client):
        # Arrange
        config = _azure_config()
        _, mock_client = fake_blob_service_client

        # Act
        store = create_artifact_store(config)

        # Assert
        assert isinstance(store, AzureArtifactStore)

    def test_github_config_with_feature_id_returns_github_artifact_store(self, monkeypatch):
        # Arrange
        monkeypatch.setenv("FAKE_GH_TOKEN", "gh-token")
        monkeypatch.setenv("FAKE_GH_OWNER", "test-owner")
        monkeypatch.setenv("FAKE_GH_REPO", "test-repo")
        config = _github_config()

        from agentharness.github_artifacts import GitHubArtifactStore

        with patch.object(GitHubArtifactStore, "from_config", return_value=MagicMock(spec=GitHubArtifactStore)) as mock_from_config:
            # Act
            store = create_artifact_store(config, feature_id="feat-x")

            # Assert
            mock_from_config.assert_called_once_with(config, "feat-x")
            assert isinstance(store, GitHubArtifactStore)

    def test_github_config_without_feature_id_raises_value_error(self):
        # Arrange
        config = _github_config()

        # Act / Assert
        with pytest.raises(ValueError, match="feature_id is required"):
            create_artifact_store(config)


class TestCreateTaskQueue:
    def test_azure_config_returns_azure_task_queue(self, fake_conn_str):
        # Arrange
        config = _azure_config()

        with patch(
            "azure.storage.queue.aio.QueueClient.from_connection_string",
            return_value=MagicMock(),
        ):
            # Act
            queue = create_task_queue(config, "analyst-queue")

        # Assert
        assert isinstance(queue, AzureTaskQueue)

    def test_github_config_returns_github_task_queue(self, monkeypatch):
        # Arrange
        monkeypatch.setenv("FAKE_GH_TOKEN", "gh-token")
        monkeypatch.setenv("FAKE_GH_OWNER", "test-owner")
        monkeypatch.setenv("FAKE_GH_REPO", "test-repo")
        config = _github_config()

        from agentharness.github_queue import GitHubTaskQueue

        with patch.object(GitHubTaskQueue, "from_config", return_value=MagicMock(spec=GitHubTaskQueue)) as mock_from_config:
            # Act
            queue = create_task_queue(config, "analyst-queue")

            # Assert
            mock_from_config.assert_called_once_with(config, "analyst-queue")
            assert isinstance(queue, GitHubTaskQueue)


class TestCreateStateManager:
    def test_azure_config_returns_state_manager(self, fake_conn_str, fake_blob_service_client):
        # Arrange
        config = _azure_config()

        # Act
        mgr = create_state_manager(config)

        # Assert
        assert isinstance(mgr, StateManager)

    def test_github_config_returns_github_state_manager(self, monkeypatch):
        # Arrange
        monkeypatch.setenv("FAKE_GH_TOKEN", "gh-token")
        monkeypatch.setenv("FAKE_GH_OWNER", "test-owner")
        monkeypatch.setenv("FAKE_GH_REPO", "test-repo")
        config = _github_config()

        from agentharness.github_state import GitHubStateManager

        with patch.object(GitHubStateManager, "from_config", return_value=MagicMock(spec=GitHubStateManager)) as mock_from_config:
            # Act
            mgr = create_state_manager(config)

            # Assert
            mock_from_config.assert_called_once_with(config)
            assert isinstance(mgr, GitHubStateManager)
