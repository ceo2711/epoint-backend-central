from typing import Protocol

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from app.core.config import get_settings


class StorageProvider(Protocol):
    def build_key(self, *parts: str) -> str: ...

    def generate_upload_url(self, key: str, content_type: str, expires_in: int = 3600) -> str: ...

    def generate_download_url(self, key: str, expires_in: int = 900) -> str: ...

    def delete_object(self, key: str) -> None: ...

    def object_exists(self, key: str) -> bool: ...


class S3StorageProvider:
    """Almacenamiento S3 compatible con Bucketeer (Heroku) y MinIO (local)."""

    def __init__(self) -> None:
        settings = get_settings()
        client_kwargs: dict = {
            "service_name": "s3",
            "aws_access_key_id": settings.aws_access_key_id,
            "aws_secret_access_key": settings.aws_secret_access_key,
            "region_name": settings.aws_region,
            "config": Config(signature_version="s3v4"),
        }
        if settings.s3_endpoint_url:
            client_kwargs["endpoint_url"] = settings.s3_endpoint_url
            client_kwargs["use_ssl"] = settings.s3_use_ssl

        self._client = boto3.client(**client_kwargs)
        self._bucket = settings.s3_bucket_name
        self._prefix = settings.s3_storage_prefix.strip("/")

    def build_key(self, *parts: str) -> str:
        clean_parts = [p.strip("/") for p in parts if p]
        key = "/".join(clean_parts)
        if self._prefix:
            return f"{self._prefix}/{key}"
        return key

    def generate_upload_url(self, key: str, content_type: str, expires_in: int = 3600) -> str:
        return self._client.generate_presigned_url(
            "put_object",
            Params={"Bucket": self._bucket, "Key": key, "ContentType": content_type},
            ExpiresIn=expires_in,
        )

    def generate_download_url(self, key: str, expires_in: int = 900) -> str:
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=expires_in,
        )

    def delete_object(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=key)

    def object_exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
            return True
        except ClientError:
            return False


_storage_provider: S3StorageProvider | None = None


def get_storage_provider() -> S3StorageProvider:
    global _storage_provider
    if _storage_provider is None:
        _storage_provider = S3StorageProvider()
    return _storage_provider
