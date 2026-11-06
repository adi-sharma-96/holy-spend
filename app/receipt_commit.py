import hashlib
from contextlib import suppress
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

from app.application import ExpenseApplicationService
from app.config import Settings
from app.errors import ConflictError, InvalidUploadError, StorageOperationError
from app.models import TransactionStatus
from app.object_storage import ObjectStorage, UploadRateLimiter
from app.plugin_models import ExpenseDraftSaveRequest, ExpenseValidationResult
from app.receipt_downloads import DownloadedReceipt
from app.receipt_extraction import (
    ReceiptCommitRequest,
    ReceiptCommitResult,
    validate_commit_against_download,
)
from app.receipt_files import OwnedReceiptFile, ReceiptRepository
from app.receipt_recovery import CleanupAttempt, ReceiptRecoveryRepository
from app.receipt_workflows import ReceiptWorkflowRepository, VersionAttachInput, fingerprint
from app.reconciliation import ReconciliationService, has_blocking_issues, item_gross_total
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
        recovery_attempt: CleanupAttempt | None = None,
        require_staged_upload: bool = False,
    ) -> None:
        self.conn = conn
        self.user_id = user_id
        self.settings = settings
        self.storage = storage
        self.rate_limiter = rate_limiter
        self.recovery_attempt = recovery_attempt
        self.require_staged_upload = require_staged_upload
        self.receipts = ReceiptRepository(conn, user_id)
        self.application = ExpenseApplicationService(conn, user_id, settings)
        self.compensation_object: tuple[str, str] | None = None

    def commit(
        self,
        request: ReceiptCommitRequest,
        downloaded: DownloadedReceipt,
    ) -> ReceiptCommitResult:
        request_hash = request.payload_hash()
        self.receipts.acquire_commit_lock(request.file_sha256)
        replay = self.receipts.get_commit_result_by_hash(request.file_sha256)
        if replay is not None:
            if replay.request_hash not in {request_hash, request.stable_hash()}:
                raise ConflictError(
                    "Receipt bytes are already linked to another intent; review the existing transaction"
                )
            validation = self._validation_result(replay.transaction_id, persist=False)
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
        self._assert_upload_protected(pending, downloaded.sha256)
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

    def attach_version(self, request: VersionAttachInput, downloaded: DownloadedReceipt) -> ReceiptCommitResult:
        """Attach another original to one reviewed purchase without another expense."""
        if not request.explicit_approval:
            raise ConflictError("Explicit approval is required to attach a confirmed purchase document")
        intent_hash = fingerprint(
            {
                "transaction_id": request.transaction_id,
                "file_sha256": downloaded.sha256,
                "document_kind": request.document_kind,
                "provider_order_key": request.provider_order_key,
                "occurred_at": request.occurred_at,
                "supersedes_file_id": request.supersedes_file_id,
                "extracted_facts": request.extracted_facts,
            }
        )
        self.receipts.acquire_commit_lock(downloaded.sha256)
        replay = self.receipts.get_commit_result_by_hash(downloaded.sha256)
        if replay is not None:
            if replay.transaction_id != request.transaction_id or replay.request_hash != intent_hash:
                raise ConflictError("These receipt bytes are already linked to a different document intent")
            return ReceiptCommitResult(
                expense=self.application.get_expense(replay.transaction_id),
                receipt_file_id=str(replay.file.id),
                validation=self._validation_result(replay.transaction_id, persist=False),
                idempotent_replay=True,
                exact_file_duplicate=True,
            )
        status, revision = self.application.transactions.lock_draft(request.transaction_id)
        if status != TransactionStatus.CONFIRMED or revision != request.expected_revision:
            raise ConflictError("Purchase changed; review its current revision before attaching a document")
        receipt = self.receipts.get_receipt_for_transaction(request.transaction_id)
        if receipt is None:
            raise ConflictError("Purchase has no receipt record")
        self.rate_limiter.check(self.user_id)
        extension = Path(downloaded.filename).suffix.lower()
        object_key = deterministic_object_key(
            self.user_id, receipt.id, request.operation_id, downloaded.sha256, extension
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
        self._assert_upload_protected(pending, downloaded.sha256)
        self.compensation_object = (pending.bucket_name, pending.object_key)
        try:
            if not self.storage.object_exists(pending.bucket_name, pending.object_key):
                self.storage.upload_object(
                    pending.bucket_name, pending.object_key, downloaded.content, downloaded.mime_type
                )
            metadata = self.storage.confirm_upload(pending.bucket_name, pending.object_key)
            self._validate_stored_file(pending, metadata.byte_size, metadata.mime_type)
            confirmed = self.receipts.confirm_file(
                receipt.id, pending.id, metadata.byte_size, metadata.mime_type, downloaded.sha256
            )
            ReceiptWorkflowRepository(self.conn, self.user_id).record_version(
                request.transaction_id,
                confirmed.id,
                kind=request.document_kind,
                order_key=request.provider_order_key,
                occurred_at=request.occurred_at,
                supersedes_file_id=request.supersedes_file_id,
                extracted_facts=request.extracted_facts,
            )
            self.receipts.record_commit_result(
                request.operation_id,
                intent_hash,
                downloaded.sha256,
                request.transaction_id,
                receipt.id,
                confirmed.id,
                confirmed.object_key,
            )
        except Exception:
            self.compensate("receipt_version_attach_failed")
            raise
        validation = self._validation_result(request.transaction_id)
        return ReceiptCommitResult(
            expense=self.application.get_expense(request.transaction_id),
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

    def _assert_upload_protected(self, pending: OwnedReceiptFile, source_sha256: str) -> None:
        if not self.require_staged_upload:
            return
        if self.recovery_attempt is None:
            raise ConflictError("Upload cleanup protection is required")
        ReceiptRecoveryRepository(self.conn, self.user_id).assert_active_attempt(
            self.recovery_attempt, pending.bucket_name, pending.object_key, source_sha256
        )

    def _validation_result(self, transaction_id: UUID, *, persist: bool = True) -> ExpenseValidationResult:
        if persist:
            validation = self.application.validate(transaction_id)
            delta, issues = validation.reconciliation_delta_amount, validation.issues
        else:
            current = self.application.transactions.get_transaction(transaction_id)
            delta, issues = ReconciliationService(self.settings).validate(current)
        transaction = self.application.transactions.get_transaction(transaction_id)
        computed_items = item_gross_total(transaction) if transaction.items else None
        item_delta = (
            (transaction.subtotal_amount - computed_items).quantize(Decimal("0.01"))
            if transaction.subtotal_amount is not None and computed_items is not None
            else None
        )
        warnings = [
            {"code": issue.code, "metadata": issue.metadata} for issue in issues if issue.severity.value == "warning"
        ]
        computed_total = transaction.total_amount - delta if delta is not None else None
        return ExpenseValidationResult(
            transaction_id=transaction_id,
            reconciliation_delta_amount=delta,
            computed_total_amount=computed_total,
            item_subtotal_delta_amount=item_delta,
            printed_subtotal_amount=transaction.subtotal_amount,
            computed_item_subtotal_amount=computed_items,
            reviewed_revision=transaction.updated_at,
            warning_digest=fingerprint(warnings) if warnings else None,
            issues=issues,
            confirmation_eligible=not has_blocking_issues(issues),
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
