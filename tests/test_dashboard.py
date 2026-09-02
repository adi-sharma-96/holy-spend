from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.dashboard import DashboardRepository, dashboard_window
from app.plugin_models import (
    DashboardPeriod,
    ExpenseDashboardRequest,
    ItemPriceHistoryRequest,
    MerchantBreakdownRequest,
    PersonalBasketRequest,
    SearchKnownItemsRequest,
)

USER_ID = UUID("33333333-3333-3333-3333-333333333333")
TRANSACTION_ID = UUID("55555555-5555-5555-5555-555555555555")
ITEM_ID = UUID("66666666-6666-6666-6666-666666666666")


class FakeResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def fetchone(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None

    def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


class FakeDashboardConn:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def execute(self, sql: str, params: dict[str, Any]) -> FakeResult:
        self.calls.append((sql, params))
        if "dashboard:profile" in sql:
            return FakeResult([{"display_name": "Adi", "default_currency": "CAD"}])
        if "dashboard:totals" in sql:
            return FakeResult(
                [
                    {
                        "currency": "CAD",
                        "current_amount": Decimal("325.40"),
                        "previous_amount": Decimal("280.00"),
                    },
                    {
                        "currency": "USD",
                        "current_amount": Decimal("40.00"),
                        "previous_amount": Decimal("0"),
                    },
                ]
            )
        if "dashboard:categories" in sql:
            return FakeResult(
                [
                    {
                        "category_slug": "grocery",
                        "category_name": "Grocery & Everyday Retail",
                        "taxonomy_level": 2,
                        "taxonomy_level_name": "Group",
                        "has_children": True,
                        "currency": "CAD",
                        "current_amount": Decimal("200"),
                        "previous_amount": Decimal("150"),
                    },
                    {
                        "category_slug": "eating_out",
                        "category_name": "Eating Out",
                        "taxonomy_level": 2,
                        "taxonomy_level_name": "Group",
                        "has_children": True,
                        "currency": "CAD",
                        "current_amount": Decimal("50"),
                        "previous_amount": Decimal("70"),
                    },
                ]
            )
        if "dashboard:spend-trend" in sql:
            return FakeResult(
                [
                    {
                        "period_start": date(2026, 6, 1),
                        "label": "Jun",
                        "currency": "CAD",
                        "amount": Decimal("280.00"),
                    },
                    {
                        "period_start": date(2026, 7, 1),
                        "label": "Jul",
                        "currency": "CAD",
                        "amount": Decimal("325.40"),
                    },
                ]
            )
        if "dashboard:review" in sql:
            return FakeResult([{"needs_review_count": 2}])
        if "dashboard:recent" in sql:
            return FakeResult(
                [
                    {
                        "id": TRANSACTION_ID,
                        "transaction_type": "expense",
                        "source_type": "receipt",
                        "status": "confirmed",
                        "transaction_date": date(2026, 7, 25),
                        "merchant_name_raw": "Fresh Market",
                        "merchant_name_normalized": "Fresh Market",
                        "currency": "CAD",
                        "total_amount": Decimal("48.50"),
                        "confirmed_at": None,
                        "item_count": 5,
                    }
                ]
            )
        if "dashboard:daily-spend" in sql:
            return FakeResult(
                [
                    {
                        "spend_date": date(2026, 7, 10),
                        "currency": "CAD",
                        "amount": Decimal("10.98"),
                        "transaction_count": 1,
                    },
                    {
                        "spend_date": date(2026, 7, 25),
                        "currency": "CAD",
                        "amount": Decimal("48.50"),
                        "transaction_count": 2,
                    },
                ]
            )
        if "dashboard:price-changes" in sql:
            return FakeResult(
                [
                    {
                        "normalized_name": "honeycrisp apples",
                        "taxonomy_key": "food_dining.groceries.produce.fruit.apples_pears.apples",
                        "taxonomy_name": "Apples",
                        "currency": "CAD",
                        "normalized_unit": "kg",
                        "price": Decimal("6.59"),
                        "transaction_date": date(2026, 7, 25),
                        "merchant": "Fresh Market",
                        "quantity": None,
                        "unit": None,
                        "measured_value": Decimal("1.25"),
                        "measured_unit": "kg",
                        "package_value": None,
                        "package_unit": None,
                        "updated_at": None,
                        "id": ITEM_ID,
                    },
                    {
                        "normalized_name": "gala apples",
                        "taxonomy_key": "food_dining.groceries.produce.fruit.apples_pears.apples",
                        "taxonomy_name": "Apples",
                        "currency": "CAD",
                        "normalized_unit": "kg",
                        "price": Decimal("5.49"),
                        "transaction_date": date(2026, 7, 10),
                        "merchant": "Budget Foods",
                        "quantity": None,
                        "unit": None,
                        "measured_value": Decimal("2"),
                        "measured_unit": "kg",
                        "package_value": None,
                        "package_unit": None,
                        "updated_at": None,
                        "id": ITEM_ID,
                    },
                    {
                        "normalized_name": "nova red onions",
                        "taxonomy_key": "food_dining.groceries.produce.vegetables.alliums.onions",
                        "taxonomy_name": "Onions",
                        "currency": "CAD",
                        "normalized_unit": "kg",
                        "price": Decimal("3.67"),
                        "transaction_date": date(2026, 7, 22),
                        "merchant": "Fresh Market",
                        "quantity": None,
                        "unit": None,
                        "measured_value": Decimal("1"),
                        "measured_unit": "kg",
                        "package_value": None,
                        "package_unit": None,
                        "updated_at": None,
                        "id": ITEM_ID,
                    },
                ]
            )
        if "dashboard:item-price-history" in sql:
            return FakeResult(
                [
                    {
                        "transaction_id": TRANSACTION_ID,
                        "transaction_item_id": ITEM_ID,
                        "transaction_date": date(2026, 7, 25),
                        "merchant_name": "Fresh Market",
                        "display_name": "Apples",
                        "normalized_name": "honeycrisp apples",
                        "brand": None,
                        "concept_id": None,
                        "variant_id": None,
                        "taxonomy_key": "food_dining.groceries.produce.fruit.apples_pears.apples",
                        "taxonomy_name": "Apples",
                        "currency": "CAD",
                        "normalized_unit": "kg",
                        "normalized_unit_price_amount": Decimal("6.59"),
                        "is_estimated": True,
                        "quantity": None,
                        "unit": None,
                        "measured_value": Decimal("2"),
                        "measured_unit": "lb",
                        "package_value": None,
                        "package_unit": None,
                        "line_total_amount": Decimal("5.98"),
                    }
                ]
            )
        raise AssertionError(f"Unexpected SQL: {sql}")


class FakeDashboardConnWithZeroCategory(FakeDashboardConn):
    def execute(self, sql: str, params: dict[str, Any]) -> FakeResult:
        if "dashboard:categories" in sql:
            self.calls.append((sql, params))
            return FakeResult(
                [
                    {
                        "category_slug": "grocery",
                        "category_name": "Grocery & Everyday Retail",
                        "taxonomy_level": 2,
                        "taxonomy_level_name": "Group",
                        "has_children": True,
                        "currency": "CAD",
                        "current_amount": Decimal("200"),
                        "previous_amount": Decimal("150"),
                    },
                    {
                        "category_slug": "subscriptions",
                        "category_name": "Subscriptions",
                        "taxonomy_level": 2,
                        "taxonomy_level_name": "Group",
                        "has_children": False,
                        "currency": "CAD",
                        "current_amount": Decimal("0"),
                        "previous_amount": Decimal("40"),
                    },
                ]
            )
        return super().execute(sql, params)


class FakeMerchantConn:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def execute(self, sql: str, params: dict[str, Any]) -> FakeResult:
        self.calls.append((sql, params))
        if "dashboard:merchants" in sql:
            return FakeResult(self.rows)
        raise AssertionError(f"Unexpected SQL: {sql}")


class FakeBasketConn:
    def __init__(self, rows: list[dict[str, Any]], total_tracked_spend: str = "0") -> None:
        self.rows = rows
        self.total_tracked_spend = total_tracked_spend
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def execute(self, sql: str, params: dict[str, Any]) -> FakeResult:
        self.calls.append((sql, params))
        if "dashboard:tracked-total" in sql:
            return FakeResult([{"total": Decimal(self.total_tracked_spend)}])
        if "dashboard:personal-basket" in sql:
            return FakeResult(self.rows)
        raise AssertionError(f"Unexpected SQL: {sql}")


def _basket_row(
    name: str,
    taxonomy_key: str,
    unit: str,
    price: str,
    line_total: str,
    when: date,
    merchant: str = "Test Market",
    brand: str | None = None,
) -> dict[str, Any]:
    return {
        "normalized_name": name,
        "brand": brand,
        "taxonomy_key": taxonomy_key,
        "normalized_unit": unit,
        "price": Decimal(price),
        "line_total_amount": Decimal(line_total),
        "transaction_date": when,
        "merchant": merchant,
    }


def test_calendar_month_window_compares_equal_month_to_date_progress() -> None:
    window = dashboard_window(DashboardPeriod.MONTH, date(2026, 7, 27))

    assert window.current_start == date(2026, 7, 1)
    assert window.current_end == date(2026, 7, 27)
    assert window.previous_start == date(2026, 6, 1)
    assert window.previous_end == date(2026, 6, 27)


def test_month_window_caps_comparison_at_shorter_previous_month() -> None:
    window = dashboard_window(DashboardPeriod.MONTH, date(2026, 3, 31))

    assert window.previous_start == date(2026, 2, 1)
    assert window.previous_end == date(2026, 2, 28)


def test_year_window_compares_equal_year_to_date_progress() -> None:
    window = dashboard_window(DashboardPeriod.YEAR, date(2026, 7, 27))

    assert window.previous_start == date(2025, 1, 1)
    assert window.previous_end == date(2025, 7, 27)


def test_dashboard_keeps_currencies_separate_and_builds_focused_insights() -> None:
    conn = FakeDashboardConn()
    response = DashboardRepository(
        conn,
        USER_ID,
        today=lambda: date(2026, 7, 27),
    ).get_dashboard(ExpenseDashboardRequest())

    assert response.display_name == "Adi"
    assert [total.currency for total in response.totals] == ["CAD", "USD"]
    assert response.totals[0].delta_percent == Decimal("16.2")
    assert response.totals[1].delta_percent is None
    # Grocery(200) + Eating Out(50) = 250, but the real CAD total is 325.40 -
    # the gap (75.40 of tax/fees/tips never attached to an item) now shows as
    # its own row and is folded into the share denominator, so grocery's true
    # share of total spend is 61.5%, not 80% of just the classified portion.
    assert response.categories[0].share_percent == Decimal("61.5")
    assert response.categories[0].taxonomy_level_name == "Group"
    cad_adjustments = next(
        c
        for c in response.categories
        if c.category_slug == "adjustments.taxes_fees" and c.currency == "CAD"
    )
    assert cad_adjustments.current_amount == Decimal("75.40")
    assert cad_adjustments.previous_amount == Decimal("60")
    assert cad_adjustments.share_percent == Decimal("23.2")
    assert response.spend_trend[-1].amount == Decimal("325.40")
    assert [daily.spend_date for daily in response.daily_spend] == [
        date(2026, 7, 10),
        date(2026, 7, 25),
    ]
    assert response.daily_spend[1].amount == Decimal("48.50")
    assert response.daily_spend[1].transaction_count == 2
    assert response.recent_transactions[0].item_count == 5
    assert response.needs_review_count == 2
    assert response.price_changes[0].normalized_unit == "kg"
    assert response.price_changes[0].identity_key == "product:apples"
    assert response.price_changes[0].sample_size == 2
    assert response.price_changes[0].best_merchant == "Budget Foods"
    assert response.price_changes[0].best_price == Decimal("5.49")
    assert response.price_changes[0].best_quantity_label == "2 kg"
    assert response.price_changes[0].comparison_merchant == "Fresh Market"
    assert response.price_changes[0].comparison_price == Decimal("6.59")
    assert response.price_changes[0].savings_amount == Decimal("1.10")
    assert response.price_changes[0].savings_percent == Decimal("16.7")
    assert response.price_changes[0].recent_prices == [Decimal("5.49"), Decimal("6.59")]
    assert response.price_changes[1].label == "Onions"
    assert response.price_changes[1].delta_amount is None
    assert response.price_changes[1].recent_prices == [Decimal("3.67")]
    assert len(response.insights) == 3
    for sql, params in conn.calls:
        assert params["user_id"] == USER_ID
        if "dashboard:totals" in sql or "dashboard:categories" in sql:
            assert "t.status = 'confirmed'" in sql
        if "dashboard:categories" in sql:
            assert "category.stable_key not like 'unclassified.%%'" in sql
        if "dashboard:review" in sql:
            assert "node.stable_key = 'unclassified.needs_review'" in sql
        if "dashboard:price-changes" in sql:
            assert "t.transaction_date <= %(current_end)s" in sql
            assert "not i.normalized_price_is_estimated" in sql


def test_dashboard_drops_categories_with_no_current_period_spend() -> None:
    conn = FakeDashboardConnWithZeroCategory()
    response = DashboardRepository(
        conn,
        USER_ID,
        today=lambda: date(2026, 7, 27),
    ).get_dashboard(ExpenseDashboardRequest())

    slugs = [category.category_slug for category in response.categories]
    # The zero-current "subscriptions" row is still dropped - it's empty and
    # doesn't count toward the share denominator either way. The two
    # "adjustments.taxes_fees" rows are the CAD and USD reconciliation gaps
    # (real total minus what actually got attached to a category).
    assert slugs == ["grocery", "adjustments.taxes_fees", "adjustments.taxes_fees"]
    assert response.categories[0].share_percent == Decimal("61.5")
    cad_adjustments = response.categories[1]
    assert cad_adjustments.currency == "CAD"
    assert cad_adjustments.current_amount == Decimal("125.40")
    assert cad_adjustments.share_percent == Decimal("38.5")
    usd_adjustments = response.categories[2]
    assert usd_adjustments.currency == "USD"
    assert usd_adjustments.current_amount == Decimal("40")
    assert usd_adjustments.share_percent == Decimal("100.0")


def test_merchant_breakdown_computes_deltas_and_drops_zero_current_rows() -> None:
    rows = [
        {
            "merchant_name": "Farm Boy",
            "current_amount": Decimal("120"),
            "previous_amount": Decimal("100"),
            "visit_count": 4,
        },
        {
            "merchant_name": "No Frills",
            "current_amount": Decimal("80"),
            "previous_amount": Decimal("100"),
            "visit_count": 2,
        },
        {
            "merchant_name": "Pizzeria Libretto",
            "current_amount": Decimal("40"),
            "previous_amount": Decimal("0"),
            "visit_count": 1,
        },
        {
            "merchant_name": "TTC",
            "current_amount": Decimal("20"),
            "previous_amount": Decimal("20"),
            "visit_count": 1,
        },
        {
            "merchant_name": "Old Gym",
            "current_amount": Decimal("0"),
            "previous_amount": Decimal("60"),
            "visit_count": 0,
        },
    ]
    conn = FakeMerchantConn(rows)
    response = DashboardRepository(
        conn,
        USER_ID,
        today=lambda: date(2026, 7, 27),
    ).get_merchant_breakdown(
        MerchantBreakdownRequest(currency="cad", period=DashboardPeriod.MONTH)
    )

    names = [merchant.merchant_name for merchant in response.merchants]
    assert names == ["Farm Boy", "No Frills", "Pizzeria Libretto", "TTC"]
    assert "Old Gym" not in names

    farm_boy, no_frills, pizzeria, ttc = response.merchants
    assert farm_boy.delta_percent == Decimal("20.0")
    assert farm_boy.average_amount == Decimal("30.00")
    assert farm_boy.share_percent == Decimal("46.2")

    assert no_frills.delta_percent == Decimal("-20.0")
    assert no_frills.share_percent == Decimal("30.8")

    # No prior-period spend at all - genuinely "New," not a computed 0%.
    assert pizzeria.delta_percent is None
    assert pizzeria.share_percent == Decimal("15.4")

    # Spent the same both periods - a real computed tie, distinct from "New."
    assert ttc.delta_percent == Decimal("0.0")
    assert ttc.share_percent == Decimal("7.7")

    assert response.currency == "CAD"
    for sql, params in conn.calls:
        assert params["currency"] == "CAD"
        assert "t.status = 'confirmed'" in sql


def test_merchant_breakdown_respects_the_requested_limit() -> None:
    rows = [
        {
            "merchant_name": f"Merchant {index}",
            "current_amount": Decimal(str(100 - index)),
            "previous_amount": Decimal("0"),
            "visit_count": 1,
        }
        for index in range(5)
    ]
    conn = FakeMerchantConn(rows)
    response = DashboardRepository(conn, USER_ID, today=lambda: date(2026, 7, 27)).get_merchant_breakdown(
        MerchantBreakdownRequest(currency="CAD", period=DashboardPeriod.MONTH, limit=2)
    )

    assert [merchant.merchant_name for merchant in response.merchants] == [
        "Merchant 0",
        "Merchant 1",
    ]


def test_price_history_uses_one_identity_and_groups_by_currency_and_unit() -> None:
    conn = FakeDashboardConn()
    response = DashboardRepository(conn, USER_ID).get_item_price_history(
        ItemPriceHistoryRequest(identity_key="product:apples", currency="cad")
    )

    assert response.label == "Apples"
    assert response.series[0].currency == "CAD"
    assert response.series[0].normalized_unit == "kg"
    assert response.series[0].points[0].measured_unit == "lb"
    assert response.series[0].points[0].is_estimated is True
    sql, params = conn.calls[-1]
    assert params["currency"] == "CAD"


def test_item_price_history_basket_identity_never_falls_back_to_family() -> None:
    conn = FakeDashboardConn()
    response = DashboardRepository(conn, USER_ID).get_item_price_history(
        ItemPriceHistoryRequest(
            identity_key="basket:honeycrisp-apples@kg@store:fresh-market", currency="cad"
        )
    )

    assert response.label == "Fresh Market Honeycrisp Apples"
    assert response.series[0].points[0].measured_unit == "lb"


class FakeDashboardConnTwoUnits(FakeDashboardConn):
    """A 'product' identity that spans two units (e.g. croissants sold both by
    weight and by count) - Deals' taxonomy-leaf identity doesn't fold unit
    into the key, so both rows share identity_key "product:croissants"."""

    def execute(self, sql: str, params: dict[str, Any]) -> FakeResult:
        if "dashboard:item-price-history" in sql:
            self.calls.append((sql, params))
            return FakeResult(
                [
                    {
                        "transaction_id": TRANSACTION_ID,
                        "transaction_item_id": ITEM_ID,
                        "transaction_date": date(2026, 7, 20),
                        "merchant_name": "TD Office",
                        "display_name": "Croissants",
                        "normalized_name": "croissants",
                        "brand": None,
                        "concept_id": None,
                        "variant_id": None,
                        "taxonomy_key": "food_dining.groceries.bread_bakery.pastries.croissants",
                        "taxonomy_name": "Croissants",
                        "currency": "CAD",
                        "normalized_unit": "each",
                        "normalized_unit_price_amount": Decimal("2.48"),
                        "quantity": None,
                        "unit": None,
                        "measured_value": None,
                        "measured_unit": None,
                        "package_value": None,
                        "package_unit": None,
                        "line_total_amount": Decimal("2.48"),
                    },
                    {
                        "transaction_id": TRANSACTION_ID,
                        "transaction_item_id": ITEM_ID,
                        "transaction_date": date(2026, 7, 18),
                        "merchant_name": "FreshCo",
                        "display_name": "Croissants",
                        "normalized_name": "croissants",
                        "brand": None,
                        "concept_id": None,
                        "variant_id": None,
                        "taxonomy_key": "food_dining.groceries.bread_bakery.pastries.croissants",
                        "taxonomy_name": "Croissants",
                        "currency": "CAD",
                        "normalized_unit": "kg",
                        "normalized_unit_price_amount": Decimal("20.37"),
                        "quantity": None,
                        "unit": None,
                        "measured_value": Decimal("0.3"),
                        "measured_unit": "kg",
                        "package_value": None,
                        "package_unit": None,
                        "line_total_amount": Decimal("6.11"),
                    },
                ]
            )
        return super().execute(sql, params)


def test_item_price_history_disambiguates_a_product_that_spans_two_units() -> None:
    conn = FakeDashboardConnTwoUnits()

    both = DashboardRepository(conn, USER_ID).get_item_price_history(
        ItemPriceHistoryRequest(identity_key="product:croissants", currency="cad")
    )
    assert {series.normalized_unit for series in both.series} == {"each", "kg"}

    each_only = DashboardRepository(conn, USER_ID).get_item_price_history(
        ItemPriceHistoryRequest(
            identity_key="product:croissants", currency="cad", normalized_unit="each"
        )
    )
    assert len(each_only.series) == 1
    assert each_only.series[0].normalized_unit == "each"
    assert each_only.series[0].points[0].merchant_name == "TD Office"

    kg_only = DashboardRepository(conn, USER_ID).get_item_price_history(
        ItemPriceHistoryRequest(
            identity_key="product:croissants", currency="cad", normalized_unit="kg"
        )
    )
    assert len(kg_only.series) == 1
    assert kg_only.series[0].normalized_unit == "kg"
    assert kg_only.series[0].points[0].merchant_name == "FreshCo"


class FakeDashboardConnKnownItems(FakeDashboardConn):
    def execute(self, sql: str, params: dict[str, Any]) -> FakeResult:
        if "dashboard:search-known-items" in sql:
            self.calls.append((sql, params))
            return FakeResult(
                [
                    {
                        "normalized_name": "Sealtest Partly Skimmed Milk 4 L",
                        "brand": "Sealtest",
                        "taxonomy_key": "food_dining.groceries.dairy_eggs.milk.cows_milk.fresh_milk",
                        "taxonomy_name": "Milk",
                        "purchase_count": 2,
                        "last_purchased": date(2026, 8, 11),
                        "last_merchant": "FreshCo",
                    },
                    {
                        "normalized_name": "Natrel 2% Milk 4L",
                        "brand": "Natrel",
                        "taxonomy_key": "food_dining.groceries.dairy_eggs.milk.cows_milk.fresh_milk",
                        "taxonomy_name": "Milk",
                        "purchase_count": 1,
                        "last_purchased": date(2026, 7, 25),
                        "last_merchant": "FreshCo",
                    },
                ]
            )
        return super().execute(sql, params)


def test_search_known_items_returns_every_variant_matching_a_short_query() -> None:
    # This is the fix for get_item_price_history's "name:" identity match
    # being useless for discovery: it requires the exact stored text, so a
    # receipt-processing agent guessing "milk" gets nothing back from it even
    # when matching purchases exist under different wording ("Sealtest
    # Partly Skimmed Milk 4 L", "Natrel 2% Milk 4L"). search_known_items does
    # a real substring search so both are surfaced for reuse.
    conn = FakeDashboardConnKnownItems()
    response = DashboardRepository(conn, USER_ID).search_known_items(
        SearchKnownItemsRequest(query="milk")
    )

    assert response.query == "milk"
    assert [item.normalized_name for item in response.items] == [
        "Sealtest Partly Skimmed Milk 4 L",
        "Natrel 2% Milk 4L",
    ]
    assert response.items[0].purchase_count == 2
    assert response.items[0].brand == "Sealtest"


def test_search_known_items_escapes_sql_wildcards_in_the_query() -> None:
    # A literal "%" or "_" in the owner's query must not act as a SQL
    # wildcard - otherwise "50% milk" would match everything, not just
    # products containing a literal percent sign.
    conn = FakeDashboardConnKnownItems()
    DashboardRepository(conn, USER_ID).search_known_items(
        SearchKnownItemsRequest(query="50% milk_shake")
    )

    _, params = conn.calls[-1]
    assert params["pattern"] == "%50\\% milk\\_shake%"


def test_personal_basket_separates_exact_products_and_weights_by_spend() -> None:
    rows = [
        _basket_row(
            "honeycrisp apples",
            "food_dining.groceries.produce.fruit.apples_pears",
            "kg",
            "5.00",
            "6.00",
            date(2026, 5, 10),
        ),
        _basket_row(
            "greek yogurt",
            "food_dining.groceries.dairy_eggs.yogurt_fermented.yogurt",
            "kg",
            "8.00",
            "8.00",
            date(2026, 5, 5),
        ),
        _basket_row(
            "gala apples",
            "food_dining.groceries.produce.fruit.apples_pears",
            "kg",
            "4.50",
            "4.50",
            date(2026, 6, 1),
        ),
        _basket_row(
            "ground coffee",
            "food_dining.groceries.beverages.coffee",
            "kg",
            "5.00",
            "5.00",
            date(2026, 7, 1),
        ),
        _basket_row(
            "greek yogurt",
            "food_dining.groceries.dairy_eggs.yogurt_fermented.yogurt",
            "kg",
            "7.00",
            "7.00",
            date(2026, 7, 15),
        ),
        _basket_row(
            "honeycrisp apples",
            "food_dining.groceries.produce.fruit.apples_pears",
            "kg",
            "6.00",
            "7.20",
            date(2026, 7, 20),
        ),
    ]
    conn = FakeBasketConn(rows, total_tracked_spend="50.00")
    index = DashboardRepository(conn, USER_ID, today=lambda: date(2026, 7, 27)).get_personal_basket(
        PersonalBasketRequest(currency="cad")
    )

    assert index.currency == "CAD"
    assert index.window_days == 180
    assert index.product_count == 2
    labels = {product.label for product in index.products}
    assert labels == {"Test Market Honeycrisp Apples", "Greek Yogurt"}
    # total_tracked_spend comes from an independent query over ALL confirmed
    # spend across the trackable categories, not just rows with a normalized
    # name/unit price - it can be (and here is) larger than what the tracked
    # products themselves add up to, so coverage honestly reflects
    # untracked/unnormalized spend too.
    assert index.total_tracked_spend == Decimal("50.00")
    assert index.covered_spend == Decimal("28.20")
    assert index.coverage_percent == Decimal("56.4")
    # Yogurt has more raw spend (15.00) than apples (13.20), but the 35% cap
    # equalizes their influence, so the overall figure is the simple average
    # of their two deltas: (20.0 + -12.5) / 2 = 3.75, rounded to 3.8.
    assert index.overall_delta_percent == Decimal("3.8")
    assert index.confidence == "low"

    apples = next(p for p in index.products if p.label == "Test Market Honeycrisp Apples")
    assert apples.delta_percent == Decimal("20.0")
    assert apples.purchase_count == 2
    assert apples.spend_amount == Decimal("13.20")
    # Sorted by spend share: yogurt (15.00) leads apples (13.20).
    assert [p.label for p in index.products] == ["Greek Yogurt", "Test Market Honeycrisp Apples"]

    for _sql, params in conn.calls:
        assert params["currency"] == "CAD"
        assert params["window_start"] == date(2026, 1, 28)
        assert params["window_end"] == date(2026, 7, 27)


def test_personal_basket_smooths_baseline_and_current_across_multiple_purchases() -> None:
    rows = [
        _basket_row(
            "honeycrisp apples",
            "food_dining.groceries.produce.fruit.apples_pears",
            "kg",
            "10.00",
            "10.00",
            date(2026, 1, 15),
        ),
        _basket_row(
            "honeycrisp apples",
            "food_dining.groceries.produce.fruit.apples_pears",
            "kg",
            "10.00",
            "10.00",
            date(2026, 2, 15),
        ),
        _basket_row(
            "honeycrisp apples",
            "food_dining.groceries.produce.fruit.apples_pears",
            "kg",
            "10.00",
            "10.00",
            date(2026, 3, 15),
        ),
        _basket_row(
            "honeycrisp apples",
            "food_dining.groceries.produce.fruit.apples_pears",
            "kg",
            "10.00",
            "10.00",
            date(2026, 5, 15),
        ),
        _basket_row(
            "honeycrisp apples",
            "food_dining.groceries.produce.fruit.apples_pears",
            "kg",
            "15.00",
            "15.00",
            date(2026, 6, 15),
        ),
        _basket_row(
            "honeycrisp apples",
            "food_dining.groceries.produce.fruit.apples_pears",
            "kg",
            # A single one-off spike on the very last purchase - smoothing
            # exists specifically so this doesn't dominate the trend.
            "40.00",
            "40.00",
            date(2026, 7, 20),
        ),
    ]
    conn = FakeBasketConn(rows, total_tracked_spend="120.00")
    index = DashboardRepository(conn, USER_ID, today=lambda: date(2026, 7, 27)).get_personal_basket(
        PersonalBasketRequest(currency="cad")
    )

    assert index.product_count == 1
    apples = index.products[0]
    assert apples.purchase_count == 6
    # Baseline = average of the first 3 purchases (10, 10, 10) = 10.00.
    assert apples.baseline_price == Decimal("10.00")
    # Current = average of the last 3 purchases (10, 15, 40) = 21.67 - not the
    # raw 40.00 spike on the single latest receipt, which alone would read as
    # a 200% increase instead of the smoothed 116.7%.
    assert apples.current_price == Decimal("21.67")
    assert apples.delta_percent == Decimal("116.7")
    assert apples.baseline_date == date(2026, 1, 15)
    assert apples.current_date == date(2026, 7, 20)


def test_personal_basket_confidence_is_high_with_broad_coverage() -> None:
    rows = []
    for index in range(8):
        rows.append(
            _basket_row(
                f"vegetable {index}",
                "food_dining.groceries.produce.vegetables.alliums",
                "kg",
                "2.00",
                "2.00",
                date(2026, 5, 1),
            )
        )
        rows.append(
            _basket_row(
                f"vegetable {index}",
                "food_dining.groceries.produce.vegetables.alliums",
                "kg",
                "2.20",
                "2.20",
                date(2026, 7, 20),
            )
        )
    conn = FakeBasketConn(rows, total_tracked_spend="33.60")
    result = DashboardRepository(conn, USER_ID, today=lambda: date(2026, 7, 27)).get_personal_basket(
        PersonalBasketRequest(currency="cad")
    )

    assert result.product_count == 8
    assert result.coverage_percent == Decimal("100.0")
    assert result.confidence == "high"


def test_personal_basket_with_no_qualifying_products_is_honest_about_it() -> None:
    rows = [
        _basket_row(
            "honeycrisp apples",
            "food_dining.groceries.produce.fruit.apples_pears",
            "kg",
            "5.00",
            "5.00",
            date(2026, 7, 20),
        ),
    ]
    conn = FakeBasketConn(rows, total_tracked_spend="5.00")
    result = DashboardRepository(conn, USER_ID, today=lambda: date(2026, 7, 27)).get_personal_basket(
        PersonalBasketRequest(currency="cad")
    )

    assert result.product_count == 0
    assert result.overall_delta_percent is None
    assert result.confidence == "low"
    assert result.covered_spend == Decimal("0")


def test_personal_basket_splits_the_same_product_by_store_and_brand() -> None:
    # Buying the same staple at two different stores no longer blends into
    # one series - each store gets its own product, and each needs its own
    # repeat purchases to qualify.
    rows = [
        _basket_row(
            "liquid detergent",
            "housing_utilities.household_operations.laundry_supplies",
            "each",
            "12.00",
            "12.00",
            date(2026, 5, 1),
            merchant="Costco",
            brand="Tide",
        ),
        _basket_row(
            "liquid detergent",
            "housing_utilities.household_operations.laundry_supplies",
            "each",
            "13.00",
            "13.00",
            date(2026, 7, 1),
            merchant="Costco",
            brand="Tide",
        ),
        _basket_row(
            "liquid detergent",
            "housing_utilities.household_operations.laundry_supplies",
            "each",
            "14.00",
            "14.00",
            date(2026, 5, 15),
            merchant="Walmart",
            brand="Tide",
        ),
        _basket_row(
            "liquid detergent",
            "housing_utilities.household_operations.laundry_supplies",
            "each",
            "15.50",
            "15.50",
            date(2026, 7, 10),
            merchant="Walmart",
            brand="Tide",
        ),
    ]
    conn = FakeBasketConn(rows, total_tracked_spend="60.00")
    result = DashboardRepository(conn, USER_ID, today=lambda: date(2026, 7, 27)).get_personal_basket(
        PersonalBasketRequest(currency="cad")
    )

    assert result.product_count == 2
    stores = {product.merchant_name for product in result.products}
    assert stores == {"Costco", "Walmart"}
    for product in result.products:
        assert product.label == "Tide Liquid Detergent"
        assert product.purchase_count == 2


def test_personal_basket_excludes_estimated_unit_prices_from_the_query() -> None:
    # Same class of bug as Price Watch: a multi-count pack priced as "1 each" because its
    # package size was never captured shouldn't be able to swing the inflation index.
    conn = FakeBasketConn([], total_tracked_spend="0")
    DashboardRepository(conn, USER_ID, today=lambda: date(2026, 7, 27)).get_personal_basket(
        PersonalBasketRequest(currency="cad")
    )

    sql, _ = next(call for call in conn.calls if "dashboard:personal-basket" in call[0])
    assert "not i.normalized_price_is_estimated" in sql
