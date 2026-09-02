from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True)
class StoredObjectMetadata:
    byte_size: int
    mime_type: str


class ObjectStorage(Protocol):
    def confirm_upload(self, bucket: str, object_key: str) -> StoredObjectMetadata: ...

    def create_signed_download_url(self, bucket: str, object_key: str, expires_in: int) -> str: ...

    def delete_object(self, bucket: str, object_key: str) -> None: ...

    def object_exists(self, bucket: str, object_key: str) -> bool: ...

    def upload_object(self, bucket: str, object_key: str, content: bytes, mime_type: str) -> None: ...


class UploadRateLimiter(Protocol):
    def check(self, user_id: UUID) -> None: ...


class NoOpUploadRateLimiter:
    def check(self, user_id: UUID) -> None:
        del user_id
