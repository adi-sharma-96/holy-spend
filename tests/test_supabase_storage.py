import builtins
from typing import Any

from app.supabase_storage import SupabaseStorage


class FakeBucket:
    def __init__(self) -> None:
        self.signed_ttl: int | None = None
        self.removed: list[str] = []
        self.uploaded: tuple[str, bytes, dict[str, str]] | None = None

    def list(self, path: str, options: dict[str, Any]) -> builtins.list[dict[str, Any]]:
        del path, options
        return [{"name": "file.png", "metadata": {"size": 4, "mimetype": "image/png"}}]

    def create_signed_url(self, path: str, expires_in: int, options: object) -> dict[str, str]:
        del path, options
        self.signed_ttl = expires_in
        return {"signedURL": "https://example.test/download"}

    def remove(self, paths: builtins.list[str]) -> builtins.list[dict[str, Any]]:
        self.removed.extend(paths)
        return []

    def upload(self, path: str, content: bytes, options: dict[str, str]) -> object:
        self.uploaded = (path, content, options)
        return object()


class FakeStorageClient:
    def __init__(self, bucket: FakeBucket) -> None:
        self.bucket = bucket
        self.bucket_name: str | None = None

    def from_(self, bucket_name: str) -> FakeBucket:
        self.bucket_name = bucket_name
        return self.bucket


def test_supabase_storage_adapter_maps_sdk_operations(monkeypatch: Any) -> None:
    bucket = FakeBucket()
    client = FakeStorageClient(bucket)
    monkeypatch.setattr("app.supabase_storage.SyncStorageClient", lambda *_args, **_kwargs: client)
    storage = SupabaseStorage("https://project.supabase.co", "secret")
    object_key = "users/a/receipts/b/file.png"

    metadata = storage.confirm_upload("receipt-originals", object_key)
    download_url = storage.create_signed_download_url("receipt-originals", object_key, 75)
    storage.upload_object("receipt-originals", object_key, b"data", "image/png")
    storage.delete_object("receipt-originals", object_key)

    assert metadata.byte_size == 4
    assert metadata.mime_type == "image/png"
    assert download_url == "https://example.test/download"
    assert bucket.signed_ttl == 75
    assert bucket.uploaded == (object_key, b"data", {"content-type": "image/png", "upsert": "false"})
    assert bucket.removed == [object_key]
