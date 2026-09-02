from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

import pytest

from app.application import ExpenseApplicationService
from app.config import Settings
from app.errors import ConflictError
from app.models import SourceType, TransactionDetail, TransactionStatus, TransactionType
from app.plugin_models import ExpenseDraftInput, ExpenseDraftSaveRequest

USER_ID = UUID("11111111-1111-4111-8111-111111111111")
TRANSACTION_ID = UUID("22222222-2222-4222-8222-222222222222")
REVISION = datetime(2026, 7, 27, 12, tzinfo=UTC)


def transaction() -> TransactionDetail:
    return TransactionDetail(
        id=TRANSACTION_ID,
        transaction_type=TransactionType.EXPENSE,
        source_type=SourceType.MANUAL,
        status=TransactionStatus.DRAFT,
        transaction_date=date(2026, 7, 27),
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
        reconciliation_delta_amount=None,
        confirmed_at=None,
        created_at=REVISION,
        updated_at=REVISION,
    )


def request(**overrides: Any) -> ExpenseDraftSaveRequest:
    values: dict[str, Any] = {
        "client_request_id": "widget:request-123",
        "draft": ExpenseDraftInput(
            source_type="manual",
            transaction_date="2026-07-27",
            currency="CAD",
            subtotal_amount="10.00",
            tax_amount="1.30",
            total_amount="11.30",
        ),
    }
    values.update(overrides)
    return ExpenseDraftSaveRequest.model_validate(values)


class NoReceiptRepository:
    def get_receipt_for_transaction(self, transaction_id: UUID) -> None:
        assert transaction_id == TRANSACTION_ID
        return None


class ReplayTransactionRepository:
    def __init__(self, request_hash: str) -> None:
        self.request_hash = request_hash
        self.locked = False

    def acquire_mutation_lock(self, client_request_id: str) -> None:
        assert client_request_id == "widget:request-123"
        self.locked = True

    def get_mutation_result(self, client_request_id: str) -> dict[str, Any]:
        assert self.locked
        return {"request_hash": self.request_hash, "transaction_id": TRANSACTION_ID}

    def get_transaction(self, transaction_id: UUID) -> TransactionDetail:
        assert transaction_id == TRANSACTION_ID
        return transaction()


class StaleTransactionRepository:
    replaced = False

    def acquire_mutation_lock(self, _client_request_id: str) -> None:
        return None

    def get_mutation_result(self, _client_request_id: str) -> None:
        return None

    def lock_draft(self, transaction_id: UUID) -> tuple[TransactionStatus, datetime]:
        assert transaction_id == TRANSACTION_ID
        return TransactionStatus.DRAFT, REVISION + timedelta(minutes=1)

    def replace_draft(self, _transaction_id: UUID, _payload: object) -> TransactionDetail:
        self.replaced = True
        return transaction()


def service() -> ExpenseApplicationService:
    return ExpenseApplicationService(
        conn=object(),
        user_id=USER_ID,
        settings=Settings.model_validate({"supported_currencies": ["CAD", "USD"]}),
    )


def test_idempotent_replay_returns_original_transaction_without_mutating() -> None:
    application = service()
    payload = request()
    replay = ReplayTransactionRepository(application._request_hash(payload))
    application.transactions = cast(Any, replay)
    application.receipts = cast(Any, NoReceiptRepository())

    result = application.save_draft(payload)

    assert result.idempotent_replay is True
    assert result.expense.transaction.id == TRANSACTION_ID


def test_reusing_idempotency_key_for_different_payload_is_rejected() -> None:
    application = service()
    payload = request()
    application.transactions = cast(Any, ReplayTransactionRepository("0" * 64))

    with pytest.raises(ConflictError, match="different draft payload"):
        application.save_draft(payload)


def test_stale_revision_never_replaces_newer_draft() -> None:
    application = service()
    repository = StaleTransactionRepository()
    application.transactions = cast(Any, repository)

    with pytest.raises(ConflictError, match="refresh"):
        application.save_draft(
            request(transaction_id=TRANSACTION_ID, expected_revision=REVISION)
        )

    assert repository.replaced is False


def test_confirmation_requires_explicit_approval_before_database_work() -> None:
    application = service()

    with pytest.raises(ConflictError, match="Explicit user approval"):
        application.confirm(TRANSACTION_ID, explicit_approval=False)
