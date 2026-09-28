"""Blob storage for uploaded files: Azurite locally, Azure Blob Storage when deployed.

Both speak the same API, so only AZURE_STORAGE_CONNECTION_STRING changes between them.
"""
from functools import lru_cache
import os

from azure.core.exceptions import AzureError, ResourceExistsError, ResourceNotFoundError
from azure.storage.blob import BlobServiceClient, ContentSettings


class StorageUnavailable(Exception):
    pass


class BlobStorage:
    def __init__(self, connection_string: str, container: str):
        # Short timeouts and few retries so a storage outage fails fast instead of hanging requests.
        service = BlobServiceClient.from_connection_string(
            connection_string, connection_timeout=3, read_timeout=30, retry_total=2)
        self._container = service.get_container_client(container)
        self._container_ready = False

    def _ensure_container(self):
        if self._container_ready:
            return
        try:
            self._container.create_container()
        except ResourceExistsError:
            pass
        self._container_ready = True

    def upload(self, name: str, data: bytes, content_type: str = "text/csv") -> None:
        try:
            self._ensure_container()
            self._container.upload_blob(name, data, overwrite=False,
                                        content_settings=ContentSettings(content_type=content_type))
        except AzureError as error:
            raise StorageUnavailable from error

    def delete(self, name: str) -> None:
        try:
            self._container.delete_blob(name)
        except ResourceNotFoundError:
            pass
        except AzureError as error:
            raise StorageUnavailable from error

    def check(self) -> None:
        try:
            self._ensure_container()
            self._container.get_container_properties()
        except AzureError as error:
            raise StorageUnavailable from error


@lru_cache
def get_storage() -> BlobStorage:
    return BlobStorage(os.environ["AZURE_STORAGE_CONNECTION_STRING"],
                       os.getenv("STORAGE_CONTAINER", "uploads"))
