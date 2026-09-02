import hashlib
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest

import app.receipt_commit as receipt_commit_module
from app.config import Settings
from app.errors import StorageOperationError
from app.models import (
    ReceiptFileUploadStatus,
    ReceiptRecord,
    TransactionDetail,
    TransactionStatus,
    TransactionType,
    ValidationResponse,
)
from app.object_storage import NoOpUploadRateLimiter, StoredObjectMetadata
from app.plugin_models import ExpenseDraftInput, ExpenseSnapshot, ReceiptSnapshot
from app.receipt_commit import ReceiptCommitSaga
from app.receipt_downloads import DownloadedReceipt
from app.receipt_extraction import ReceiptCommitRequest
from app.receipt_files import OwnedReceiptFile, ReceiptCommitReplay

USER_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
TRANSACTION_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
RECEIPT_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
NOW = datetime(2026, 7, 28, tzinfo=UTC)
CONTENT = b"\x89PNG\r\n\x1a\npopulated receipt"
FILE_HASH = hashlib.sha256(CONTENT).hexdigest()


def transaction() -> TransactionDetail:
    return TransactionDetail(
        id=TRANSACTION_ID,
        transaction_type=TransactionType.EXPENSE,
        source_type="receipt",
        status=TransactionStatus.DRAFT,
        transaction_date=date(2026, 7, 28),
        merchant_name_raw="Market",
        merchant_name_normalized="Market",
        currency="CAD",
        subtotal_amount=Decimal("10.00"),
        tax_amount=Decimal("1.30"),
        fee_amount=None,
        discount_amount=None,
        tip_amount=None,
        deposit_amount=None,
        rounding_amount=None,
        total_amount=Decimal("11.30"),
        reconciliation_delta_amount=Decimal("0"),
        confirmed_at=None,
        created_at=NOW,
        updated_at=NOW,
    )


def commit_request(**updates: Any) -> ReceiptCommitRequest:
    values: dict[str, Any] = {
        "file_sha256": FILE_HASH,
        "draft": ExpenseDraftInput(
            source_type="receipt",
            transaction_date="2026-07-28",
            merchant_name_raw="Market",
            merchant_name_normalized="Market",
            currency="CAD",
            subtotal_amount="10.00",
            tax_amount="1.30",
            total_amount="11.30",
            receipt={},
            items=[
                {
                    "raw_name": "Bread",
                    "normalized_name": "bread",
                    "category_slug": "uncategorized",
                    "line_total_amount": "10.00",
                }
            ],
        ),
        "client_request_id": f"sha256:{FILE_HASH}",
    }
    values.update(updates)
    return ReceiptCommitRequest.model_validate(values)


def downloaded() -> DownloadedReceipt:
    return DownloadedReceipt(
        content=CONTENT,
        filename="receipt.png",
        mime_type="image/png",
        byte_size=len(CONTENT),
        sha256=FILE_HASH,
    )


class FakeStorage:
    def __init__(self, *, fail_upload: bool = False, fail_delete: bool = False) -> None:
        self.objects: dict[tuple[str, str], StoredObjectMetadata] = {}
        self.deleted: list[str] = []
        self.upload_calls = 0
        self.fail_upload = fail_upload
        self.fail_delete = fail_delete

    def object_exists(self, bucket: str, key: str) -> bool:
        return (bucket, key) in self.objects

    def upload_object(self, bucket: str, key: str, content: bytes, mime: str) -> None:
        self.upload_calls += 1
        self.objects[(bucket, key)] = StoredObjectMetadata(len(content), mime)
        if self.fail_upload:
            raise StorageOperationError("storage unavailable after write")

    def confirm_upload(self, bucket: str, key: str) -> StoredObjectMetadata:
        return self.objects[(bucket, key)]

    def delete_object(self, bucket: str, key: str) -> None:
        if self.fail_delete:
            raise StorageOperationError("storage cleanup unavailable")
        self.objects.pop((bucket, key), None)
        self.deleted.append(key)


class FakeTransactions:
    def __init__(self) -> None:
        self.create_calls = 0

    def create_draft(self, _payload: object, **_ids: object) -> TransactionDetail:
        self.create_calls += 1
        return transaction()

    def get_transaction(self, _transaction_id: UUID) -> TransactionDetail:
        return transaction()


class FakeApplication:
    def __init__(self, transactions: FakeTransactions) -> None:
        self.transactions = transactions

    def _add_indexed_adjustments(self, current: TransactionDetail, *_args: object) -> TransactionDetail:
        return current

    def validate(self, _transaction_id: UUID) -> ValidationResponse:
        return ValidationResponse(
            transaction_id=TRANSACTION_ID,
            reconciliation_delta_amount=Decimal("0"),
            issues=[],
        )

    def get_expense(self, _transaction_id: UUID) -> ExpenseSnapshot:
        return ExpenseSnapshot(
            transaction=transaction(),
            receipt=ReceiptSnapshot(
                receipt=ReceiptRecord(id=RECEIPT_ID, transaction_id=TRANSACTION_ID, created_at=NOW),
                files=[],
            ),
        )


class FakeReceipts:
    def __init__(self, *, fail_confirm: bool = False) -> None:
        self.file: OwnedReceiptFile | None = None
        self.replay: ReceiptCommitReplay | None = None
        self.fail_confirm = fail_confirm
        self.commit_records = 0
        self.cleanup_jobs: list[str] = []

    def acquire_commit_lock(self, _source_hash: str) -> None:
        return None

    def get_commit_result_by_hash(self, _source_hash: str) -> ReceiptCommitReplay | None:
        return self.replay

    def get_receipt_for_transaction(self, _transaction_id: UUID) -> ReceiptRecord:
        return ReceiptRecord(id=RECEIPT_ID, transaction_id=TRANSACTION_ID, created_at=NOW)

    def create_pending_file(
        self,
        _receipt_id: UUID,
        bucket: str,
        key: str,
        filename: str,
        mime: str,
        byte_size: int,
        sha256: str,
    ) -> OwnedReceiptFile:
        self.file = OwnedReceiptFile(
            id=uuid4(),
            user_id=USER_ID,
            receipt_id=RECEIPT_ID,
            storage_provider="supabase",
            bucket_name=bucket,
            object_key=key,
            original_filename=filename,
            mime_type=mime,
            byte_size=byte_size,
            sha256=sha256,
            upload_status=ReceiptFileUploadStatus.PENDING,
            created_at=NOW,
            uploaded_at=None,
            deleted_at=None,
        )
        return self.file

    def confirm_file(
        self,
        _receipt_id: UUID,
        _file_id: UUID,
        _byte_size: int,
        _mime: str,
        _sha256: str,
    ) -> OwnedReceiptFile:
        if self.fail_confirm:
            raise RuntimeError("database metadata failure")
        assert self.file is not None
        self.file = replace(
            self.file,
            upload_status=ReceiptFileUploadStatus.UPLOADED,
            uploaded_at=NOW,
        )
        return self.file

    def record_commit_result(
        self,
        _request_id: str,
        request_hash: str,
        source_hash: str,
        _transaction_id: UUID,
        _receipt_id: UUID,
        _file_id: UUID,
        _object_key: str,
    ) -> None:
        assert self.file is not None
        self.commit_records += 1
        self.replay = ReceiptCommitReplay(
            request_hash=request_hash,
            source_file_sha256=source_hash,
            transaction_id=TRANSACTION_ID,
            receipt_id=RECEIPT_ID,
            file=self.file,
            result_version=1,
        )

    def record_cleanup_job(
        self,
        _bucket: str,
        key: str,
        _reason: str,
        _last_error: str,
    ) -> None:
        self.cleanup_jobs.append(key)


def make_saga(
    monkeypatch: pytest.MonkeyPatch,
    *,
    storage: FakeStorage | None = None,
    receipts: FakeReceipts | None = None,
) -> tuple[ReceiptCommitSaga, FakeTransactions, FakeReceipts, FakeStorage]:
    transactions = FakeTransactions()
    active_receipts = receipts or FakeReceipts()
    active_storage = storage or FakeStorage()
    monkeypatch.setattr(receipt_commit_module, "TransactionRepository", lambda *_args: transactions)
    saga = ReceiptCommitSaga(
        object(),
        USER_ID,
        Settings(_env_file=None),
        active_storage,  # type: ignore[arg-type]
        NoOpUploadRateLimiter(),
    )
    saga.receipts = active_receipts  # type: ignore[assignment]
    saga.application = FakeApplication(transactions)  # type: ignore[assignment]
    return saga, transactions, active_receipts, active_storage


def test_candidate_commit_creates_populated_draft_and_linked_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saga, transactions, receipts, storage = make_saga(monkeypatch)

    result = saga.commit(commit_request(), downloaded())

    assert result.expense.transaction.merchant_name_raw == "Market"
    assert result.receipt_file_id == str(receipts.file.id)  # type: ignore[union-attr]
    assert transactions.create_calls == 1
    assert receipts.commit_records == 1
    assert storage.upload_calls == 1
    assert len(storage.objects) == 1


def test_same_idempotency_key_replays_without_duplicate_draft_or_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saga, transactions, _receipts, storage = make_saga(monkeypatch)
    first = saga.commit(commit_request(), downloaded())
    saga.compensation_object = None
    replay = saga.commit(commit_request(), downloaded())

    assert replay.idempotent_replay is True
    assert replay.exact_file_duplicate is True
    assert replay.receipt_file_id == first.receipt_file_id
    assert transactions.create_calls == 1
    assert storage.upload_calls == 1


def test_same_exact_file_with_different_retry_metadata_returns_existing_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saga, _transactions, _receipts, storage = make_saga(monkeypatch)
    first = saga.commit(commit_request(), downloaded())
    saga.compensation_object = None

    replay = saga.commit(
        commit_request(
            draft=commit_request().draft.model_copy(
                update={"total_amount": Decimal("12.00")}
            )
        ),
        downloaded(),
    )

    assert replay.expense.transaction.id == first.expense.transaction.id
    assert replay.exact_file_duplicate is True
    assert storage.upload_calls == 1


def test_storage_failure_cleans_object_and_never_records_completed_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saga, _transactions, receipts, storage = make_saga(
        monkeypatch,
        storage=FakeStorage(fail_upload=True),
    )

    with pytest.raises(StorageOperationError):
        saga.commit(commit_request(), downloaded())

    assert storage.objects == {}
    assert len(storage.deleted) == 1
    assert receipts.commit_records == 0


def test_database_metadata_failure_cleans_uploaded_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saga, _transactions, receipts, storage = make_saga(
        monkeypatch,
        receipts=FakeReceipts(fail_confirm=True),
    )

    with pytest.raises(RuntimeError, match="database metadata failure"):
        saga.commit(commit_request(), downloaded())

    assert storage.objects == {}
    assert len(storage.deleted) == 1
    assert receipts.commit_records == 0


def test_failed_compensation_records_retryable_cleanup_and_retains_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saga, _transactions, receipts, storage = make_saga(
        monkeypatch,
        receipts=FakeReceipts(fail_confirm=True),
        storage=FakeStorage(fail_delete=True),
    )

    with pytest.raises(StorageOperationError, match="cleanup unavailable"):
        saga.commit(commit_request(), downloaded())

    assert len(storage.objects) == 1
    assert receipts.cleanup_jobs
    assert saga.compensation_object is not None
