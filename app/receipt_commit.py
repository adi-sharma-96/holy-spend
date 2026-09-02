import hashlib
from contextlib import suppress
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

from app.application import ExpenseApplicationService
from app.config import Settings
from app.errors import InvalidUploadError, StorageOperationError
from app.object_storage import ObjectStorage, UploadRateLimiter
from app.plugin_models import ExpenseDraftSaveRequest, ExpenseValidationResult
from app.receipt_downloads import DownloadedReceipt
from app.receipt_extraction import (
    ReceiptCommitRequest,
    ReceiptCommitResult,
    validate_commit_against_download,
)
from app.receipt_files import OwnedReceiptFile, ReceiptRepository
from app.reconciliation import has_blocking_issues
from app.repositories import TransactionRepository


class ReceiptCommitSaga:
    """Create a populated draft and private original as one compensated product operation."""

    def __init__(
        self,
        conn: Any,
        user_id: UUID,
        settings: Settings,
        storage: ObjectStorage,
        rate_limiter: UploadRateLimiter,
    ) -> None:
        self.conn = conn
        self.user_id = user_id
        self.settings = settings
        self.storage = storage
        self.rate_limiter = rate_limiter
        self.receipts = ReceiptRepository(conn, user_id)
        self.application = ExpenseApplicationService(conn, user_id, settings)
        self.compensation_object: tuple[str, str] | None = None

    def commit(
        self,
        request: ReceiptCommitRequest,
        downloaded: DownloadedReceipt,
    ) -> ReceiptCommitResult:
        request_hash = request.stable_hash()
        self.receipts.acquire_commit_lock(request.file_sha256)
        replay = self.receipts.get_commit_result_by_hash(request.file_sha256)
        if replay is not None:
            validation = self._validation_result(replay.transaction_id)
            return ReceiptCommitResult(
                expense=self.application.get_expense(replay.transaction_id),
                receipt_file_id=str(replay.file.id),
                validation=validation,
                idempotent_replay=True,
                exact_file_duplicate=True,
                result_version=replay.result_version,
            )

        self.rate_limiter.check(self.user_id)
        validate_commit_against_download(request, downloaded)
        if request.draft.currency not in self.settings.supported_currencies:
            raise InvalidUploadError(f"Unsupported currency: {request.draft.currency}")

        transaction_id = request.transaction_id
        if transaction_id is None:
            transaction_id = uuid5(self.user_id, f"receipt-file:{request.file_sha256}")
            receipt_id = uuid5(transaction_id, "receipt")
            transaction = TransactionRepository(self.conn, self.user_id).create_draft(
                request.draft.transaction_payload(),
                transaction_id=transaction_id,
                receipt_id=receipt_id,
            )
            transaction = self.application._add_indexed_adjustments(
                transaction,
                ExpenseDraftSaveRequest(
                    draft=request.draft,
                    client_request_id=f"receipt:{request.client_request_id}",
                ),
            )
        else:
            mutation = self.application.save_draft(
                ExpenseDraftSaveRequest(
                    draft=request.draft,
                    transaction_id=transaction_id,
                    expected_revision=request.expected_revision,
                    client_request_id=f"receipt:{request.client_request_id}",
                )
            )
            transaction = mutation.expense.transaction

        receipt = self.receipts.get_receipt_for_transaction(transaction.id)
        if receipt is None:
            raise RuntimeError("The populated receipt draft was created without receipt metadata")

        validation = self._validation_result(transaction.id)
        extension = Path(downloaded.filename).suffix.lower()
        object_key = deterministic_object_key(
            self.user_id,
            receipt.id,
            request.client_request_id,
            downloaded.sha256,
            extension,
        )
        pending = self.receipts.create_pending_file(
            receipt.id,
            self.settings.storage_bucket,
            object_key,
            downloaded.filename,
            downloaded.mime_type,
            downloaded.byte_size,
            downloaded.sha256,
        )
        self.compensation_object = (pending.bucket_name, pending.object_key)
        try:
            if not self.storage.object_exists(pending.bucket_name, pending.object_key):
                self.storage.upload_object(
                    pending.bucket_name,
                    pending.object_key,
                    downloaded.content,
                    downloaded.mime_type,
                )
            metadata = self.storage.confirm_upload(pending.bucket_name, pending.object_key)
            self._validate_stored_file(pending, metadata.byte_size, metadata.mime_type)
            confirmed = self.receipts.confirm_file(
                receipt.id,
                pending.id,
                metadata.byte_size,
                metadata.mime_type,
                downloaded.sha256,
            )
            self.receipts.record_commit_result(
                request.client_request_id,
                request_hash,
                downloaded.sha256,
                transaction.id,
                receipt.id,
                confirmed.id,
                confirmed.object_key,
            )
        except Exception:
            self.compensate("receipt_commit_failed")
            raise

        return ReceiptCommitResult(
            expense=self.application.get_expense(transaction.id),
            receipt_file_id=str(confirmed.id),
            validation=validation,
        )

    def compensate(self, reason: str) -> None:
        if self.compensation_object is None:
            return
        bucket, object_key = self.compensation_object
        try:
            if self.storage.object_exists(bucket, object_key):
                self.storage.delete_object(bucket, object_key)
        except StorageOperationError as error:
            with suppress(Exception):
                self.receipts.record_cleanup_job(bucket, object_key, reason, str(error))
            raise
        else:
            self.compensation_object = None

    def _validation_result(self, transaction_id: UUID) -> ExpenseValidationResult:
        validation = self.application.validate(transaction_id)
        transaction = self.application.transactions.get_transaction(transaction_id)
        computed_total = (
            transaction.total_amount - validation.reconciliation_delta_amount
            if validation.reconciliation_delta_amount is not None
            else None
        )
        return ExpenseValidationResult(
            transaction_id=transaction_id,
            reconciliation_delta_amount=validation.reconciliation_delta_amount,
            computed_total_amount=computed_total,
            issues=validation.issues,
            confirmation_eligible=not has_blocking_issues(validation.issues),
        )

    @staticmethod
    def _validate_stored_file(
        pending: OwnedReceiptFile,
        byte_size: int,
        mime_type: str,
    ) -> None:
        if byte_size != pending.byte_size:
            raise InvalidUploadError("Stored receipt size does not match the analyzed file")
        if mime_type.lower() != pending.mime_type.lower():
            raise InvalidUploadError("Stored receipt MIME type does not match the analyzed file")


def deterministic_object_key(
    user_id: UUID,
    receipt_id: UUID,
    client_request_id: str,
    file_sha256: str,
    extension: str,
) -> str:
    request_digest = hashlib.sha256(client_request_id.encode()).hexdigest()[:16]
    filename = f"{file_sha256[:32]}-{request_digest}{extension}"
    return f"users/{user_id}/receipts/{receipt_id}/{filename}"
