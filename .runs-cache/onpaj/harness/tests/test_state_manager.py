"""Unit tests for StateManager — mocked Azure blob operations."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentharness.models import FeatureState, FeatureStatus
from agentharness.state_manager import StateManager


def _make_state(feature_id: str = "feat-test") -> FeatureState:
    return FeatureState(feature_id=feature_id)


def _serialize(state: FeatureState) -> bytes:
    return state.model_dump_json().encode()


class TestStateManagerGet:
    async def test_get_returns_state(self):
        state = _make_state()
        blob_mock = AsyncMock()
        stream_mock = AsyncMock()
        stream_mock.readall.return_value = _serialize(state)
        blob_mock.download_blob.return_value = stream_mock

        service_mock = MagicMock()
        service_mock.get_container_client.return_value.get_blob_client.return_value = blob_mock

        mgr = StateManager(service_mock, "pipeline-artifacts")
        result = await mgr.get("feat-test")

        assert result.feature_id == "feat-test"

    async def test_get_raises_key_error_when_not_found(self):
        from azure.core.exceptions import ResourceNotFoundError

        blob_mock = AsyncMock()
        blob_mock.download_blob.side_effect = ResourceNotFoundError("not found")

        service_mock = MagicMock()
        service_mock.get_container_client.return_value.get_blob_client.return_value = blob_mock

        mgr = StateManager(service_mock, "pipeline-artifacts")
        with pytest.raises(KeyError, match="feat-missing"):
            await mgr.get("feat-missing")


class TestStateManagerCreate:
    async def test_create_uploads_state(self):
        state = _make_state()
        blob_mock = AsyncMock()

        service_mock = MagicMock()
        service_mock.get_container_client.return_value.get_blob_client.return_value = blob_mock

        mgr = StateManager(service_mock, "pipeline-artifacts")
        await mgr.create(state)

        blob_mock.upload_blob.assert_called_once()
        call_kwargs = blob_mock.upload_blob.call_args[1]
        assert call_kwargs.get("overwrite") is False


class TestStateManagerUpdate:
    async def test_update_applies_transform(self):
        state = _make_state()
        blob_mock = AsyncMock()
        lease_mock = AsyncMock()
        blob_mock.acquire_lease.return_value = lease_mock

        stream_mock = AsyncMock()
        stream_mock.readall.return_value = _serialize(state)
        blob_mock.download_blob.return_value = stream_mock

        service_mock = MagicMock()
        service_mock.get_container_client.return_value.get_blob_client.return_value = blob_mock

        mgr = StateManager(service_mock, "pipeline-artifacts")
        result = await mgr.update(
            "feat-test",
            lambda s: s.with_status(FeatureStatus.done),
        )

        assert result.status == FeatureStatus.done
        blob_mock.upload_blob.assert_called_once()
        lease_mock.release.assert_called_once()

    async def test_update_releases_lease_on_error(self):
        """Non-lease errors propagate immediately and the lease is still released."""
        blob_mock = AsyncMock()
        lease_mock = AsyncMock()
        blob_mock.acquire_lease.return_value = lease_mock
        blob_mock.download_blob.side_effect = RuntimeError("unexpected storage error")

        service_mock = MagicMock()
        service_mock.get_container_client.return_value.get_blob_client.return_value = blob_mock

        mgr = StateManager(service_mock, "pipeline-artifacts")
        with pytest.raises(RuntimeError, match="unexpected storage error"):
            await mgr.update("feat-test", lambda s: s)

        lease_mock.release.assert_called()

    async def test_update_retries_on_lease_contention(self):
        """HttpResponseError with lease error code triggers retry."""
        from azure.core.exceptions import HttpResponseError

        state = _make_state()
        lease_mock = AsyncMock()
        stream_mock = AsyncMock()
        stream_mock.readall.return_value = _serialize(state)

        blob_mock = AsyncMock()
        # First acquire_lease raises lease contention, second succeeds
        contention = HttpResponseError(message="lease conflict")
        contention.error_code = "LeaseAlreadyPresent"
        blob_mock.acquire_lease.side_effect = [contention, lease_mock]
        blob_mock.download_blob.return_value = stream_mock

        service_mock = MagicMock()
        service_mock.get_container_client.return_value.get_blob_client.return_value = blob_mock

        mgr = StateManager(service_mock, "pipeline-artifacts")
        # Patch sleep to avoid real waiting
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("agentharness.state_manager.asyncio.sleep", AsyncMock())
            result = await mgr.update("feat-test", lambda s: s)

        assert result.feature_id == "feat-test"
        assert blob_mock.acquire_lease.call_count == 2
