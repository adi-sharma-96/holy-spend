import hashlib
import json
from typing import Any
from uuid import UUID

from app.config import Settings
from app.errors import ConflictError, ValidationReferenceError
from app.models import (
    ReceiptFileRecord,
    TransactionAdjustmentCreate,
    TransactionDetail,
    ValidationResponse,
)
from app.plugin_models import (
    ExpenseCorrectionRequest,
    ExpenseDraftSaveRequest,
    ExpenseSnapshot,
    MutationResult,
    ReceiptSnapshot,
)
from app.receipt_files import ReceiptRepository
from app.reconciliation import ReconciliationService, has_blocking_issues
from app.repositories import TransactionRepository


class ExpenseApplicationService:
    """Shared transaction orchestration used by REST and MCP transports."""

    def __init__(self, conn: Any, user_id: UUID, settings: Settings) -> None:
        self.conn = conn
        self.user_id = user_id
        self.settings = settings
        self.transactions = TransactionRepository(conn, user_id)
        self.receipts = ReceiptRepository(conn, user_id)

    def get_expense(self, transaction_id: UUID) -> ExpenseSnapshot:
        transaction = self.transactions.get_transaction(transaction_id)
        receipt = self.receipts.get_receipt_for_transaction(transaction_id)
        receipt_snapshot = None
        if receipt is not None:
            files: list[ReceiptFileRecord] = [
                owned.public_record() for owned in self.receipts.list_files(receipt.id)
            ]
            receipt_snapshot = ReceiptSnapshot(receipt=receipt, files=files)
        return ExpenseSnapshot(transaction=transaction, receipt=receipt_snapshot)

    def save_draft(self, request: ExpenseDraftSaveRequest) -> MutationResult:
        if request.draft.currency not in self.settings.supported_currencies:
            raise ValidationReferenceError(f"Unsupported currency: {request.draft.currency}")

        request_hash = self._request_hash(request)
        self.transactions.acquire_mutation_lock(request.client_request_id)
        previous = self.transactions.get_mutation_result(request.client_request_id)
        if previous is not None:
            if previous["request_hash"] != request_hash:
                raise ConflictError("client_request_id was already used for a different draft payload")
            return MutationResult(
                expense=self.get_expense(previous["transaction_id"]),
                idempotent_replay=True,
            )

        payload = request.draft.transaction_payload()
        if request.transaction_id is None:
            transaction = self.transactions.create_draft(payload)
        else:
            _status, actual_revision = self.transactions.lock_draft(request.transaction_id)
            if request.expected_revision is None:
                raise ConflictError("expected_revision is required when replacing an existing draft")
            if request.expected_revision != actual_revision:
                raise ConflictError(
                    "Draft changed since it was loaded; refresh it before applying further edits"
                )
            transaction = self.transactions.replace_draft(request.transaction_id, payload)

        transaction = self._add_indexed_adjustments(transaction, request)
        self.transactions.record_mutation_result(
            request.client_request_id,
            request_hash,
            transaction.id,
        )
        return MutationResult(expense=self.get_expense(transaction.id))

    def validate(self, transaction_id: UUID) -> ValidationResponse:
        transaction = self.transactions.get_transaction(transaction_id)
        delta, issues = ReconciliationService(self.settings).validate(transaction)
        persisted = self.transactions.set_validation_result(transaction_id, delta, issues)
        return ValidationResponse(
            transaction_id=transaction_id,
            reconciliation_delta_amount=delta,
            issues=persisted,
        )

    def correct_confirmed(self, request: ExpenseCorrectionRequest) -> MutationResult:
        """Replace a confirmed record atomically, preserving an audit snapshot."""
        if not request.explicit_approval:
            raise ConflictError("Explicit user approval is required before correcting a confirmed expense")
        if request.draft.currency not in self.settings.supported_currencies:
            raise ValidationReferenceError(f"Unsupported currency: {request.draft.currency}")

        request_hash = self._request_hash(request)
        self.transactions.acquire_mutation_lock(request.client_request_id)
        previous = self.transactions.get_mutation_result(request.client_request_id)
        if previous is not None:
            if previous["request_hash"] != request_hash:
                raise ConflictError("client_request_id was already used for a different correction")
            return MutationResult(
                expense=self.get_expense(previous["transaction_id"]),
                idempotent_replay=True,
            )

        status, actual_revision = self.transactions.lock_draft(request.transaction_id)
        if status.value != "confirmed":
            raise ConflictError("Only confirmed expenses can use the correction workflow")
        if request.expected_revision != actual_revision:
            raise ConflictError(
                "Expense changed since it was loaded; refresh it before applying the correction"
            )

        transaction = self.transactions.replace_confirmed(
            request.transaction_id,
            request.draft.transaction_payload(),
            request.correction_reason,
        )
        transaction = self._add_indexed_adjustments(
            transaction,
            request,
            correction_reason=request.correction_reason,
        )
        validation = self.validate(transaction.id)
        if has_blocking_issues(validation.issues):
            raise ConflictError("The correction has blocking validation issues and was not applied")
        self.transactions.record_mutation_result(
            request.client_request_id,
            request_hash,
            transaction.id,
        )
        return MutationResult(expense=self.get_expense(transaction.id))

    def confirm(self, transaction_id: UUID, explicit_approval: bool) -> TransactionDetail:
        if not explicit_approval:
            raise ConflictError("Explicit user approval is required before confirmation")
        validation = self.validate(transaction_id)
        if has_blocking_issues(validation.issues):
            raise ConflictError("Blocking validation issues must be resolved before confirmation")
        return self.transactions.confirm_transaction(transaction_id)

    def _add_indexed_adjustments(
        self,
        transaction: TransactionDetail,
        request: ExpenseDraftSaveRequest | ExpenseCorrectionRequest,
        *,
        correction_reason: str | None = None,
    ) -> TransactionDetail:
        for adjustment in request.draft.adjustments:
            item_id = None
            if adjustment.item_index is not None:
                try:
                    item_id = transaction.items[adjustment.item_index].id
                except IndexError as error:
                    raise ValidationReferenceError(
                        f"Adjustment item_index {adjustment.item_index} is outside the items list"
                    ) from error
            self.transactions.add_adjustment(
                transaction.id,
                TransactionAdjustmentCreate(
                    item_id=item_id,
                    type=adjustment.type,
                    subtype=adjustment.subtype,
                    amount=adjustment.amount,
                    description=adjustment.description,
                    raw_label=adjustment.raw_label,
                    affects_total=adjustment.affects_total,
                    metadata=adjustment.metadata,
                    correction_reason=correction_reason,
                ),
            )
        return self.transactions.get_transaction(transaction.id)

    @staticmethod
    def _request_hash(request: ExpenseDraftSaveRequest | ExpenseCorrectionRequest) -> str:
        canonical = request.model_dump(
            mode="json",
            exclude={"client_request_id"},
        )
        encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()
