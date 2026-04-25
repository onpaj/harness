"""Tests for StateManager worktree helpers: set_worktree_path, set_cleanup_warning."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from agentharness.models import FeatureState
from agentharness.state_manager import StateManager


def _make_state(feature_id: str = "feat-abc", worktree_path: str | None = None) -> FeatureState:
    return FeatureState(feature_id=feature_id, worktree_path=worktree_path)


def _serialize(state: FeatureState) -> bytes:
    return state.model_dump_json().encode()


def _make_manager(state: FeatureState) -> tuple[StateManager, MagicMock]:
    """Return a StateManager wired to a blob mock that serves the given state."""
    lease_mock = AsyncMock()
    stream_mock = AsyncMock()
    stream_mock.readall.return_value = _serialize(state)

    blob_mock = AsyncMock()
    blob_mock.acquire_lease.return_value = lease_mock
    blob_mock.download_blob.return_value = stream_mock

    service_mock = MagicMock()
    service_mock.get_container_client.return_value.get_blob_client.return_value = blob_mock

    return StateManager(service_mock, "pipeline-artifacts"), blob_mock


class TestSetWorktreePath:
    async def test_persists_path_under_lease(self):
        state = _make_state()
        mgr, blob_mock = _make_manager(state)

        await mgr.set_worktree_path("feat-abc", "/repo/.worktrees/feat-abc")

        blob_mock.acquire_lease.assert_called_once()
        blob_mock.upload_blob.assert_called_once()
        uploaded_json = blob_mock.upload_blob.call_args[0][0]
        saved = FeatureState.model_validate_json(uploaded_json)
        assert saved.worktree_path == "/repo/.worktrees/feat-abc"

    async def test_same_value_is_noop_no_error(self):
        state = _make_state(worktree_path="/repo/.worktrees/feat-abc")
        mgr, blob_mock = _make_manager(state)

        # Should not raise even though path is already set
        await mgr.set_worktree_path("feat-abc", "/repo/.worktrees/feat-abc")

        blob_mock.upload_blob.assert_called_once()
        uploaded_json = blob_mock.upload_blob.call_args[0][0]
        saved = FeatureState.model_validate_json(uploaded_json)
        assert saved.worktree_path == "/repo/.worktrees/feat-abc"

    async def test_raises_on_overwrite_with_different_value(self):
        state = _make_state(worktree_path="/repo/.worktrees/feat-abc")
        mgr, blob_mock = _make_manager(state)

        with pytest.raises(ValueError, match="immutability invariant"):
            await mgr.set_worktree_path("feat-abc", "/repo/.worktrees/different-path")

        blob_mock.upload_blob.assert_not_called()

    async def test_lease_released_after_success(self):
        state = _make_state()
        mgr, blob_mock = _make_manager(state)
        lease_mock = blob_mock.acquire_lease.return_value

        await mgr.set_worktree_path("feat-abc", "/repo/.worktrees/feat-abc")

        lease_mock.release.assert_called_once()

    async def test_lease_released_on_error(self):
        state = _make_state(worktree_path="/existing/path")
        mgr, blob_mock = _make_manager(state)
        lease_mock = blob_mock.acquire_lease.return_value

        with pytest.raises(ValueError):
            await mgr.set_worktree_path("feat-abc", "/different/path")

        lease_mock.release.assert_called_once()


class TestSetCleanupWarning:
    async def test_persists_message_under_lease(self):
        state = _make_state()
        mgr, blob_mock = _make_manager(state)

        await mgr.set_cleanup_warning("feat-abc", "worktree removal failed: directory busy")

        blob_mock.acquire_lease.assert_called_once()
        blob_mock.upload_blob.assert_called_once()
        uploaded_json = blob_mock.upload_blob.call_args[0][0]
        saved = FeatureState.model_validate_json(uploaded_json)
        assert saved.cleanup_warning == "worktree removal failed: directory busy"

    async def test_subsequent_read_sees_warning(self):
        """Verify the serialized state round-trips cleanup_warning correctly."""
        state = _make_state()
        mgr, blob_mock = _make_manager(state)

        await mgr.set_cleanup_warning("feat-abc", "some error")

        uploaded_json = blob_mock.upload_blob.call_args[0][0]
        reloaded = FeatureState.model_validate_json(uploaded_json)
        assert reloaded.cleanup_warning == "some error"

    async def test_worktree_path_preserved_when_setting_warning(self):
        state = _make_state(worktree_path="/repo/.worktrees/feat-abc")
        mgr, blob_mock = _make_manager(state)

        await mgr.set_cleanup_warning("feat-abc", "removal failed")

        uploaded_json = blob_mock.upload_blob.call_args[0][0]
        saved = FeatureState.model_validate_json(uploaded_json)
        assert saved.worktree_path == "/repo/.worktrees/feat-abc"
        assert saved.cleanup_warning == "removal failed"

    async def test_lease_released_after_success(self):
        state = _make_state()
        mgr, blob_mock = _make_manager(state)
        lease_mock = blob_mock.acquire_lease.return_value

        await mgr.set_cleanup_warning("feat-abc", "msg")

        lease_mock.release.assert_called_once()


class TestConcurrentSerializationViaLease:
    async def test_second_call_retries_on_lease_contention(self):
        """Concurrent updates serialize via lease — contention causes retry."""
        from azure.core.exceptions import HttpResponseError

        state = _make_state()
        lease_mock = AsyncMock()
        stream_mock = AsyncMock()
        stream_mock.readall.return_value = _serialize(state)

        contention = HttpResponseError(message="lease conflict")
        contention.error_code = "LeaseAlreadyPresent"

        blob_mock = AsyncMock()
        blob_mock.acquire_lease.side_effect = [contention, lease_mock]
        blob_mock.download_blob.return_value = stream_mock

        service_mock = MagicMock()
        service_mock.get_container_client.return_value.get_blob_client.return_value = blob_mock

        mgr = StateManager(service_mock, "pipeline-artifacts")

        import agentharness.state_manager as sm_mod
        original_sleep = sm_mod.asyncio.sleep
        sm_mod.asyncio.sleep = AsyncMock()
        try:
            await mgr.set_worktree_path("feat-abc", "/repo/.worktrees/feat-abc")
        finally:
            sm_mod.asyncio.sleep = original_sleep

        assert blob_mock.acquire_lease.call_count == 2
        blob_mock.upload_blob.assert_called_once()
