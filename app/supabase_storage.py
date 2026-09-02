from pathlib import PurePosixPath
from typing import Any, cast

from storage3 import SyncStorageClient
from storage3.exceptions import StorageApiError

from app.errors import StorageObjectNotFoundError, StorageOperationError
from app.object_storage import ObjectStorage, StoredObjectMetadata


def validate_object_key(object_key: str) -> None:
    path = PurePosixPath(object_key)
    if (
        not object_key
        or object_key.startswith("/")
        or "\\" in object_key
        or any(part in {"", ".", ".."} for part in object_key.split("/"))
        or path.as_posix() != object_key
    ):
        raise StorageOperationError("Invalid storage object key")


class SupabaseStorage(ObjectStorage):
    def __init__(self, supabase_url: str, secret_key: str) -> None:
        endpoint = f"{supabase_url.rstrip('/')}/storage/v1/"
        self.client = SyncStorageClient(
            endpoint,
            {
                "apikey": secret_key,
                "Authorization": f"Bearer {secret_key}",
            },
        )

    def confirm_upload(self, bucket: str, object_key: str) -> StoredObjectMetadata:
        validate_object_key(object_key)
        parent, _, filename = object_key.rpartition("/")
        try:
            rows = self.client.from_(bucket).list(parent, {"limit": 100, "search": filename})
        except StorageApiError as error:
            raise StorageOperationError(f"Supabase could not inspect the uploaded object: {error.message}") from error

        row = next((candidate for candidate in rows if candidate.get("name") == filename), None)
        if row is None:
            raise StorageObjectNotFoundError("Uploaded object was not found")

        metadata = cast(dict[str, Any], row.get("metadata") or {})
        size_value = metadata.get("size")
        mime_value = metadata.get("mimetype") or metadata.get("contentType") or metadata.get("content-type")
        if size_value is None or mime_value is None:
            raise StorageOperationError("Supabase returned incomplete object metadata")
        try:
            byte_size = int(size_value)
        except (TypeError, ValueError) as error:
            raise StorageOperationError("Supabase returned an invalid object size") from error
        return StoredObjectMetadata(byte_size=byte_size, mime_type=str(mime_value).lower())

    def create_signed_download_url(self, bucket: str, object_key: str, expires_in: int) -> str:
        validate_object_key(object_key)
        try:
            result = self.client.from_(bucket).create_signed_url(object_key, expires_in, {"download": True})
        except StorageApiError as error:
            raise StorageOperationError(f"Supabase could not create a download URL: {error.message}") from error
        signed_url = result.get("signedURL") or result.get("signedUrl")
        if not signed_url:
            raise StorageOperationError("Supabase returned an empty signed download URL")
        return str(signed_url)

    def delete_object(self, bucket: str, object_key: str) -> None:
        validate_object_key(object_key)
        try:
            self.client.from_(bucket).remove([object_key])
        except StorageApiError as error:
            raise StorageOperationError(f"Supabase could not delete the object: {error.message}") from error

    def object_exists(self, bucket: str, object_key: str) -> bool:
        try:
            self.confirm_upload(bucket, object_key)
        except StorageObjectNotFoundError:
            return False
        return True

    def upload_object(self, bucket: str, object_key: str, content: bytes, mime_type: str) -> None:
        validate_object_key(object_key)
        try:
            self.client.from_(bucket).upload(
                object_key,
                content,
                {"content-type": mime_type, "upsert": "false"},
            )
        except StorageApiError as error:
            raise StorageOperationError(f"Supabase could not upload the object: {error.message}") from error
