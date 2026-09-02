from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.models import AliasResolveItem, TransactionDetail, TransactionItem
from app.repositories import TransactionRepository

USER_ID = UUID("33333333-3333-3333-3333-333333333333")
TRANSACTION_ID = UUID("55555555-5555-5555-5555-555555555555")
CATEGORY_ID = UUID("66666666-6666-6666-6666-666666666666")
CONCEPT_ID = UUID("77777777-7777-7777-7777-777777777777")
VARIANT_ID = UUID("88888888-8888-8888-8888-888888888888")


class FakeResult:
    def __init__(self, row: dict[str, Any] | None = None, rowcount: int = 1) -> None:
        self.row = row
        self.rowcount = rowcount

    def fetchone(self) -> dict[str, Any] | None:
        return self.row


class AliasLookupConn:
    def __init__(
        self,
        merchant_row: dict[str, Any] | None,
        global_row: dict[str, Any] | None,
    ) -> None:
        self.merchant_row = merchant_row
        self.global_row = global_row
        self.calls: list[str] = []

    def execute(self, sql: str, _params: dict[str, Any]) -> FakeResult:
        self.calls.append(sql)
        if "a.source = 'user_merchant'" in sql:
            return FakeResult(self.merchant_row)
        return FakeResult(self.global_row)


class RecordingConn:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def execute(self, sql: str, params: dict[str, Any]) -> FakeResult:
        self.calls.append((sql, params))
        return FakeResult()


def alias_row(source: str, category_slug: str) -> dict[str, Any]:
    return {
        "source": source,
        "category_id": CATEGORY_ID,
        "category_slug": category_slug,
        "concept_id": CONCEPT_ID,
        "variant_id": VARIANT_ID,
    }


def transaction(status: str = "confirmed") -> TransactionDetail:
    return TransactionDetail(
        id=TRANSACTION_ID,
        transaction_type="expense",
        source_type="receipt",
        status=status,
        transaction_date=date(2026, 7, 1),
        merchant_name_raw="Example Market",
        merchant_name_normalized="example market",
        currency="CAD",
        subtotal_amount=Decimal("10.00"),
        tax_amount=Decimal("1.30"),
        fee_amount=None,
        discount_amount=None,
        tip_amount=None,
        deposit_amount=None,
        rounding_amount=None,
        total_amount=Decimal("11.30"),
        reconciliation_delta_amount=Decimal("0.00"),
        confirmed_at=None,
    )


def item() -> TransactionItem:
    return TransactionItem(
        id=UUID("99999999-9999-9999-9999-999999999999"),
        raw_name="  MILK 2%  ",
        interpreted_name="2% milk",
        normalized_name="milk 2 percent",
        concept_id=CONCEPT_ID,
        variant_id=VARIANT_ID,
        category_id=CATEGORY_ID,
        category_slug="grocery.food.dairy",
        quantity=Decimal("1"),
        unit="2 L",
        unit_price_amount=Decimal("5.99"),
        line_subtotal_amount=Decimal("5.99"),
        line_discount_amount=None,
        line_tax_amount=None,
        line_fee_amount=None,
        line_total_amount=Decimal("5.99"),
        confidence=Decimal("0.99"),
    )


def test_merchant_alias_has_precedence() -> None:
    conn = AliasLookupConn(
        merchant_row=alias_row("user_merchant", "grocery.food.dairy"),
        global_row=alias_row("user_global", "grocery"),
    )
    result = TransactionRepository(conn, USER_ID).resolve_aliases(
        "example market", [AliasResolveItem(raw_name="Milk 2%")]
    )

    assert result[0].source == "user_merchant"
    assert result[0].category_slug == "grocery.food.dairy"
    assert len(conn.calls) == 1


def test_alias_falls_back_to_user_global_then_unresolved() -> None:
    global_conn = AliasLookupConn(None, alias_row("user_global", "grocery"))
    global_result = TransactionRepository(global_conn, USER_ID).resolve_aliases(
        "other store", [AliasResolveItem(raw_name="Milk 2%")]
    )
    unresolved_conn = AliasLookupConn(None, None)
    unresolved_result = TransactionRepository(unresolved_conn, USER_ID).resolve_aliases(
        "other store", [AliasResolveItem(raw_name="Unknown item")]
    )

    assert global_result[0].source == "user_global"
    assert len(global_conn.calls) == 2
    assert unresolved_result[0].unresolved is True
    assert unresolved_result[0].source is None


def test_confirmed_item_learning_writes_merchant_and_user_global_aliases() -> None:
    conn = RecordingConn()
    TransactionRepository(conn, USER_ID).write_alias_for_confirmed_item(transaction(), item())

    assert len(conn.calls) == 2
    merchant_sql, merchant_params = conn.calls[0]
    global_sql, global_params = conn.calls[1]
    assert "'user_merchant'" in merchant_sql
    assert "'user_global'" in global_sql
    assert merchant_params["raw_name"] == "milk 2"
    assert global_params["concept_id"] == CONCEPT_ID
    assert global_params["variant_id"] == VARIANT_ID


class ConfirmationTrackingRepository(TransactionRepository):
    def __init__(self, status: str) -> None:
        super().__init__(RecordingConn(), USER_ID)
        self.current = transaction(status)
        self.alias_writes = 0

    def get_transaction(self, _transaction_id: UUID) -> TransactionDetail:
        return self.current

    def write_aliases_from_confirmed_items(self, _transaction_id: UUID) -> None:
        self.alias_writes += 1
        self.current = self.current.model_copy(update={"status": "confirmed"})

    def add_audit_event(
        self,
        _entity_type: str,
        _entity_id: UUID,
        _action: str,
        _metadata: dict[str, Any],
    ) -> None:
        return None


def test_alias_learning_occurs_on_first_confirmation_only() -> None:
    draft_repo = ConfirmationTrackingRepository("draft")
    confirmed_repo = ConfirmationTrackingRepository("confirmed")

    draft_repo.confirm_transaction(TRANSACTION_ID)
    confirmed_repo.confirm_transaction(TRANSACTION_ID)

    assert draft_repo.alias_writes == 1
    assert confirmed_repo.alias_writes == 0
