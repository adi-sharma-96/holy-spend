"""WS3 behavior against a disposable PostgreSQL database and restricted role."""

import hashlib
import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from decimal import Decimal
from threading import Event
from typing import Any
from uuid import UUID, uuid5

import psycopg
import pytest
from psycopg.rows import dict_row

from app.application import ExpenseApplicationService
from app.config import Settings
from app.errors import ConflictError, NotFoundError, StorageOperationError
from app.models import TransactionItemUpdate
from app.object_storage import NoOpUploadRateLimiter, StoredObjectMetadata
from app.plugin_models import ExpenseCorrectionRequest, ExpenseDraftInput
from app.receipt_commit import ReceiptCommitSaga, deterministic_object_key
from app.receipt_downloads import DownloadedReceipt
from app.receipt_extraction import ReceiptCommitRequest
from app.receipt_recovery import ReceiptRecoveryRepository
from app.receipt_workflows import (
    AttachmentInput,
    AttachmentProgress,
    BatchInput,
    DocumentEventInput,
    ReceiptWorkflowRepository,
    VersionAttachInput,
)

ADMIN_URL = os.getenv("TEST_ADMIN_DATABASE_URL")
RUNTIME_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not ADMIN_URL or not RUNTIME_URL,
    reason="Set disposable TEST_ADMIN_DATABASE_URL and TEST_DATABASE_URL",
)
OWNER = UUID("a1000000-0000-4000-8000-000000000001")
OTHER = UUID("a1000000-0000-4000-8000-000000000002")
SETTINGS = Settings(_env_file=None)
LEAF = "food_dining.groceries.produce.fruit.apples_pears.apples"


class MemoryStorage:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], StoredObjectMetadata] = {}
        self.uploads = 0
        self.deletes = 0
        self.fail_delete = False

    def object_exists(self, bucket: str, key: str) -> bool:
        return (bucket, key) in self.objects

    def upload_object(self, bucket: str, key: str, content: bytes, mime: str) -> None:
        self.uploads += 1
        self.objects[(bucket, key)] = StoredObjectMetadata(len(content), mime)

    def confirm_upload(self, bucket: str, key: str) -> StoredObjectMetadata:
        return self.objects[(bucket, key)]

    def create_signed_download_url(self, bucket: str, key: str, expires_in: int) -> str:
        raise AssertionError("Synthetic storage never creates signed URLs")

    def delete_object(self, bucket: str, key: str) -> None:
        if self.fail_delete:
            raise StorageOperationError("synthetic delete failure")
        self.deletes += 1
        self.objects.pop((bucket, key), None)


@pytest.fixture
def seeded() -> Iterator[None]:
    assert ADMIN_URL is not None
    with psycopg.connect(ADMIN_URL, row_factory=dict_row) as conn:
        conn.execute("delete from auth.users where id in (%(a)s, %(b)s)", {"a": OWNER, "b": OTHER})
        for user, email in ((OWNER, "ws3-owner@example.test"), (OTHER, "ws3-other@example.test")):
            conn.execute(
                "insert into auth.users (id, email) values (%(id)s, %(email)s)",
                {"id": user, "email": email},
            )
            conn.execute(
                "insert into profiles (id, display_name, default_currency) values (%(id)s, 'WS3 test', 'CAD')",
                {"id": user},
            )
        conn.commit()
    yield
    with psycopg.connect(ADMIN_URL, row_factory=dict_row) as conn:
        conn.execute("delete from auth.users where id in (%(a)s, %(b)s)", {"a": OWNER, "b": OTHER})
        conn.commit()


def runtime(user: UUID) -> Any:
    assert RUNTIME_URL is not None
    conn = psycopg.connect(RUNTIME_URL, row_factory=dict_row)
    conn.execute("select set_config('app.current_user_id', %(id)s, false)", {"id": str(user)})
    return conn


def receipt(index: int) -> DownloadedReceipt:
    content = b"\x89PNG\r\n\x1a\nsynthetic-ws3-" + str(index).encode()
    return DownloadedReceipt(
        content=content,
        filename=f"synthetic-{index}.png",
        mime_type="image/png",
        byte_size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
    )


def draft(index: int, *, adjusted: bool = False) -> ExpenseDraftInput:
    if adjusted:
        return ExpenseDraftInput.model_validate(
            {
                "source_type": "receipt",
                "provider_key": "synthetic_provider",
                "transaction_date": "2026-10-20",
                "merchant_name_raw": "Example Market",
                "currency": "CAD",
                "subtotal_amount": "88.90",
                "tax_amount": "3.88",
                "discount_amount": "5.27",
                "tip_amount": "6.00",
                "total_amount": "93.51",
                "receipt": {"receipt_number": "ORDER-ADJUSTED"},
                "items": [
                    {
                        "raw_name": "Kept substitute apple packet A",
                        "normalized_name": "apple packet A",
                        "taxonomy_node_key": LEAF,
                        "line_subtotal_amount": "44.00",
                        "line_total_amount": "44.00",
                    },
                    {
                        "raw_name": "Kept substitute apple packet B",
                        "normalized_name": "apple packet B",
                        "taxonomy_node_key": LEAF,
                        "line_subtotal_amount": "45.75",
                        "line_total_amount": "45.75",
                    },
                ],
            }
        )
    return ExpenseDraftInput.model_validate(
        {
            "source_type": "receipt",
            "provider_key": "synthetic_provider",
            "transaction_date": "2026-10-20",
            "merchant_name_raw": "Example Market",
            "currency": "CAD",
            "subtotal_amount": "10.00",
            "total_amount": "10.00",
            "receipt": {"receipt_number": f"ORDER-{index}"},
            "items": [
                {
                    "raw_name": "Synthetic apple packet",
                    "normalized_name": "apple packet",
                    "taxonomy_node_key": LEAF,
                    "line_subtotal_amount": "10.00",
                    "line_total_amount": "10.00",
                }
            ],
        }
    )


def commit(conn: Any, storage: MemoryStorage, index: int, *, adjusted: bool = False) -> tuple[ReceiptCommitSaga, Any]:
    file = receipt(index)
    request = ReceiptCommitRequest(
        file_sha256=file.sha256,
        draft=draft(index, adjusted=adjusted),
        client_request_id=f"operation:{index:04d}",
    )
    saga = ReceiptCommitSaga(conn, OWNER, SETTINGS, storage, NoOpUploadRateLimiter())
    result = saga.commit(request, file)
    workflow = ReceiptWorkflowRepository(conn, OWNER)
    workflow.record_version(
        result.expense.transaction.id,
        UUID(result.receipt_file_id),
        kind="original",
        occurred_at=datetime(2026, 10, 20, tzinfo=UTC),
    )
    result = result.model_copy(update={"validation": saga._validation_result(result.expense.transaction.id)})
    return saga, result


def test_twenty_receipts_resume_without_duplicate_purchases(seeded: None) -> None:
    storage = MemoryStorage()
    payload = BatchInput(
        client_batch_id="ws3-twenty",
        authorization_source="user requested add and confirm",
        confirm_authorized=True,
        attachments=[
            AttachmentInput(client_attachment_id=f"attachment:{i:02d}", operation_id=f"operation:{i:04d}")
            for i in range(20)
        ],
    )
    with runtime(OWNER) as conn:
        batch = ReceiptWorkflowRepository(conn, OWNER).start(payload)
        assert len(batch.attachments) == 20
        assert ReceiptWorkflowRepository(conn, OWNER).start(payload).id == batch.id
    with runtime(OTHER) as conn, pytest.raises(NotFoundError):
        ReceiptWorkflowRepository(conn, OTHER).get(batch.id)
    for start, end in ((0, 7), (7, 14), (14, 20)):
        # Each range uses a new connection, as after process/chat interruption.
        with runtime(OWNER) as conn:
            workflow = ReceiptWorkflowRepository(conn, OWNER)
            for index in range(start, end):
                attachment = workflow.get(batch.id).attachments[index]
                workflow.progress(
                    AttachmentProgress(
                        batch_id=batch.id,
                        attachment_id=attachment.id,
                        status="extracting",
                    )
                )
                _saga, saved = commit(conn, storage, index)
                workflow.record_draft(
                    batch.id,
                    attachment.id,
                    operation_id=attachment.operation_id,
                    payload_fingerprint=ReceiptCommitRequest(
                        file_sha256=receipt(index).sha256,
                        draft=draft(index),
                        client_request_id=attachment.operation_id,
                    ).payload_hash(),
                    content_sha256=receipt(index).sha256,
                    transaction_id=saved.expense.transaction.id,
                    receipt_file_id=UUID(saved.receipt_file_id),
                    duplicate=False,
                    issues=[],
                )
                ExpenseApplicationService(conn, OWNER, SETTINGS).confirm(
                    saved.expense.transaction.id,
                    True,
                    saved.validation.reviewed_revision,
                )
    with runtime(OWNER) as conn:
        workflow = ReceiptWorkflowRepository(conn, OWNER)
        resumed = workflow.get(batch.id)
        assert resumed.counts["confirmed"] == 20
        assert (
            conn.execute("select count(*) as count from transactions where user_id=%(id)s", {"id": OWNER}).fetchone()[
                "count"
            ]
            == 20
        )
        assert (
            conn.execute("select count(*) as count from receipt_files where user_id=%(id)s", {"id": OWNER}).fetchone()[
                "count"
            ]
            == 20
        )
        replay_saga = ReceiptCommitSaga(conn, OWNER, SETTINGS, storage, NoOpUploadRateLimiter())
        replay = replay_saga.commit(
            ReceiptCommitRequest(
                file_sha256=receipt(0).sha256, draft=draft(0), client_request_id="different-operation"
            ),
            receipt(0),
        )
        assert replay.exact_file_duplicate
        assert replay.expense.transaction.id == resumed.attachments[0].transaction_id
        assert (
            conn.execute("select count(*) as count from transactions where user_id=%(id)s", {"id": OWNER}).fetchone()[
                "count"
            ]
            == 20
        )
    assert storage.uploads == 20


def test_adjusted_order_documents_and_wallet_events_remain_one_purchase(seeded: None) -> None:
    storage = MemoryStorage()
    with runtime(OWNER) as conn:
        saga, saved = commit(conn, storage, 100, adjusted=True)
        tx_id = saved.expense.transaction.id
        assert saved.validation.reconciliation_delta_amount == Decimal("0.00")
        assert saved.validation.item_subtotal_delta_amount == Decimal("-0.85")
        assert any(issue.code == "subtotal_reconciliation_warning" for issue in saved.validation.issues)
        with pytest.raises(ConflictError, match="Warnings changed"):
            ExpenseApplicationService(conn, OWNER, SETTINGS).confirm(
                tx_id,
                True,
                saved.validation.reviewed_revision,
                "wrong-warning-set",
            )
        ExpenseApplicationService(conn, OWNER, SETTINGS).confirm(
            tx_id,
            True,
            saved.validation.reviewed_revision,
            saved.validation.warning_digest,
        )
        workflow = ReceiptWorkflowRepository(conn, OWNER)
        for index, kind, when in (
            (102, "adjustment", datetime(2026, 10, 22, tzinfo=UTC)),
            (101, "revision", datetime(2026, 10, 21, tzinfo=UTC)),
        ):
            revision = ExpenseApplicationService(conn, OWNER, SETTINGS).get_expense(tx_id).transaction.updated_at
            assert revision is not None
            result = saga.attach_version(
                VersionAttachInput(
                    transaction_id=tx_id,
                    expected_revision=revision,
                    operation_id=f"version:{index}",
                    document_kind=kind,
                    provider_order_key="ORDER-ADJUSTED",
                    occurred_at=when,
                    explicit_approval=True,
                ),
                receipt(index),
            )
            assert result.expense.transaction.id == tx_id
        events = [
            ("charge-original", "original_charge", "92.78"),
            ("order-change", "order_adjustment", "-5.27"),
            ("tip-change", "tip", "6.00"),
            ("wallet-refund", "wallet_refund", "5.27"),
            ("wallet-use", "wallet_use", "5.27"),
        ]
        for source, kind, amount in events:
            revision = ExpenseApplicationService(conn, OWNER, SETTINGS).get_expense(tx_id).transaction.updated_at
            assert revision is not None
            request = DocumentEventInput(
                transaction_id=tx_id,
                expected_revision=revision,
                source_key=source,
                event_kind=kind,
                amount=Decimal(amount),
                currency="CAD",
                item_id=saved.expense.transaction.items[0].id if kind == "order_adjustment" else None,
                item_disposition="kept" if kind == "order_adjustment" else "unknown",
                attribution_status="known" if kind == "order_adjustment" else "unknown",
                explicit_approval=True,
            )
            assert not workflow.record_event(request)["idempotent_replay"]
            assert workflow.record_event(request)["idempotent_replay"]
            with pytest.raises(ConflictError, match="different facts"):
                workflow.record_event(request.model_copy(update={"amount": Decimal("99.00")}))
        timeline = workflow.timeline(tx_id)
        assert len(timeline["versions"]) == 3
        assert len(timeline["events"]) == 5
        assert [v["document_kind"] for v in timeline["versions"]] == ["original", "revision", "adjustment"]
        assert (
            conn.execute("select count(*) as count from transactions where user_id=%(id)s", {"id": OWNER}).fetchone()[
                "count"
            ]
            == 1
        )
        total = conn.execute("select total_amount from transactions where id=%(id)s", {"id": tx_id}).fetchone()[
            "total_amount"
        ]
        assert total == Decimal("93.51")
        previous_item_id = saved.expense.transaction.items[0].id
        correction_draft = draft(100, adjusted=True)
        current_items = ExpenseApplicationService(conn, OWNER, SETTINGS).get_expense(tx_id).transaction.items
        correction_draft.items = [
            item.model_copy(update={"existing_item_id": current_items[index].id})
            for index, item in enumerate(correction_draft.items)
        ]
        revision = ExpenseApplicationService(conn, OWNER, SETTINGS).get_expense(tx_id).transaction.updated_at
        assert revision is not None
        ExpenseApplicationService(conn, OWNER, SETTINGS).correct_confirmed(
            ExpenseCorrectionRequest(
                transaction_id=tx_id,
                expected_revision=revision,
                draft=correction_draft,
                correction_reason="Verified synthetic packet detail",
                explicit_approval=True,
                client_request_id="correction:lineage",
            )
        )
        changed_event = next(
            event for event in workflow.timeline(tx_id)["events"] if event["source_key"] == "order-change"
        )
        assert changed_event["source_item_id"] == previous_item_id
        assert changed_event["item_id"] != previous_item_id
        assert changed_event["item_id"] is not None
    with runtime(OTHER) as conn, pytest.raises(NotFoundError):
        ReceiptWorkflowRepository(conn, OTHER).timeline(tx_id)


def test_concurrent_exact_file_replay_creates_one_purchase(seeded: None) -> None:
    storage = MemoryStorage()

    def save(operation_id: str) -> tuple[UUID, bool]:
        file = receipt(200)
        with runtime(OWNER) as conn:
            saga = ReceiptCommitSaga(conn, OWNER, SETTINGS, storage, NoOpUploadRateLimiter())
            result = saga.commit(
                ReceiptCommitRequest(file_sha256=file.sha256, draft=draft(200), client_request_id=operation_id),
                file,
            )
            return result.expense.transaction.id, result.exact_file_duplicate

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, ("concurrent:first", "concurrent:second")))
    assert results[0][0] == results[1][0]
    assert sorted(result[1] for result in results) == [False, True]
    assert storage.uploads == 1
    with runtime(OWNER) as conn:
        count = conn.execute(
            "select count(*) as count from transactions where user_id=%(id)s", {"id": OWNER}
        ).fetchone()["count"]
        assert count == 1


def test_staged_upload_recovery_handles_orphan_failure_and_adoption(seeded: None) -> None:
    storage = MemoryStorage()
    file = receipt(300)
    receipt_id = uuid5(uuid5(OWNER, f"receipt-file:{file.sha256}"), "receipt")
    key = deterministic_object_key(OWNER, receipt_id, "operation:0300", file.sha256, ".png")
    with runtime(OWNER) as conn:
        attempt = ReceiptRecoveryRepository(conn, OWNER).stage(SETTINGS.storage_bucket, key, file.sha256)
        assert attempt is not None
    storage.upload_object(SETTINGS.storage_bucket, key, file.content, file.mime_type)
    storage.fail_delete = True
    with runtime(OWNER) as conn:
        recovery = ReceiptRecoveryRepository(conn, OWNER)
        assert recovery.recover(attempt.job_id, storage)["status"] == "retrying"
        assert recovery.list_unresolved()[0]["attempt_count"] == 1
    storage.fail_delete = False
    with runtime(OWNER) as conn:
        assert ReceiptRecoveryRepository(conn, OWNER).recover(
            attempt.job_id, storage, finished_attempt_id=attempt.attempt_id
        )["status"] == "completed"
    assert not storage.object_exists(SETTINGS.storage_bucket, key)

    with runtime(OWNER) as conn:
        adopted_attempt = ReceiptRecoveryRepository(conn, OWNER).stage(SETTINGS.storage_bucket, key, file.sha256)
        assert adopted_attempt is not None
    with runtime(OWNER) as conn:
        _saga, saved = commit(conn, storage, 300)
        assert saved.expense.transaction.id
    with runtime(OWNER) as conn:
        outcome = ReceiptRecoveryRepository(conn, OWNER).recover(adopted_attempt.job_id, storage)
        assert outcome["status"] == "completed"
        assert outcome["adopted"] is True
    assert storage.object_exists(SETTINGS.storage_bucket, key)


def test_early_cleanup_keeps_intent_until_late_upload_is_removed(seeded: None) -> None:
    storage = MemoryStorage()
    file = receipt(301)
    key = f"users/{OWNER}/receipts/late-{file.sha256}.png"
    with runtime(OWNER) as conn:
        attempt = ReceiptRecoveryRepository(conn, OWNER).stage(SETTINGS.storage_bucket, key, file.sha256)
        assert attempt is not None
    with runtime(OWNER) as conn:
        recovery = ReceiptRecoveryRepository(conn, OWNER)
        assert recovery.recover(attempt.job_id, storage)["reason"] == "upload_not_observed"
        assert len(recovery.list_unresolved()) == 1
    storage.upload_object(SETTINGS.storage_bucket, key, file.content, file.mime_type)
    with runtime(OWNER) as conn:
        assert ReceiptRecoveryRepository(conn, OWNER).recover(attempt.job_id, storage)["status"] == "retrying"
        assert len(ReceiptRecoveryRepository(conn, OWNER).list_unresolved()) == 1
    assert not storage.object_exists(SETTINGS.storage_bucket, key)
    with runtime(OWNER) as conn:
        recovery = ReceiptRecoveryRepository(conn, OWNER)
        assert recovery.recover(
            attempt.job_id, storage, finished_attempt_id=attempt.attempt_id
        )["status"] == "completed"
        finished_attempt = recovery.stage(SETTINGS.storage_bucket, key + "-never-started", file.sha256)
        assert finished_attempt is not None
        assert recovery.recover(
            finished_attempt.job_id, storage, finished_attempt_id=finished_attempt.attempt_id
        )["status"] == "completed"


def test_overlapping_retries_keep_each_upload_protected(seeded: None) -> None:
    storage = MemoryStorage()
    file = receipt(304)
    key = f"users/{OWNER}/receipts/overlap-{file.sha256}.png"
    with runtime(OWNER) as conn:
        attempt_a = ReceiptRecoveryRepository(conn, OWNER).stage(SETTINGS.storage_bucket, key, file.sha256)
        assert attempt_a is not None
    with runtime(OWNER) as conn:
        attempt_b = ReceiptRecoveryRepository(conn, OWNER).stage(SETTINGS.storage_bucket, key, file.sha256)
        assert attempt_b is not None
    assert attempt_a.job_id == attempt_b.job_id
    assert attempt_a.attempt_id != attempt_b.attempt_id

    with runtime(OWNER) as conn:
        recovery = ReceiptRecoveryRepository(conn, OWNER)
        assert recovery.recover(
            attempt_a.job_id, storage, finished_attempt_id=attempt_a.attempt_id
        )["status"] == "retrying"
        assert len(recovery.list_unresolved()) == 1
        with pytest.raises(ConflictError, match="no longer active"):
            recovery.assert_active_attempt(attempt_a, SETTINGS.storage_bucket, key, file.sha256)
        recovery.assert_active_attempt(attempt_b, SETTINGS.storage_bucket, key, file.sha256)

    # B uploads after A has finished, then loses its purchase transaction.
    storage.upload_object(SETTINGS.storage_bucket, key, file.content, file.mime_type)
    with runtime(OWNER) as conn:
        recovery = ReceiptRecoveryRepository(conn, OWNER)
        assert recovery.recover(attempt_b.job_id, storage)["status"] == "retrying"
        assert len(recovery.list_unresolved()) == 1
    assert not storage.object_exists(SETTINGS.storage_bucket, key)
    with runtime(OWNER) as conn:
        recovery = ReceiptRecoveryRepository(conn, OWNER)
        assert recovery.recover(
            attempt_b.job_id, storage, finished_attempt_id=attempt_b.attempt_id
        )["status"] == "completed"
        assert recovery.list_unresolved() == []


def test_finished_attempt_cannot_start_a_late_upload(seeded: None) -> None:
    storage = MemoryStorage()
    file = receipt(305)
    operation_id = "operation:0305"
    receipt_id = uuid5(uuid5(OWNER, f"receipt-file:{file.sha256}"), "receipt")
    key = deterministic_object_key(OWNER, receipt_id, operation_id, file.sha256, ".png")
    with runtime(OWNER) as conn:
        attempt = ReceiptRecoveryRepository(conn, OWNER).stage(SETTINGS.storage_bucket, key, file.sha256)
        assert attempt is not None
    with runtime(OWNER) as conn:
        assert ReceiptRecoveryRepository(conn, OWNER).recover(
            attempt.job_id, storage, finished_attempt_id=attempt.attempt_id
        )["status"] == "completed"
    with runtime(OWNER) as conn:
        saga = ReceiptCommitSaga(
            conn, OWNER, SETTINGS, storage, NoOpUploadRateLimiter(),
            recovery_attempt=attempt, require_staged_upload=True,
        )
        with pytest.raises(ConflictError, match="no longer active"):
            saga.commit(ReceiptCommitRequest(
                file_sha256=file.sha256, draft=draft(305), client_request_id=operation_id
            ), file)
    assert storage.uploads == 0
    assert not storage.object_exists(SETTINGS.storage_bucket, key)


def test_replayed_saved_draft_remains_confirmable(seeded: None) -> None:
    storage = MemoryStorage()
    with runtime(OWNER) as conn:
        workflow = ReceiptWorkflowRepository(conn, OWNER)
        batch = workflow.start(BatchInput(
            client_batch_id="replayed-draft-batch",
            authorization_source="user approved batch confirmation",
            confirm_authorized=True,
            attachments=[AttachmentInput(
                client_attachment_id="replayed-attachment", operation_id="operation:0302"
            )],
        ))
        attachment = batch.attachments[0]
        workflow.progress(AttachmentProgress(
            batch_id=batch.id, attachment_id=attachment.id, status="extracting"
        ))
        _saga, saved = commit(conn, storage, 302)
        request = ReceiptCommitRequest(
            file_sha256=receipt(302).sha256, draft=draft(302), client_request_id="operation:0302"
        )
        for duplicate in (False, True):
            workflow.record_draft(
                batch.id, attachment.id, operation_id=attachment.operation_id,
                payload_fingerprint=request.payload_hash(), content_sha256=receipt(302).sha256,
                transaction_id=saved.expense.transaction.id,
                receipt_file_id=UUID(saved.receipt_file_id), duplicate=duplicate, issues=[],
            )
        assert workflow.get(batch.id).attachments[0].status == "draft_saved"
        assert workflow.authorized_transaction(batch.id, attachment.id) == saved.expense.transaction.id
        ExpenseApplicationService(conn, OWNER, SETTINGS).confirm(
            saved.expense.transaction.id, True, saved.validation.reviewed_revision
        )
        assert workflow.get(batch.id).attachments[0].status == "confirmed"


def test_item_edit_waiting_on_confirmation_requires_correction(seeded: None) -> None:
    storage = MemoryStorage()
    entered = Event()
    with runtime(OWNER) as creating:
        _saga, saved = commit(creating, storage, 303)
    transaction_id = saved.expense.transaction.id
    item_id = saved.expense.transaction.items[0].id

    with runtime(OWNER) as confirming:
        confirming.execute(
            "select id from transactions where id=%(id)s for update", {"id": transaction_id}
        )

        def edit_without_reason() -> str:
            with runtime(OWNER) as editing:
                entered.set()
                with pytest.raises(ConflictError, match="correction_reason"):
                    ExpenseApplicationService(editing, OWNER, SETTINGS).transactions.update_item(
                        transaction_id, item_id, TransactionItemUpdate(quantity=Decimal("99"))
                    )
            return "rejected"

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(edit_without_reason)
            assert entered.wait(timeout=5)
            ExpenseApplicationService(confirming, OWNER, SETTINGS).confirm(
                transaction_id, True, saved.validation.reviewed_revision
            )
            confirming.commit()
        assert future.result(timeout=5) == "rejected"
    with runtime(OWNER) as conn:
        row = conn.execute(
            "select status from transactions where id=%(id)s", {"id": transaction_id}
        ).fetchone()
        item = conn.execute(
            "select quantity from transaction_items where id=%(id)s", {"id": item_id}
        ).fetchone()
        assert row["status"] == "confirmed"
        assert item["quantity"] != Decimal("99")
        with pytest.raises(psycopg.errors.RaiseException, match="approved correction"):
            conn.execute(
                "update transaction_items set quantity=99 where id=%(id)s", {"id": item_id}
            )


def test_batch_clarification_retry_scope_and_stale_child_revision(seeded: None) -> None:
    payload = BatchInput(
        client_batch_id="clarification-batch",
        authorization_source="user requested draft review",
        confirm_authorized=False,
        attachments=[
            AttachmentInput(client_attachment_id="attachment:clarify", operation_id="operation:clarify"),
            AttachmentInput(client_attachment_id="attachment:retry", operation_id="operation:retry"),
        ],
    )
    with runtime(OWNER) as conn:
        workflow = ReceiptWorkflowRepository(conn, OWNER)
        batch = workflow.start(payload)
        first, second = batch.attachments
        workflow.progress(
            AttachmentProgress(
                batch_id=batch.id,
                attachment_id=first.id,
                status="extracting",
            )
        )
        workflow.progress(
            AttachmentProgress(
                batch_id=batch.id,
                attachment_id=first.id,
                status="clarification_needed",
                questions=["Which packet was kept?"],
            )
        )
        workflow.progress(
            AttachmentProgress(
                batch_id=batch.id,
                attachment_id=second.id,
                status="retryable_failure",
                retry_reason="download_expired",
            )
        )
        with pytest.raises(ConflictError, match="different batch"):
            workflow.start(payload.model_copy(update={"confirm_authorized": True}))
    with runtime(OWNER) as conn:
        workflow = ReceiptWorkflowRepository(conn, OWNER)
        resumed = workflow.get(batch.id)
        assert resumed.counts["clarification_needed"] == 1
        assert resumed.counts["retryable_failure"] == 1
        assert resumed.attachments[0].unresolved_issues[0]["question"] == "Which packet was kept?"
        assert (
            workflow.progress(
                AttachmentProgress(
                    batch_id=batch.id,
                    attachment_id=second.id,
                    status="extracting",
                )
            )
            .attachments[1]
            .attempt_count
            == 1
        )
        with pytest.raises(ConflictError, match="did not authorize"):
            workflow.authorized_transaction(batch.id, first.id)
    with runtime(OTHER) as conn, pytest.raises(NotFoundError):
        ReceiptWorkflowRepository(conn, OTHER).progress(
            AttachmentProgress(
                batch_id=batch.id,
                attachment_id=second.id,
                status="extracting",
            )
        )

    storage = MemoryStorage()
    with runtime(OWNER) as conn:
        _saga, saved = commit(conn, storage, 401)
        workflow = ReceiptWorkflowRepository(conn, OWNER)
        tx_id = saved.expense.transaction.id
        assert (
            workflow.find_order_candidate(
                "synthetic_provider", "ORDER-401", "CAD", date(2026, 10, 20), receipt(402).sha256
            )
            == tx_id
        )
        assert (
            workflow.find_order_candidate(
                "synthetic_provider", "ORDER-401", "CAD", date(2026, 10, 21), receipt(402).sha256
            )
            is None
        )
        item_id = saved.expense.transaction.items[0].id
        conn.execute(
            "update transaction_items set raw_name='Edited synthetic packet' where id=%(id)s and user_id=%(user_id)s",
            {"id": item_id, "user_id": OWNER},
        )
        with pytest.raises(ConflictError, match="revision changed"):
            ExpenseApplicationService(conn, OWNER, SETTINGS).confirm(
                tx_id,
                True,
                saved.validation.reviewed_revision,
            )
