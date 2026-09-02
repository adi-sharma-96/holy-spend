from functools import lru_cache

from app.config import get_settings
from app.errors import StorageConfigurationError
from app.object_storage import NoOpUploadRateLimiter, ObjectStorage, UploadRateLimiter
from app.supabase_storage import SupabaseStorage


@lru_cache
def get_object_storage() -> ObjectStorage:
    settings = get_settings()
    try:
        supabase_url, secret_key = settings.storage_credentials()
    except ValueError as error:
        raise StorageConfigurationError(str(error)) from error
    return SupabaseStorage(supabase_url, secret_key)


@lru_cache
def get_upload_rate_limiter() -> UploadRateLimiter:
    return NoOpUploadRateLimiter()
