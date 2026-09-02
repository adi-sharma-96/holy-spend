from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import pytest

from app.config import Settings
from app.errors import ConflictError, InvalidUploadError, NotFoundError
from app.models import ReceiptFileUploadStatus, ReceiptRecord
from app.object_storage import NoOpUploadRateLimiter, StoredObjectMetadata
from app.receipt_files import (
    OwnedReceiptFile,
    ReceiptFileRepository,
    ReceiptFileService,
    sanitize_and_validate_filename,
)

USER_ID = UUID("10000000-0000-4000-8000-000000000001")
RECEIPT_ID = UUID("20000000-0000-4000-8000-000000000001")
TRANSACTION_ID = UUID("30000000-0000-4000-8000-000000000001")
FILE_ID = UUID("40000000-0000-4000-8000-000000000001")


def owned_file(*, status: ReceiptFileUploadStatus = ReceiptFileUploadStatus.UPLOADED) -> OwnedReceiptFile:
    now = datetime.now(UTC)
    return OwnedReceiptFile(
        id=FILE_ID,
        user_id=USER_ID,
        receipt_id=RECEIPT_ID,
        storage_provider="supabase",
        bucket_name="receipt-originals",
        object_key=f"users/{USER_ID}/receipts/{RECEIPT_ID}/receipt.jpg",
        original_filename="receipt.jpg",
        mime_type="image/jpeg",
        byte_size=4,
        sha256="a" * 64,
        upload_status=status,
        created_at=now,
        uploaded_at=now if status == ReceiptFileUploadStatus.UPLOADED else None,
        deleted_at=None,
    )


class FakeRepository:
    def __init__(self) -> None:
        self.file = owned_file()
        self.receipt = ReceiptRecord(
            id=RECEIPT_ID,
            transaction_id=TRANSACTION_ID,
            created_at=datetime.now(UTC),
        )
        self.marked_deleted = False
        self.deleted_transactions: list[UUID] = []
        self.cleanup_jobs: list[tuple[str, str, str, str]] = []

    def get_file(self, receipt_id: UUID, file_id: UUID) -> OwnedReceiptFile:
        if receipt_id != RECEIPT_ID or file_id != FILE_ID:
            raise NotFoundError("Receipt file not found")
        return self.file

    def get_receipt(self, receipt_id: UUID) -> ReceiptRecord:
        if receipt_id != RECEIPT_ID:
            raise NotFoundError("Receipt not found")
        return self.receipt

    def get_receipt_for_transaction(self, transaction_id: UUID) -> ReceiptRecord | None:
        if transaction_id != TRANSACTION_ID:
            raise NotFoundError("Transaction not found")
        return self.receipt

    def list_files(self, receipt_id: UUID) -> list[OwnedReceiptFile]:
        self.get_receipt(receipt_id)
        return [self.file]

    def mark_file_deleted(self, receipt_id: UUID, file_id: UUID) -> None:
        self.get_file(receipt_id, file_id)
        self.marked_deleted = True

    def delete_transaction(self, transaction_id: UUID) -> None:
        self.deleted_transactions.append(transaction_id)

    def record_cleanup_job(
        self,
        bucket_name: str,
        object_key: str,
        operation: str,
        last_error: str,
    ) -> None:
        self.cleanup_jobs.append((bucket_name, object_key, operation, last_error))


class FakeStorage:
    def __init__(self) -> None:
        self.objects = {owned_file().object_key}
        self.downloads: list[tuple[str, str, int]] = []
        self.deleted: list[str] = []

    def confirm_upload(self, bucket: str, object_key: str) -> StoredObjectMetadata:
        del bucket, object_key
        return StoredObjectMetadata(byte_size=4, mime_type="image/jpeg")

    def create_signed_download_url(self, bucket: str, object_key: str, expires_in: int) -> str:
        self.downloads.append((bucket, object_key, expires_in))
        return "https://storage.example/private"

    def delete_object(self, bucket: str, object_key: str) -> None:
        del bucket
        self.objects.discard(object_key)
        self.deleted.append(object_key)

    def object_exists(self, bucket: str, object_key: str) -> bool:
        del bucket
        return object_key in self.objects

    def upload_object(self, bucket: str, object_key: str, content: bytes, mime_type: str) -> None:
        del bucket, content, mime_type
        self.objects.add(object_key)


def service() -> tuple[ReceiptFileService, FakeRepository, FakeStorage]:
    repository = FakeRepository()
    storage = FakeStorage()
    return (
        ReceiptFileService(
            cast(ReceiptFileRepository, repository),
            storage,
            NoOpUploadRateLimiter(),
            Settings(_env_file=None),
        ),
        repository,
        storage,
    )


@pytest.mark.parametrize("filename", ["../receipt.jpg", r"..\receipt.jpg", "/receipt.jpg"])
def test_receipt_filename_rejects_path_traversal(filename: str) -> None:
    with pytest.raises(InvalidUploadError):
        sanitize_and_validate_filename(filename, "image/jpeg")


def test_receipt_filename_requires_matching_supported_mime() -> None:
    with pytest.raises(InvalidUploadError):
        sanitize_and_validate_filename("receipt.jpg", "application/pdf")


def test_private_receipt_view_uses_short_lived_server_signed_url() -> None:
    receipt_service, _, storage = service()

    result = receipt_service.create_download_url(RECEIPT_ID, FILE_ID)

    assert result.download_url == "https://storage.example/private"
    assert storage.downloads[0][1] == owned_file().object_key
    assert storage.downloads[0][2] == Settings(_env_file=None).storage_signed_url_ttl_seconds


def test_unconfirmed_receipt_cannot_be_viewed() -> None:
    receipt_service, repository, _ = service()
    repository.file = owned_file(status=ReceiptFileUploadStatus.PENDING)

    with pytest.raises(ConflictError):
        receipt_service.create_download_url(RECEIPT_ID, FILE_ID)


def test_receipt_file_deletion_removes_object_then_metadata() -> None:
    receipt_service, repository, storage = service()

    assert receipt_service.delete_file(RECEIPT_ID, FILE_ID) is True
    assert storage.deleted == [owned_file().object_key]
    assert repository.marked_deleted is True


def test_transaction_deletion_removes_owned_receipt_object_first() -> None:
    receipt_service, repository, storage = service()

    assert receipt_service.delete_transaction(TRANSACTION_ID) is True
    assert storage.deleted == [owned_file().object_key]
    assert repository.deleted_transactions == [TRANSACTION_ID]


def test_removed_upload_and_legacy_ingestion_methods_do_not_exist() -> None:
    receipt_service, _, _ = service()

    for obsolete in (
        "create_upload_target",
        "confirm_upload",
        "upload_multipart",
        "ingest_chatgpt_file",
    ):
        assert not hasattr(receipt_service, obsolete)
