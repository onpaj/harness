"""Lease-based atomic state management for feature state.json blobs."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Callable

from azure.core.exceptions import HttpResponseError, ResourceNotFoundError
from azure.storage.blob.aio import BlobServiceClient

from agentharness.models import FeatureState
from agentharness.storage import state_blob_path

log = logging.getLogger(__name__)

_LEASE_DURATION_SECONDS = 30
_MAX_RETRIES = 10
_RETRY_BASE_SECONDS = 0.5

# Azure error codes that indicate lease contention — safe to retry
_LEASE_CONTENTION_CODES = {"LeaseAlreadyPresent", "LeaseIdMissing", "LeaseLost"}


class AzureStateManager:
    """Read and update feature state with blob lease for atomicity."""

    def __init__(self, blob_service: BlobServiceClient, container: str) -> None:
        self._service = blob_service
        self._container = container

    @classmethod
    def from_config(cls, config) -> AzureStateManager:
        return cls(BlobServiceClient.from_connection_string(config.storage.connection_string), config.storage.container)

    def _blob_client(self, feature_id: str):
        return self._service.get_container_client(self._container).get_blob_client(
            state_blob_path(feature_id)
        )

    async def get(self, feature_id: str) -> FeatureState:
        blob = self._blob_client(feature_id)
        try:
            stream = await blob.download_blob()
            data = await stream.readall()
            return FeatureState.model_validate_json(data)
        except ResourceNotFoundError:
            raise KeyError(f"No state found for feature {feature_id!r}")

    async def create(self, state: FeatureState, brief_content: str = "") -> None:
        """Write initial state (no lease needed — blob doesn't exist yet)."""
        blob = self._blob_client(state.feature_id)
        await blob.upload_blob(state.model_dump_json(), overwrite=False)

    async def update(
        self,
        feature_id: str,
        updater: Callable[[FeatureState], FeatureState],
    ) -> FeatureState:
        """Atomically read → transform → write state using a blob lease.

        Retries with exponential backoff if lease acquisition fails.
        """
        for attempt in range(_MAX_RETRIES):
            blob = self._blob_client(feature_id)
            lease = None
            try:
                lease = await blob.acquire_lease(lease_duration=_LEASE_DURATION_SECONDS)
                stream = await blob.download_blob(lease=lease)
                data = await stream.readall()
                current = FeatureState.model_validate_json(data)
                updated = updater(current)
                await blob.upload_blob(
                    updated.model_dump_json(),
                    overwrite=True,
                    lease=lease,
                )
                return updated
            except HttpResponseError as exc:
                if exc.error_code not in _LEASE_CONTENTION_CODES:
                    raise
                if attempt == _MAX_RETRIES - 1:
                    raise RuntimeError(
                        f"Failed to acquire lease for {feature_id} after {_MAX_RETRIES} attempts"
                    ) from exc
                backoff = _RETRY_BASE_SECONDS * (2**attempt)
                log.warning(
                    "Lease contention on %s, retrying in %.1fs (attempt %d/%d)",
                    feature_id,
                    backoff,
                    attempt + 1,
                    _MAX_RETRIES,
                )
                await asyncio.sleep(backoff)
            finally:
                if lease:
                    try:
                        await lease.release()
                    except Exception:
                        pass  # Lease may have expired; ignore

        raise RuntimeError(f"Exhausted retries updating state for {feature_id}")

    async def set_worktree_path(self, feature_id: str, worktree_path: str) -> None:
        """Atomically persist worktree_path under blob lease.

        No-op if already set to the same value.
        Raises ValueError if attempting to overwrite a different non-None value.
        """
        await self.update(feature_id, lambda s: s.with_worktree_path(worktree_path))

    async def set_cleanup_warning(self, feature_id: str, message: str) -> None:
        """Atomically persist cleanup_warning on the feature record under blob lease."""
        await self.update(feature_id, lambda s: s.with_cleanup_warning(message))

    async def list_features(self) -> list[FeatureState]:
        """List all features by enumerating state.json blobs under artifacts/."""
        container = self._service.get_container_client(self._container)
        states: list[FeatureState] = []
        async for blob in container.list_blobs(name_starts_with="artifacts/"):
            if not blob.name.endswith("/state.json"):
                continue
            feature_id = blob.name.split("/")[1]
            try:
                state = await self.get(feature_id)
                states.append(state)
            except (ValueError, KeyError, json.JSONDecodeError) as exc:
                log.warning("Unreadable state blob %s: %s", blob.name, exc)
            except Exception as exc:
                log.error("Unexpected error reading state blob %s: %s", blob.name, exc)
        return states

    async def open_review(self, feature_id: str) -> str | None:
        """Azure has no PR concept; always returns None."""
        log.debug("open_review called for %s — no-op on Azure backend", feature_id)
        return None


# Backward-compatible alias — prefer AzureStateManager in new code
StateManager = AzureStateManager
