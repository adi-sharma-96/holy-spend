from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.analytics import AnalyticsQueryCompiler, AnalyticsRepository
from app.models import AnalyticsFilters, AnalyticsQueryRequest

USER_ID = UUID("33333333-3333-3333-3333-333333333333")


class FakeResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


class FakeAnalyticsConn:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.sql = ""
        self.params: dict[str, Any] = {}

    def execute(self, sql: str, params: dict[str, Any]) -> FakeResult:
        self.sql = sql
        self.params = params
        return FakeResult(self.rows)


def request(**values: Any) -> AnalyticsQueryRequest:
    return AnalyticsQueryRequest.model_validate(values)


def test_analytics_is_always_confirmed_only_and_user_scoped() -> None:
    statement = AnalyticsQueryCompiler().compile(USER_ID, request(metrics=["total_spend"]))

    assert "t.status = 'confirmed'" in statement.sql
    assert "t.user_id = %(user_id)s" in statement.sql
    assert "draft" not in statement.sql
    assert statement.params["user_id"] == USER_ID


def test_category_descendant_filter_uses_taxonomy_closure() -> None:
    statement = AnalyticsQueryCompiler().compile(
        USER_ID,
        request(
            metrics=["total_spend"],
            filters={"taxonomy_node_key": "food_dining.groceries", "include_descendants": True},
        ),
    )

    assert "join taxonomy_node_closure selected_branch" in statement.sql
    assert "selected_branch.descendant_id = item_node.id" in statement.sql
    assert statement.params["taxonomy_node_key"] == "food_dining.groceries"


def test_category_exact_filter_can_exclude_descendants() -> None:
    statement = AnalyticsQueryCompiler().compile(
        USER_ID,
        request(
            metrics=["total_spend"],
            filters={"taxonomy_node_key": "food_dining.groceries", "include_descendants": False},
        ),
    )

    assert "item_node.stable_key = %(taxonomy_node_key)s" in statement.sql
    assert "selected_branch" not in statement.sql


def test_explicit_date_boundaries_are_inclusive() -> None:
    statement = AnalyticsQueryCompiler().compile(
        USER_ID,
        request(
            metrics=["purchase_count"],
            filters={"start_date": "2026-01-01", "end_date": "2026-01-31"},
        ),
    )

    assert "t.transaction_date >= %(start_date)s" in statement.sql
    assert "t.transaction_date <= %(end_date)s" in statement.sql
    assert statement.params["start_date"] == date(2026, 1, 1)
    assert statement.params["end_date"] == date(2026, 1, 31)


def test_relative_date_range_includes_today() -> None:
    compiler = AnalyticsQueryCompiler(today=lambda: date(2026, 7, 16))
    statement = compiler.compile(
        USER_ID,
        request(metrics=["total_spend"], filters={"relative_days": 30}),
    )

    assert statement.params["start_date"] == date(2026, 6, 17)
    assert statement.params["end_date"] == date(2026, 7, 16)


def test_refunds_reduce_spend_and_are_reported_as_positive_magnitude() -> None:
    statement = AnalyticsQueryCompiler().compile(
        USER_ID,
        request(metrics=["total_spend", "refund_total"]),
    )

    assert "when t.transaction_type = 'refund' then -abs(t.total_amount)" in statement.sql
    assert "then abs(t.total_amount) else 0" in statement.sql


def test_month_category_and_merchant_groupings_are_allowlisted() -> None:
    statement = AnalyticsQueryCompiler().compile(
        USER_ID,
        request(
            metrics=["total_spend"],
            group_by=["month", "category", "merchant"],
        ),
    )

    assert "date_trunc('month', t.transaction_date)::date" in statement.sql
    assert "from taxonomy_node_closure path" in statement.sql
    assert "ancestor.level <= %(taxonomy_rollup_level)s" in statement.sql
    assert statement.params["taxonomy_rollup_level"] == 3
    assert "t.merchant_name_normalized" in statement.sql
    assert "group by" in statement.sql


def test_category_grouping_can_use_a_deeper_rollup() -> None:
    statement = AnalyticsQueryCompiler().compile(
        USER_ID,
        request(
            metrics=["total_spend"],
            group_by=["category"],
            taxonomy_rollup_level=4,
        ),
    )

    assert statement.params["taxonomy_rollup_level"] == 4


def test_category_grouping_can_request_direct_categories() -> None:
    statement = AnalyticsQueryCompiler().compile(
        USER_ID,
        request(
            metrics=["total_spend"],
            group_by=["category"],
            taxonomy_rollup_level=6,
            category_rollup_depth=None,
        ),
    )

    assert "category_node.stable_key as dimension_0" in statement.sql
    assert statement.params["taxonomy_rollup_level"] == 6
    assert "string_to_array" not in statement.sql


def test_repository_preserves_decimal_accuracy() -> None:
    conn = FakeAnalyticsConn([{"dimension_0": "CAD", "metric_0": Decimal("0.30")}])
    response = AnalyticsRepository(conn, USER_ID).query(request(metrics=["total_spend"]))

    assert response.rows[0].metrics["total_spend"] == Decimal("0.30")
    assert response.rows[0].dimensions["currency"] == "CAD"
    assert response.confirmed_only is True


def test_monetary_results_are_implicitly_separated_by_currency() -> None:
    statement = AnalyticsQueryCompiler().compile(
        USER_ID,
        request(metrics=["total_spend"]),
    )

    assert "t.currency as dimension_0" in statement.sql
    assert "group by t.currency" in statement.sql


def test_grouped_query_can_return_empty_results() -> None:
    conn = FakeAnalyticsConn([])
    response = AnalyticsRepository(conn, USER_ID).query(
        request(metrics=["total_spend"], group_by=["merchant"])
    )

    assert response.rows == []


@pytest.mark.parametrize(
    "payload",
    [
        {"metrics": ["median_spend"]},
        {"metrics": ["total_spend"], "group_by": ["store_city"]},
        {"metrics": ["total_spend"], "taxonomy_rollup_level": 7},
    ],
)
def test_unsupported_metrics_and_groupings_are_rejected(payload: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        AnalyticsQueryRequest.model_validate(payload)


def test_relative_days_cannot_be_combined_with_explicit_dates() -> None:
    with pytest.raises(ValidationError):
        AnalyticsFilters(relative_days=7, start_date=date(2026, 1, 1))
