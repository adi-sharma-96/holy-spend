import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol, cast
from uuid import UUID

from app.config import Settings
from app.errors import ConflictError, InvalidUploadError, NotFoundError, StorageOperationError
from app.models import (
    ReceiptDraftCreate,
    ReceiptFileDownloadUrlResponse,
    ReceiptFileRecord,
    ReceiptFileUploadStatus,
    ReceiptRecord,
)
from app.object_storage import ObjectStorage, StoredObjectMetadata, UploadRateLimiter

ALLOWED_RECEIPT_TYPES = {
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".webp": "image/webp",
}
READ_CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True)
class OwnedReceiptFile:
    id: UUID
    user_id: UUID
    receipt_id: UUID
    storage_provider: str
    bucket_name: str
    object_key: str
    original_filename: str
    mime_type: str
    byte_size: int | None
    sha256: str | None
    upload_status: ReceiptFileUploadStatus
    created_at: datetime
    uploaded_at: datetime | None
    deleted_at: datetime | None

    def public_record(self) -> ReceiptFileRecord:
        return ReceiptFileRecord(
            id=self.id,
            receipt_id=self.receipt_id,
            storage_provider=self.storage_provider,
            bucket_name=self.bucket_name,
            original_filename=self.original_filename,
            mime_type=self.mime_type,
            byte_size=self.byte_size,
            sha256=self.sha256,
            upload_status=self.upload_status,
            created_at=self.created_at,
            uploaded_at=self.uploaded_at,
            deleted_at=self.deleted_at,
        )


@dataclass(frozen=True)
class ReceiptCommitReplay:
    request_hash: str
    source_file_sha256: str
    transaction_id: UUID
    receipt_id: UUID
    result_version: int
    file: OwnedReceiptFile


class ReceiptFileRepository(Protocol):
    def create_receipt_draft(self, payload: ReceiptDraftCreate) -> ReceiptRecord: ...

    def get_receipt(self, receipt_id: UUID) -> ReceiptRecord: ...

    def get_receipt_for_transaction(self, transaction_id: UUID) -> ReceiptRecord | None: ...

    def create_pending_file(
        self,
        receipt_id: UUID,
        bucket_name: str,
        object_key: str,
        original_filename: str,
        mime_type: str,
        byte_size: int | None,
        sha256: str | None,
    ) -> OwnedReceiptFile: ...

    def get_file(self, receipt_id: UUID, file_id: UUID) -> OwnedReceiptFile: ...

    def list_files(self, receipt_id: UUID) -> list[OwnedReceiptFile]: ...

    def confirm_file(
        self,
        receipt_id: UUID,
        file_id: UUID,
        byte_size: int,
        mime_type: str,
        sha256: str | None,
    ) -> OwnedReceiptFile: ...

    def mark_file_deleted(self, receipt_id: UUID, file_id: UUID) -> None: ...

    def delete_receipt(self, receipt_id: UUID) -> None: ...

    def delete_transaction(self, transaction_id: UUID) -> None: ...

    def assert_draft_transaction_without_receipt(self, transaction_id: UUID) -> None: ...

    def mark_file_failed(self, receipt_id: UUID, file_id: UUID) -> None: ...

    def delete_file_metadata(self, receipt_id: UUID, file_id: UUID) -> None: ...

    def acquire_commit_lock(self, source_file_sha256: str) -> None: ...

    def get_commit_result_by_hash(self, source_file_sha256: str) -> ReceiptCommitReplay | None: ...

    def record_commit_result(
        self,
        client_request_id: str,
        request_hash: str,
        source_file_sha256: str,
        transaction_id: UUID,
        receipt_id: UUID,
        receipt_file_id: UUID,
        object_key: str,
    ) -> None: ...

    def record_cleanup_job(
        self,
        bucket_name: str,
        object_key: str,
        reason: str,
        error: str,
    ) -> None: ...


class ReceiptRepository:
    def __init__(self, conn: Any, user_id: UUID) -> None:
        self.conn = conn
        self.user_id = user_id

    def create_receipt_draft(self, payload: ReceiptDraftCreate) -> ReceiptRecord:
        if payload.transaction_id is None:
            row = self.conn.execute(
                """
                insert into transactions (
                    user_id, transaction_type, source_type, status,
                    transaction_date, currency, total_amount
                )
                values (%(user_id)s, 'expense', 'receipt', 'draft', %(transaction_date)s, %(currency)s, 0)
                returning id
                """,
                {
                    "user_id": self.user_id,
                    "transaction_date": payload.transaction_date,
                    "currency": payload.currency,
                },
            ).fetchone()
            transaction_id = cast(UUID, row["id"])
        else:
            transaction_id = payload.transaction_id
            transaction = self.conn.execute(
                """
                select id, status
                from transactions
                where id = %(transaction_id)s and user_id = %(user_id)s
                """,
                {"transaction_id": transaction_id, "user_id": self.user_id},
            ).fetchone()
            if transaction is None:
                raise NotFoundError("Transaction not found")
            if transaction["status"] != "draft":
                raise ConflictError("A receipt can only be attached to a draft transaction")
            self.conn.execute(
                """
                update transactions
                set source_type = 'receipt'
                where id = %(transaction_id)s and user_id = %(user_id)s
                """,
                {"transaction_id": transaction_id, "user_id": self.user_id},
            )

        try:
            row = self.conn.execute(
                """
                insert into receipts (user_id, transaction_id)
                values (%(user_id)s, %(transaction_id)s)
                returning id, transaction_id, created_at
                """,
                {"user_id": self.user_id, "transaction_id": transaction_id},
            ).fetchone()
        except Exception as error:
            if getattr(error, "sqlstate", None) == "23505":
                raise ConflictError("Transaction already has a receipt") from error
            raise
        self._add_audit_event("receipt", row["id"], "draft_created")
        return ReceiptRecord.model_validate(row)

    def get_receipt(self, receipt_id: UUID) -> ReceiptRecord:
        row = self.conn.execute(
            """
            select id, transaction_id, created_at
            from receipts
            where id = %(receipt_id)s and user_id = %(user_id)s
            """,
            {"receipt_id": receipt_id, "user_id": self.user_id},
        ).fetchone()
        if row is None:
            raise NotFoundError("Receipt not found")
        return ReceiptRecord.model_validate(row)

    def get_receipt_for_transaction(self, transaction_id: UUID) -> ReceiptRecord | None:
        transaction = self.conn.execute(
            "select id from transactions where id = %(transaction_id)s and user_id = %(user_id)s",
            {"transaction_id": transaction_id, "user_id": self.user_id},
        ).fetchone()
        if transaction is None:
            raise NotFoundError("Transaction not found")
        row = self.conn.execute(
            """
            select id, transaction_id, created_at
            from receipts
            where transaction_id = %(transaction_id)s and user_id = %(user_id)s
            """,
            {"transaction_id": transaction_id, "user_id": self.user_id},
        ).fetchone()
        return ReceiptRecord.model_validate(row) if row is not None else None

    def assert_draft_transaction_without_receipt(self, transaction_id: UUID) -> None:
        row = self.conn.execute(
            """
            select t.status,
                   exists (
                       select 1
                       from receipts r
                       where r.transaction_id = t.id and r.user_id = t.user_id
                   ) as has_receipt
            from transactions t
            where t.id = %(transaction_id)s and t.user_id = %(user_id)s
            """,
            {"transaction_id": transaction_id, "user_id": self.user_id},
        ).fetchone()
        if row is None:
            raise NotFoundError("Transaction not found")
        if row["status"] != "draft":
            raise ConflictError("A receipt can only be attached to a draft transaction")
        if row["has_receipt"]:
            raise ConflictError("Transaction already has a receipt")

    def create_pending_file(
        self,
        receipt_id: UUID,
        bucket_name: str,
        object_key: str,
        original_filename: str,
        mime_type: str,
        byte_size: int | None,
        sha256: str | None,
    ) -> OwnedReceiptFile:
        self.get_receipt(receipt_id)
        row = self.conn.execute(
            """
            insert into receipt_files (
                user_id, receipt_id, storage_provider, bucket_name, object_key,
                original_filename, mime_type, byte_size, sha256, upload_status
            )
            values (
                %(user_id)s, %(receipt_id)s, 'supabase', %(bucket_name)s, %(object_key)s,
                %(original_filename)s, %(mime_type)s, %(byte_size)s, %(sha256)s, 'pending'
            )
            returning id
            """,
            {
                "user_id": self.user_id,
                "receipt_id": receipt_id,
                "bucket_name": bucket_name,
                "object_key": object_key,
                "original_filename": original_filename,
                "mime_type": mime_type,
                "byte_size": byte_size,
                "sha256": sha256.lower() if sha256 else None,
            },
        ).fetchone()
        return self.get_file(receipt_id, row["id"])

    def get_file(self, receipt_id: UUID, file_id: UUID) -> OwnedReceiptFile:
        row = self.conn.execute(
            """
            select id, user_id, receipt_id, storage_provider, bucket_name, object_key,
                   original_filename, mime_type, byte_size, sha256, upload_status,
                   created_at, uploaded_at, deleted_at
            from receipt_files
            where id = %(file_id)s
              and receipt_id = %(receipt_id)s
              and user_id = %(user_id)s
              and deleted_at is null
            """,
            {"file_id": file_id, "receipt_id": receipt_id, "user_id": self.user_id},
        ).fetchone()
        if row is None:
            raise NotFoundError("Receipt file not found")
        return OwnedReceiptFile(**row)

    def list_files(self, receipt_id: UUID) -> list[OwnedReceiptFile]:
        self.get_receipt(receipt_id)
        rows = self.conn.execute(
            """
            select id, user_id, receipt_id, storage_provider, bucket_name, object_key,
                   original_filename, mime_type, byte_size, sha256, upload_status,
                   created_at, uploaded_at, deleted_at
            from receipt_files
            where receipt_id = %(receipt_id)s
              and user_id = %(user_id)s
              and deleted_at is null
            order by created_at, id
            """,
            {"receipt_id": receipt_id, "user_id": self.user_id},
        ).fetchall()
        return [OwnedReceiptFile(**row) for row in rows]

    def confirm_file(
        self,
        receipt_id: UUID,
        file_id: UUID,
        byte_size: int,
        mime_type: str,
        sha256: str | None,
    ) -> OwnedReceiptFile:
        result = self.conn.execute(
            """
            update receipt_files
            set byte_size = %(byte_size)s,
                mime_type = %(mime_type)s,
                sha256 = %(sha256)s,
                upload_status = 'uploaded',
                uploaded_at = now()
            where id = %(file_id)s
              and receipt_id = %(receipt_id)s
              and user_id = %(user_id)s
              and upload_status = 'pending'
              and deleted_at is null
            """,
            {
                "file_id": file_id,
                "receipt_id": receipt_id,
                "user_id": self.user_id,
                "byte_size": byte_size,
                "mime_type": mime_type,
                "sha256": sha256.lower() if sha256 else None,
            },
        )
        if result.rowcount == 0:
            raise ConflictError("Receipt file is not pending upload confirmation")
        self._add_audit_event("receipt_file", file_id, "upload_confirmed")
        return self.get_file(receipt_id, file_id)

    def mark_file_deleted(self, receipt_id: UUID, file_id: UUID) -> None:
        result = self.conn.execute(
            """
            update receipt_files
            set upload_status = 'deleted', deleted_at = now()
            where id = %(file_id)s
              and receipt_id = %(receipt_id)s
              and user_id = %(user_id)s
              and deleted_at is null
            """,
            {"file_id": file_id, "receipt_id": receipt_id, "user_id": self.user_id},
        )
        if result.rowcount == 0:
            raise NotFoundError("Receipt file not found")
        self._add_audit_event("receipt_file", file_id, "deleted")

    def mark_file_failed(self, receipt_id: UUID, file_id: UUID) -> None:
        result = self.conn.execute(
            """
            update receipt_files
            set upload_status = 'failed'
            where id = %(file_id)s
              and receipt_id = %(receipt_id)s
              and user_id = %(user_id)s
              and upload_status = 'pending'
              and deleted_at is null
            """,
            {"file_id": file_id, "receipt_id": receipt_id, "user_id": self.user_id},
        )
        if result.rowcount:
            self._add_audit_event("receipt_file", file_id, "upload_failed")

    def delete_file_metadata(self, receipt_id: UUID, file_id: UUID) -> None:
        self.conn.execute(
            """
            delete from receipt_files
            where id = %(file_id)s
              and receipt_id = %(receipt_id)s
              and user_id = %(user_id)s
            """,
            {"file_id": file_id, "receipt_id": receipt_id, "user_id": self.user_id},
        )

    def delete_receipt(self, receipt_id: UUID) -> None:
        result = self.conn.execute(
            "delete from receipts where id = %(receipt_id)s and user_id = %(user_id)s",
            {"receipt_id": receipt_id, "user_id": self.user_id},
        )
        if result.rowcount == 0:
            raise NotFoundError("Receipt not found")
        self._add_audit_event("receipt", receipt_id, "deleted")

    def delete_transaction(self, transaction_id: UUID) -> None:
        transaction = self.conn.execute(
            """
            select id, status
            from transactions
            where id = %(transaction_id)s and user_id = %(user_id)s
            """,
            {"transaction_id": transaction_id, "user_id": self.user_id},
        ).fetchone()
        if transaction is None:
            raise NotFoundError("Transaction not found")
        self.conn.execute(
            """
            insert into audit_events (user_id, entity_type, entity_id, action, metadata)
            values (
                %(user_id)s, 'transaction', %(transaction_id)s, 'permanently_deleted',
                jsonb_build_object('previous_status', cast(%(status)s as text))
            )
            """,
            {
                "user_id": self.user_id,
                "transaction_id": transaction_id,
                "status": transaction["status"],
            },
        )
        self.conn.execute(
            "delete from transactions where id = %(transaction_id)s and user_id = %(user_id)s",
            {"transaction_id": transaction_id, "user_id": self.user_id},
        )

    def acquire_commit_lock(self, source_file_sha256: str) -> None:
        self.conn.execute(
            """
            select pg_advisory_xact_lock(
                hashtextextended(
                    cast(%(user_id)s as text) || ':receipt-file:' || %(source_file_sha256)s,
                    0
                )
            )
            """,
            {"user_id": self.user_id, "source_file_sha256": source_file_sha256},
        )

    def get_commit_result_by_hash(self, source_file_sha256: str) -> ReceiptCommitReplay | None:
        row = self.conn.execute(
            """
            select request.request_hash, request.source_file_sha256,
                   request.transaction_id, request.receipt_id, request.result_version,
                   file.id, file.user_id, file.receipt_id as file_receipt_id,
                   file.storage_provider, file.bucket_name, file.object_key,
                   file.original_filename, file.mime_type, file.byte_size, file.sha256,
                   file.upload_status, file.created_at, file.uploaded_at, file.deleted_at
            from receipt_commit_requests request
            join receipt_files file on file.id = request.receipt_file_id
            where request.user_id = %(user_id)s
              and request.source_file_sha256 = %(source_file_sha256)s
              and file.user_id = %(user_id)s
              and file.deleted_at is null
            order by request.completed_at desc
            limit 1
            """,
            {"user_id": self.user_id, "source_file_sha256": source_file_sha256},
        ).fetchone()
        if row is None:
            return None
        return ReceiptCommitReplay(
            request_hash=row["request_hash"],
            source_file_sha256=row["source_file_sha256"],
            transaction_id=row["transaction_id"],
            receipt_id=row["receipt_id"],
            result_version=int(row["result_version"]),
            file=OwnedReceiptFile(
                id=row["id"],
                user_id=row["user_id"],
                receipt_id=row["file_receipt_id"],
                storage_provider=row["storage_provider"],
                bucket_name=row["bucket_name"],
                object_key=row["object_key"],
                original_filename=row["original_filename"],
                mime_type=row["mime_type"],
                byte_size=row["byte_size"],
                sha256=row["sha256"],
                upload_status=ReceiptFileUploadStatus(row["upload_status"]),
                created_at=row["created_at"],
                uploaded_at=row["uploaded_at"],
                deleted_at=row["deleted_at"],
            ),
        )

    def record_commit_result(
        self,
        client_request_id: str,
        request_hash: str,
        source_file_sha256: str,
        transaction_id: UUID,
        receipt_id: UUID,
        receipt_file_id: UUID,
        object_key: str,
    ) -> None:
        self.conn.execute(
            """
            insert into receipt_commit_requests (
                user_id, client_request_id, request_hash, source_file_sha256,
                transaction_id, receipt_id, receipt_file_id, object_key
            )
            values (
                %(user_id)s, %(client_request_id)s, %(request_hash)s,
                %(source_file_sha256)s, %(transaction_id)s, %(receipt_id)s,
                %(receipt_file_id)s, %(object_key)s
            )
            """,
            {
                "user_id": self.user_id,
                "client_request_id": client_request_id,
                "request_hash": request_hash,
                "source_file_sha256": source_file_sha256,
                "transaction_id": transaction_id,
                "receipt_id": receipt_id,
                "receipt_file_id": receipt_file_id,
                "object_key": object_key,
            },
        )

    def record_cleanup_job(
        self,
        bucket_name: str,
        object_key: str,
        reason: str,
        error: str,
    ) -> None:
        self.conn.execute(
            """
            insert into receipt_storage_cleanup_jobs (
                user_id, bucket_name, object_key, reason, status,
                attempt_count, last_error, next_attempt_at
            )
            values (
                %(user_id)s, %(bucket_name)s, %(object_key)s, %(reason)s,
                'retrying', 1, %(error)s, now() + interval '5 minutes'
            )
            on conflict (user_id, bucket_name, object_key) do update
            set status = 'retrying',
                attempt_count = receipt_storage_cleanup_jobs.attempt_count + 1,
                last_error = excluded.last_error,
                next_attempt_at = now() + interval '5 minutes',
                completed_at = null
            """,
            {
                "user_id": self.user_id,
                "bucket_name": bucket_name,
                "object_key": object_key,
                "reason": reason,
                "error": error[:2000],
            },
        )

    def _add_audit_event(self, entity_type: str, entity_id: UUID, action: str) -> None:
        self.conn.execute(
            """
            insert into audit_events (user_id, entity_type, entity_id, action, metadata)
            values (%(user_id)s, %(entity_type)s, %(entity_id)s, %(action)s, '{}'::jsonb)
            """,
            {
                "user_id": self.user_id,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "action": action,
            },
        )


def sanitize_and_validate_filename(filename: str, mime_type: str) -> tuple[str, str]:
    candidate = filename.strip()
    if (
        not candidate
        or "\x00" in candidate
        or "/" in candidate
        or "\\" in candidate
        or candidate in {".", ".."}
    ):
        raise InvalidUploadError("Filename contains an invalid path")

    extension = Path(candidate).suffix.lower()
    normalized_mime = mime_type.strip().lower()
    expected_mime = ALLOWED_RECEIPT_TYPES.get(extension)
    if expected_mime is None:
        raise InvalidUploadError("Unsupported receipt file extension")
    if normalized_mime != expected_mime:
        raise InvalidUploadError("File extension does not match its MIME type")

    stem = candidate[: -len(Path(candidate).suffix)]
    ascii_stem = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode("ascii")
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "-", ascii_stem).strip("-._") or "receipt"
    safe_filename = f"{safe_stem[:200]}{extension}"
    return safe_filename, normalized_mime


class ReceiptFileService:
    def __init__(
        self,
        repository: ReceiptFileRepository,
        storage: ObjectStorage,
        rate_limiter: UploadRateLimiter,
        settings: Settings,
    ) -> None:
        self.repository = repository
        self.storage = storage
        self.rate_limiter = rate_limiter
        self.settings = settings

    def create_receipt_draft(self, payload: ReceiptDraftCreate) -> ReceiptRecord:
        if payload.currency not in self.settings.supported_currencies:
            raise InvalidUploadError(f"Unsupported currency: {payload.currency}")
        return self.repository.create_receipt_draft(payload)

    def create_download_url(self, receipt_id: UUID, file_id: UUID) -> ReceiptFileDownloadUrlResponse:
        owned_file = self.repository.get_file(receipt_id, file_id)
        if owned_file.upload_status != ReceiptFileUploadStatus.UPLOADED:
            raise ConflictError("Receipt file upload has not been confirmed")
        ttl = self.settings.storage_signed_url_ttl_seconds
        url = self.storage.create_signed_download_url(owned_file.bucket_name, owned_file.object_key, ttl)
        return ReceiptFileDownloadUrlResponse(
            file_id=file_id,
            download_url=url,
            expires_at=datetime.now(UTC) + timedelta(seconds=ttl),
        )

    def delete_file(self, receipt_id: UUID, file_id: UUID) -> bool:
        owned_file = self.repository.get_file(receipt_id, file_id)
        try:
            if self.storage.object_exists(owned_file.bucket_name, owned_file.object_key):
                self.storage.delete_object(owned_file.bucket_name, owned_file.object_key)
        except StorageOperationError as error:
            self.repository.record_cleanup_job(
                owned_file.bucket_name,
                owned_file.object_key,
                "receipt_file_delete",
                str(error),
            )
            return False
        self.repository.mark_file_deleted(receipt_id, file_id)
        return True

    def delete_receipt(self, receipt_id: UUID) -> bool:
        receipt = self.repository.get_receipt(receipt_id)
        files = self.repository.list_files(receipt_id)
        cleanup_pending = False
        for owned_file in files:
            try:
                if self.storage.object_exists(owned_file.bucket_name, owned_file.object_key):
                    self.storage.delete_object(owned_file.bucket_name, owned_file.object_key)
            except StorageOperationError as error:
                cleanup_pending = True
                self.repository.record_cleanup_job(
                    owned_file.bucket_name,
                    owned_file.object_key,
                    "receipt_delete",
                    str(error),
                )
        if cleanup_pending:
            return False
        self.repository.delete_transaction(receipt.transaction_id)
        return True

    def delete_transaction(self, transaction_id: UUID) -> bool:
        receipt = self.repository.get_receipt_for_transaction(transaction_id)
        cleanup_pending = False
        if receipt is not None:
            files = self.repository.list_files(receipt.id)
            for owned_file in files:
                try:
                    if self.storage.object_exists(owned_file.bucket_name, owned_file.object_key):
                        self.storage.delete_object(owned_file.bucket_name, owned_file.object_key)
                except StorageOperationError as error:
                    cleanup_pending = True
                    self.repository.record_cleanup_job(
                        owned_file.bucket_name,
                        owned_file.object_key,
                        "transaction_delete",
                        str(error),
                    )
        if cleanup_pending:
            return False
        self.repository.delete_transaction(transaction_id)
        return True

    def _validate_stored_object(self, owned_file: OwnedReceiptFile, metadata: StoredObjectMetadata) -> None:
        if metadata.byte_size > self.settings.max_receipt_file_bytes:
            raise InvalidUploadError(
                f"Receipt file exceeds the {self.settings.max_receipt_file_bytes}-byte limit"
            )
        if owned_file.byte_size is not None and metadata.byte_size != owned_file.byte_size:
            raise InvalidUploadError("Uploaded object size does not match the declared byte size")
        if metadata.mime_type != owned_file.mime_type:
            raise InvalidUploadError("Uploaded object MIME type does not match the upload target")
