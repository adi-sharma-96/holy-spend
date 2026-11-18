from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from app.dashboard import dashboard_window
from app.plugin_models import CoverageDeclaration, DashboardPeriod
from app.spending import compare_spending


def coverage(kind: str, start: date, end: date | None = None) -> CoverageDeclaration:
    return CoverageDeclaration.model_validate({
        "id": uuid4(), "currency": "CAD", "kind": kind, "start_date": start, "end_date": end,
        "recorded_at": datetime.now(UTC), "reason": "Synthetic declaration",
    })


def test_sparse_comparison_is_suppressed_until_both_elapsed_windows_are_covered() -> None:
    window = dashboard_window(DashboardPeriod.MONTH, date(2026, 7, 12))
    current = coverage("tracking", window.current_start)
    previous = coverage("complete_import", window.previous_start, window.previous_end)
    result = compare_spending(window, "CAD", Decimal(1000), Decimal(10), 15, 1, [current])
    assert result.delta_percent is None
    assert result.previous_unknown_days == 12
    assert result.reasons == ["coverage_unknown"]
    assert result.label == "Tracking coverage is incomplete or undeclared."
    assert result.previous_amount == Decimal(10)
    assert result.window.previous_end == date(2026, 6, 12)

    result = compare_spending(window, "CAD", Decimal(1000), Decimal(10), 15, 1, [current, previous])
    assert result.delta_percent == Decimal("9900.0")
    assert result.current_basis == ["tracking"]
    assert result.previous_basis == ["complete_import"]

    hole = coverage("gap", date(2026, 6, 8), date(2026, 6, 8))
    result = compare_spending(window, "CAD", Decimal(1000), Decimal(10), 15, 1, [current, previous, hole])
    assert result.previous_unknown_days == 1
    assert result.delta_percent is None


@pytest.mark.parametrize(("previous", "count", "reason"), [
    (0, 0, "missing_baseline"), (0, 2, "zero_baseline"), (-10, 1, "negative_baseline"),
])
def test_unusable_baselines(previous: int, count: int, reason: str) -> None:
    window = dashboard_window(DashboardPeriod.MONTH, date(2026, 7, 12))
    declared = coverage("tracking", window.previous_start)
    result = compare_spending(window, "CAD", Decimal(100), Decimal(previous), 5, count, [declared])
    assert result.delta_percent is None
    assert result.reasons == [reason]


def test_ordinary_requires_review_and_coverage_is_currency_specific() -> None:
    window = dashboard_window(DashboardPeriod.MONTH, date(2026, 7, 12))
    declared = coverage("tracking", window.previous_start)
    result = compare_spending(window, "USD", Decimal(100), Decimal(50), 5, 1, [declared], unreviewed=3)
    assert result.delta_percent is None
    assert result.reasons == ["coverage_unknown", "unreviewed_spend"]
