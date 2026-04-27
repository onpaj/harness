"""Azure Blob Storage implementation of ArtifactStorage."""

from __future__ import annotations

import asyncio

from azure.storage.blob.aio import BlobServiceClient

from agentharness.config import Config


class AzureArtifactStore:
    """Async wrapper for Azure Blob Storage artifact operations."""

    def __init__(self, blob_service: BlobServiceClient, container: str) -> None:
        self._service = blob_service
        self._container = container

    @classmethod
    def from_config(cls, config: Config) -> AzureArtifactStore:
        client = BlobServiceClient.from_connection_string(config.storage.connection_string)
        return cls(client, config.storage.container)

    async def upload(self, blob_path: str, content: str | bytes, verify_retries: int = 5, verify_delay: float = 0.5) -> None:
        if isinstance(content, str):
            content = content.encode()
        container = self._service.get_container_client(self._container)
        blob = container.get_blob_client(blob_path)
        await blob.upload_blob(content, overwrite=True)
        for _ in range(verify_retries):
            if await blob.exists():
                return
            await asyncio.sleep(verify_delay)
        raise RuntimeError(f"Blob not available after upload: {blob_path}")

    async def download(self, blob_path: str) -> str:
        container = self._service.get_container_client(self._container)
        blob = container.get_blob_client(blob_path)
        stream = await blob.download_blob()
        data = await stream.readall()
        return data.decode()

    async def exists(self, blob_path: str) -> bool:
        container = self._service.get_container_client(self._container)
        blob = container.get_blob_client(blob_path)
        return await blob.exists()

    async def ensure_container_exists(self) -> None:
        container = self._service.get_container_client(self._container)
        try:
            await container.create_container()
        except Exception:
            pass

    async def close(self) -> None:
        await self._service.close()

    def get_blob_service(self) -> BlobServiceClient:
        return self._service

    def get_container_name(self) -> str:
        return self._container
