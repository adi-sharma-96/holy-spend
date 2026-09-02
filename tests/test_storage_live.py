import os
from uuid import uuid4

import pytest

from app.supabase_storage import SupabaseStorage

RUN_LIVE_STORAGE_TESTS = os.getenv("RUN_LIVE_STORAGE_TESTS") == "1"
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY")
STORAGE_BUCKET = os.getenv("STORAGE_BUCKET", "receipt-originals")

pytestmark = pytest.mark.skipif(
    not RUN_LIVE_STORAGE_TESTS or not SUPABASE_URL or not SUPABASE_SECRET_KEY,
    reason="Set RUN_LIVE_STORAGE_TESTS=1, SUPABASE_URL, and SUPABASE_SECRET_KEY to run live Storage tests.",
)


def test_live_storage_upload_sign_and_delete() -> None:
    assert SUPABASE_URL is not None
    assert SUPABASE_SECRET_KEY is not None
    storage = SupabaseStorage(SUPABASE_URL, SUPABASE_SECRET_KEY)
    object_key = f"users/{uuid4()}/receipts/{uuid4()}/{uuid4().hex}.png"

    try:
        storage.upload_object(STORAGE_BUCKET, object_key, b"phase-3-storage-test", "image/png")
        metadata = storage.confirm_upload(STORAGE_BUCKET, object_key)
        signed_url = storage.create_signed_download_url(STORAGE_BUCKET, object_key, 60)

        assert metadata.byte_size == len(b"phase-3-storage-test")
        assert signed_url.startswith("http")
    finally:
        if storage.object_exists(STORAGE_BUCKET, object_key):
            storage.delete_object(STORAGE_BUCKET, object_key)

    assert storage.object_exists(STORAGE_BUCKET, object_key) is False
