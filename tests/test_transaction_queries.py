from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.models import TransactionListFilters
from app.repositories import TransactionRepository

USER_ID = UUID("33333333-3333-3333-3333-333333333333")
TRANSACTION_ID = UUID("55555555-5555-5555-5555-555555555555")


class FakeResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def fetchone(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None

    def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


class FakeTransactionListConn:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def execute(self, sql: str, params: dict[str, Any]) -> FakeResult:
        self.calls.append((sql, params))
        if "select count(*) as total" in sql:
            return FakeResult([{"total": 1}])
        return FakeResult(
            [
                {
                    "id": TRANSACTION_ID,
                    "transaction_type": "expense",
                    "source_type": "receipt",
                    "status": "confirmed",
                    "transaction_date": date(2026, 7, 1),
                    "merchant_name_raw": "Example Market",
                    "merchant_name_normalized": "example market",
                    "currency": "CAD",
                    "total_amount": Decimal("12.34"),
                    "confirmed_at": None,
                }
            ]
        )


def test_transaction_listing_is_user_scoped_and_paginated() -> None:
    conn = FakeTransactionListConn()
    response = TransactionRepository(conn, USER_ID).list_transactions(
        TransactionListFilters(limit=20, offset=40)
    )

    assert response.total == 1
    assert response.limit == 20
    assert response.offset == 40
    assert response.transactions[0].id == TRANSACTION_ID
    for sql, params in conn.calls:
        assert "t.user_id = %(user_id)s" in sql
        assert params["user_id"] == USER_ID
        assert params["limit"] == 20
        assert params["offset"] == 40


def test_transaction_listing_compiles_safe_filters() -> None:
    conn = FakeTransactionListConn()
    filters = TransactionListFilters(
        status="confirmed",
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 31),
        merchant="Example Market",
        taxonomy_node_key="food_dining.groceries",
        include_descendants=True,
        source_type="receipt",
        transaction_type="expense",
    )

    TransactionRepository(conn, USER_ID).list_transactions(filters)
    sql, params = conn.calls[1]

    assert "t.status = %(status)s" in sql
    assert "t.transaction_date >= %(start_date)s" in sql
    assert "t.transaction_date <= %(end_date)s" in sql
    assert "lower(coalesce(t.merchant_name_normalized" in sql
    assert "exists (" in sql
    assert "join taxonomy_node_closure selected_branch" in sql
    assert "selected_branch.descendant_id = item_node.id" in sql
    assert params["taxonomy_node_key"] == "food_dining.groceries"
    assert params["status"] == "confirmed"
    assert params["source_type"] == "receipt"
    assert params["transaction_type"] == "expense"
