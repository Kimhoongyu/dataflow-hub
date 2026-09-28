"""Object storage for uploaded and result files over the S3 API.

Locally this talks to SeaweedFS; on Naver Cloud it talks to NCP Object Storage, which is
S3-compatible. Only the S3_* environment variables change between them.
"""
from functools import lru_cache
import os

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError


class StorageUnavailable(Exception):
    """Transient: storage could not be reached. Callers may retry."""


class ObjectNotFound(Exception):
    """Permanent: the object does not exist. Retrying will not help."""


def _not_found(error: ClientError) -> bool:
    return error.response.get("ResponseMetadata", {}).get("HTTPStatusCode") == 404


class ObjectStorage:
    def __init__(self, endpoint_url: str, region: str, access_key: str, secret_key: str, bucket: str,
                 max_attempts: int = 2):
        def client(attempts: int):
            config = Config(
                # Short timeouts and few attempts so an outage fails fast instead of hanging requests;
                # the worker adds its own job-level retries with backoff on top.
                connect_timeout=3, read_timeout=30, retries={"max_attempts": attempts, "mode": "standard"},
                s3={"addressing_style": "path"},
                # Newer botocore adds CRC checksums by default, which S3-compatible stores may reject.
                request_checksum_calculation="when_required", response_checksum_validation="when_required")
            return boto3.client("s3", endpoint_url=endpoint_url, region_name=region, aws_access_key_id=access_key,
                                aws_secret_access_key=secret_key, config=config)
        self._client = client(max_attempts)
        # Health checks must answer within the probe timeout, so they never retry.
        self._probe = client(1)
        self._bucket = bucket
        self._bucket_ready = False

    def _ensure_bucket(self):
        # Deployed buckets are created by Terraform; this only matters for a fresh local emulator.
        if self._bucket_ready:
            return
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except ClientError as error:
            if not _not_found(error):
                raise
            self._client.create_bucket(Bucket=self._bucket)
        self._bucket_ready = True

    def upload(self, name: str, data: bytes, content_type: str = "text/csv", overwrite: bool = False) -> None:
        # S3 always overwrites; callers keep `overwrite=False` keys unique (UUID-based names).
        try:
            self._ensure_bucket()
            self._client.put_object(Bucket=self._bucket, Key=name, Body=data, ContentType=content_type)
        except (BotoCoreError, ClientError) as error:
            raise StorageUnavailable from error

    def download(self, name: str) -> bytes:
        try:
            return self._client.get_object(Bucket=self._bucket, Key=name)["Body"].read()
        except ClientError as error:
            if _not_found(error):
                raise ObjectNotFound(name) from error
            raise StorageUnavailable from error
        except BotoCoreError as error:
            raise StorageUnavailable from error

    def delete(self, name: str) -> None:
        # Deleting a missing key succeeds in S3.
        try:
            self._client.delete_object(Bucket=self._bucket, Key=name)
        except (BotoCoreError, ClientError) as error:
            raise StorageUnavailable from error

    def check(self) -> None:
        try:
            if not self._bucket_ready:
                self._ensure_bucket()
            # Always round-trip: readiness must notice an outage after the bucket was first seen.
            self._probe.head_bucket(Bucket=self._bucket)
        except (BotoCoreError, ClientError) as error:
            raise StorageUnavailable from error


@lru_cache
def get_storage() -> ObjectStorage:
    return ObjectStorage(os.environ["S3_ENDPOINT_URL"], os.getenv("S3_REGION", "kr-standard"),
                         os.environ["S3_ACCESS_KEY"], os.environ["S3_SECRET_KEY"], os.getenv("S3_BUCKET", "uploads"),
                         int(os.getenv("S3_MAX_ATTEMPTS", "2")))
