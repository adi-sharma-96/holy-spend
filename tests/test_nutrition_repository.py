from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.nutrition_repository import NutritionRepository
from app.plugin_models import (
    NutrimentsInput,
    NutritionResultInput,
    NutritionSummaryRequest,
    SearchNutritionLookupsRequest,
)

USER_ID = UUID("11111111-1111-4111-8111-111111111111")
ITEM_ID = UUID("22222222-2222-4222-8222-222222222222")


@dataclass
class FakeCursor:
    rows: list[dict[str, Any]] = field(default_factory=list)
    rowcount: int = 0

    def fetchall(self) -> list[dict[str, Any]]:
        return self.rows

    def fetchone(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None


class FakeConn:
    def __init__(
        self,
        pending_rows: list[dict[str, Any]] | None = None,
        enqueued: int = 0,
        expired: int = 0,
        category_slug: str | None = "",
        lookup_search_rows: list[dict[str, Any]] | None = None,
    ) -> None:
        self.pending_rows = pending_rows or []
        self.enqueued = enqueued
        self.expired = expired
        self.category_slug = category_slug
        self.lookup_search_rows = lookup_search_rows or []
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def execute(self, sql: str, params: dict[str, Any] | None = None) -> FakeCursor:
        self.calls.append((sql, params or {}))
        if "nutrition:search-lookups" in sql:
            return FakeCursor(rows=self.lookup_search_rows)
        if "delete from nutrition_lookups" in sql:
            return FakeCursor(rowcount=self.expired)
        if "insert into nutrition_lookups" in sql and "select distinct" in sql:
            return FakeCursor(rowcount=self.enqueued)
        if "select id, product_name, brand" in sql:
            return FakeCursor(rows=self.pending_rows)
        if "select category_slug from nutrition_lookups" in sql:
            rows = [{"category_slug": self.category_slug}] if self.category_slug is not None else []
            return FakeCursor(rows=rows)
        return FakeCursor(rowcount=1)

    def updates_matching(self, needle: str) -> list[tuple[str, dict[str, Any]]]:
        return [(sql, params) for sql, params in self.calls if needle in sql]


def test_get_queue_enqueues_then_returns_pending_batch() -> None:
    conn = FakeConn(
        pending_rows=[{"id": ITEM_ID, "product_name": "2% Milk", "brand": "Kirkland Signature"}],
        enqueued=3,
    )

    response = NutritionRepository(conn, USER_ID).get_queue(limit=15)

    assert response.enqueued == 3
    assert len(response.items) == 1
    assert response.items[0].product_name == "2% Milk"
    assert response.items[0].brand == "Kirkland Signature"


def test_get_queue_scopes_by_owner_and_limit() -> None:
    conn = FakeConn()

    NutritionRepository(conn, USER_ID).get_queue(limit=7)

    fetch_call = next(call for sql, call in conn.calls if "select id, product_name, brand" in sql)
    assert fetch_call["user_id"] == USER_ID
    assert fetch_call["limit"] == 7


def test_get_queue_expires_rows_whose_items_left_the_grocery_taxonomy() -> None:
    # Real case: "Popcorn and drink" was enqueued while classified as groceries,
    # then correctly reclassified to food_dining.eating_out.quick_service (it's a
    # cinema concession, not a grocery purchase) - but nothing had ever removed the
    # now-stale nutrition_lookups row, so it kept getting retried forever for a
    # product that was never really in scope. get_queue() must expire it.
    conn = FakeConn(expired=1, enqueued=2)

    response = NutritionRepository(conn, USER_ID).get_queue(limit=10)

    assert response.expired == 1
    assert response.enqueued == 2
    delete_sql, delete_params = next(
        (sql, call) for sql, call in conn.calls if "delete from nutrition_lookups" in sql
    )
    # Only pending/no_match rows are ever candidates for deletion - matched rows
    # (real fetched nutrition data) are never silently removed, even if their item
    # also left scope.
    assert "status in ('pending', 'no_match')" in delete_sql
    assert "not exists" in delete_sql
    assert delete_params["user_id"] == USER_ID


def test_get_queue_also_retries_no_match_items_under_the_attempt_cap() -> None:
    # A no-match item never flips status back to 'pending' on its own, so get_queue
    # must explicitly select 'no_match' too (gated by an attempts cap, not a time
    # delay - no-match items are eligible again immediately, not after a cooldown)
    # or they're stuck forever.
    conn = FakeConn()

    NutritionRepository(conn, USER_ID).get_queue(limit=10)

    fetch_sql, params = next(
        (sql, call) for sql, call in conn.calls if "select id, product_name, brand" in sql
    )
    assert "status = 'no_match' and attempts <" in fetch_sql
    assert params["max_attempts"] == 5


def test_search_lookups_finds_an_already_matched_item_by_name() -> None:
    # Real case: "Compliments The Burger Sauce" was saved as matched using a
    # source-stated grade with every macro field null - it will never appear in
    # get_nutrition_queue again (that only returns pending/no_match), so this is
    # the only way to find its id and correct it with save_nutrition_result.
    conn = FakeConn(
        lookup_search_rows=[
            {
                "id": ITEM_ID,
                "product_name": "Compliments The Burger Sauce",
                "brand": "Compliments",
                "status": "matched",
                "category_slug": "food_dining.groceries.pantry_cooking.sauces_condiments.other_condiments",
                "matched_product_name": "compliments the burger sauce",
                "source": "Open Food Facts",
                "nutriscore_grade": "d",
                "attempts": 0,
            }
        ]
    )

    response = NutritionRepository(conn, USER_ID).search_lookups(
        SearchNutritionLookupsRequest(query="burger sauce")
    )

    assert response.query == "burger sauce"
    assert len(response.items) == 1
    match = response.items[0]
    assert match.id == ITEM_ID
    assert match.status == "matched"
    assert match.nutriscore_grade == "d"

    search_sql, params = next(
        (sql, call) for sql, call in conn.calls if "nutrition:search-lookups" in sql
    )
    assert "product_name ilike" in search_sql
    assert "brand ilike" in search_sql
    assert params["pattern"] == "%burger sauce%"


def test_search_lookups_escapes_sql_wildcards() -> None:
    conn = FakeConn()

    NutritionRepository(conn, USER_ID).search_lookups(
        SearchNutritionLookupsRequest(query="50% off_brand")
    )

    _, params = next((sql, call) for sql, call in conn.calls if "nutrition:search-lookups" in sql)
    assert params["pattern"] == "%50\\% off\\_brand%"


def test_save_matched_result_normalizes_per_100g_basis_as_is() -> None:
    conn = FakeConn()
    payload = NutritionResultInput(
        item_id=ITEM_ID,
        matched=True,
        product_name="2% Milk",
        source="usda_fooddata_central",
        source_ref="https://fdc.nal.usda.gov/example",
        nutriments=NutrimentsInput(
            basis="per_100g",
            energy_kcal=50,
            protein_g=3.4,
            sugars_g=4.8,
            saturated_fat_g=1.9,
            sodium_mg=44,
            fiber_g=0,
        ),
        confidence=0.9,
    )

    response = NutritionRepository(conn, USER_ID).save_result(payload)

    assert response.status == "matched"
    matched_updates = conn.updates_matching("status = 'matched'")
    assert matched_updates
    params = matched_updates[0][1]
    assert params["product_name"] == "2% Milk"
    assert params["source"] == "usda_fooddata_central"
    assert params["item_id"] == ITEM_ID
    assert params["user_id"] == USER_ID
    assert params["nutriments"].obj == {
        "energy_kcal_100g": 50,
        "protein_100g": 3.4,
        "sugars_100g": 4.8,
        "saturated_fat_100g": 1.9,
        "sodium_mg_100g": 44,
        "fiber_100g": 0,
    }


def test_save_matched_result_converts_per_serving_basis_to_per_100g() -> None:
    conn = FakeConn()
    payload = NutritionResultInput(
        item_id=ITEM_ID,
        matched=True,
        product_name="Catelli PROTEIN+ Elbows Pasta",
        source="FatSecret Canada",
        nutriments=NutrimentsInput(
            basis="per_serving",
            serving_size_g=85,
            energy_kcal=300,
            protein_g=17,
            sugars_g=2,
            saturated_fat_g=0.5,
            sodium_mg=4,
            fiber_g=8,
        ),
    )

    NutritionRepository(conn, USER_ID).save_result(payload)

    params = conn.updates_matching("status = 'matched'")[0][1]
    stored = params["nutriments"].obj
    assert stored["energy_kcal_100g"] == pytest.approx(300 / 85 * 100)
    assert stored["protein_100g"] == pytest.approx(17 / 85 * 100)


def test_save_matched_result_persists_serving_size_and_label_when_present() -> None:
    conn = FakeConn()
    payload = NutritionResultInput(
        item_id=ITEM_ID,
        matched=True,
        product_name="Catelli PROTEIN+ Elbows Pasta",
        source="FatSecret Canada",
        nutriments=NutrimentsInput(
            basis="per_serving",
            serving_size_g=85,
            serving_label="2/3 cup (85g)",
            energy_kcal=300,
            protein_g=17,
            sugars_g=2,
            saturated_fat_g=0.5,
            sodium_mg=4,
            fiber_g=8,
        ),
    )

    NutritionRepository(conn, USER_ID).save_result(payload)

    params = conn.updates_matching("status = 'matched'")[0][1]
    assert params["serving_size_g"] == 85
    assert params["serving_label"] == "2/3 cup (85g)"


def test_save_matched_result_leaves_serving_fields_null_without_a_breakdown() -> None:
    conn = FakeConn()
    payload = NutritionResultInput(
        item_id=ITEM_ID,
        matched=True,
        product_name="2% Milk",
        source="usda_fooddata_central",
        nutriments=NutrimentsInput(
            basis="per_100g",
            energy_kcal=50,
            protein_g=3.4,
            sugars_g=4.8,
            saturated_fat_g=1.9,
            sodium_mg=44,
            fiber_g=0,
        ),
    )

    NutritionRepository(conn, USER_ID).save_result(payload)

    params = conn.updates_matching("status = 'matched'")[0][1]
    assert params["serving_size_g"] is None
    assert params["serving_label"] is None


def test_per_serving_basis_requires_serving_size() -> None:
    with pytest.raises(ValidationError, match="serving_size_g is required"):
        NutrimentsInput(basis="per_serving", energy_kcal=300)


def test_sugars_cannot_exceed_carbohydrates() -> None:
    with pytest.raises(ValidationError, match="sugars_g .* cannot exceed carbohydrates_g"):
        NutrimentsInput(basis="per_100g", carbohydrates_g=10, sugars_g=41.1)


def test_saturated_fat_cannot_exceed_fat() -> None:
    with pytest.raises(ValidationError, match="saturated_fat_g .* cannot exceed fat_g"):
        NutrimentsInput(basis="per_100g", fat_g=5, saturated_fat_g=12)


def test_macro_consistency_allows_small_rounding_overshoot() -> None:
    # Real labels round independently - "5g sugars" on a "5g carbs" line can be
    # 4.6 and 4.8 underneath, so a fraction of a gram of overshoot is fine.
    payload = NutrimentsInput(basis="per_100g", carbohydrates_g=5.0, sugars_g=5.3)
    assert payload.sugars_g == 5.3


def test_save_no_match_result_increments_attempts_not_a_time_based_backoff() -> None:
    conn = FakeConn()
    payload = NutritionResultInput(item_id=ITEM_ID, matched=False)

    response = NutritionRepository(conn, USER_ID).save_result(payload)

    assert response.status == "no_match"
    no_match_updates = conn.updates_matching("status = 'no_match'")
    assert no_match_updates
    sql, params = no_match_updates[0]
    assert "attempts = attempts + 1" in sql
    assert "days" not in params


def test_matched_result_requires_product_name_and_source() -> None:
    with pytest.raises(ValidationError, match="requires product_name and source"):
        NutritionResultInput(item_id=ITEM_ID, matched=True)

    with pytest.raises(ValidationError, match="requires product_name and source"):
        NutritionResultInput(item_id=ITEM_ID, matched=True, product_name="2% Milk")


def test_no_match_result_does_not_require_provenance() -> None:
    payload = NutritionResultInput(item_id=ITEM_ID, matched=False)
    assert payload.product_name is None


def test_save_matched_result_writes_grade_and_nova_when_present() -> None:
    conn = FakeConn()
    payload = NutritionResultInput(
        item_id=ITEM_ID,
        matched=True,
        product_name="Cauliflower",
        source="Open Food Facts",
        nutriscore_grade="a",
        nova_group=1,
    )

    NutritionRepository(conn, USER_ID).save_result(payload)

    params = conn.updates_matching("status = 'matched'")[0][1]
    assert params["nutriscore_grade"] == "a"
    assert params["nova_group"] == 1


def test_grade_and_nova_are_optional_when_matched() -> None:
    payload = NutritionResultInput(
        item_id=ITEM_ID,
        matched=True,
        product_name="Bananas",
        source="USDA",
        nutriments=NutrimentsInput(
            basis="per_100g",
            energy_kcal=89,
            sugars_g=12,
            protein_g=1.1,
            saturated_fat_g=0.1,
            sodium_mg=1,
            fiber_g=2.6,
        ),
    )
    assert payload.nutriscore_grade is None
    assert payload.nova_group is None


def test_invalid_grade_is_rejected() -> None:
    with pytest.raises(ValidationError):
        NutritionResultInput(
            item_id=ITEM_ID, matched=True, product_name="X", source="Y", nutriscore_grade="z"
        )


def test_out_of_range_nova_group_is_rejected() -> None:
    with pytest.raises(ValidationError):
        NutritionResultInput(item_id=ITEM_ID, matched=True, product_name="X", source="Y", nova_group=5)
    with pytest.raises(ValidationError):
        NutritionResultInput(item_id=ITEM_ID, matched=True, product_name="X", source="Y", nova_group=0)


# --- get_summary ---


def _grocery_row(
    transaction_item_id: UUID,
    normalized_name: str,
    brand: str | None,
    line_total_amount: str,
    category_slug: str = "food_dining.groceries.dairy_eggs",
    category_name: str = "Dairy & Eggs",
    purchase_count: int = 1,
) -> dict[str, Any]:
    return {
        "transaction_item_id": transaction_item_id,
        "normalized_name": normalized_name,
        "brand": brand,
        "line_total_amount": Decimal(line_total_amount),
        "category_slug": category_slug,
        "category_name": category_name,
        "purchase_count": purchase_count,
    }


def _matched_row(
    identity_key: str,
    matched_product_name: str,
    grade: str | None = None,
    nova: int | None = None,
    nutriments: dict[str, Any] | None = None,
    status: str = "matched",
    nutriscore_source: str | None = None,
    nova_group_estimated: bool = False,
    serving_size_g: float | None = None,
    serving_label: str | None = None,
) -> dict[str, Any]:
    return {
        "identity_key": identity_key,
        "status": status,
        "matched_product_name": matched_product_name,
        "source": "Open Food Facts",
        "source_ref": "https://world.openfoodfacts.org/example",
        "nutriments": nutriments or {},
        "nutriscore_grade": grade,
        "nutriscore_source": nutriscore_source,
        "nova_group": nova,
        "nova_group_estimated": nova_group_estimated,
        "serving_size_g": serving_size_g,
        "serving_label": serving_label,
    }


class FakeSummaryConn:
    def __init__(
        self,
        matched_rows: list[dict[str, Any]],
        current_rows: list[dict[str, Any]],
        previous_rows: list[dict[str, Any]] | None = None,
    ) -> None:
        self.matched_rows = matched_rows
        self.current_rows = current_rows
        self.previous_rows = previous_rows if previous_rows is not None else []
        self._grocery_call_count = 0

    def execute(self, sql: str, params: dict[str, Any] | None = None) -> FakeCursor:
        if "from nutrition_lookups" in sql:
            return FakeCursor(rows=self.matched_rows)
        if "from transaction_items item" in sql:
            self._grocery_call_count += 1
            rows = self.current_rows if self._grocery_call_count == 1 else self.previous_rows
            return FakeCursor(rows=rows)
        raise AssertionError(f"Unexpected query: {sql}")


def test_get_summary_flattens_matched_item_facts() -> None:
    row = _grocery_row(ITEM_ID, "2% Milk", "Kirkland Signature", "5.00")
    matched = _matched_row(
        "2-milk::kirkland-signature",
        "Kirkland 2% Milk",
        grade="a",
        nova=1,
        nutriments={"energy_kcal_100g": 50, "protein_100g": 3.4},
    )
    conn = FakeSummaryConn(matched_rows=[matched], current_rows=[row])

    summary = NutritionRepository(conn, USER_ID).get_summary(
        NutritionSummaryRequest(currency="CAD"), today=lambda: date(2026, 8, 15)
    )

    assert len(summary.groups) == 1
    item = summary.groups[0].items[0]
    assert item.status == "matched"
    # display_name is always what the owner bought (normalized_name), never
    # the matched source's own product name ("Kirkland 2% Milk") - that would
    # show a different name here than Price Watch shows for the same purchase.
    assert item.display_name == "2% Milk"
    assert item.nutriscore_grade == "a"
    assert item.nova_group == 1
    assert item.energy_kcal_100g == 50
    assert item.protein_100g == 3.4


def test_get_summary_produce_ignores_brand_when_matching_to_a_lookup() -> None:
    # Simulates the SQL grouping not having merged these (e.g. old data from before the
    # produce-brand-blind grouping shipped) - the Python-side identity resolution should
    # still land both on the one lookup row, since produce brand is nutritionally moot.
    branded_row = _grocery_row(
        ITEM_ID, "Cauliflower", "Dole", "5.99", category_slug="food_dining.groceries.produce"
    )
    unbranded_row = _grocery_row(
        UUID("33333333-3333-4333-8333-333333333333"),
        "Cauliflower",
        None,
        "4.97",
        category_slug="food_dining.groceries.produce",
    )
    matched = _matched_row("cauliflower::", "Cauliflower, raw", grade="a", nova=1)
    conn = FakeSummaryConn(matched_rows=[matched], current_rows=[branded_row, unbranded_row])

    summary = NutritionRepository(conn, USER_ID).get_summary(
        NutritionSummaryRequest(currency="CAD"), today=lambda: date(2026, 8, 15)
    )

    items = summary.groups[0].items
    assert len(items) == 2
    assert all(item.status == "matched" and item.nutriscore_grade == "a" for item in items)


def test_get_summary_unmatched_item_has_no_facts() -> None:
    row = _grocery_row(ITEM_ID, "Bananas", None, "3.00")
    conn = FakeSummaryConn(matched_rows=[], current_rows=[row])

    summary = NutritionRepository(conn, USER_ID).get_summary(
        NutritionSummaryRequest(currency="CAD"), today=lambda: date(2026, 8, 15)
    )

    item = summary.groups[0].items[0]
    assert item.status == "pending"
    assert item.display_name == "Bananas"
    assert item.nutriscore_grade is None
    assert item.energy_kcal_100g is None
    assert summary.matched_item_count == 0
    assert summary.total_item_count == 1


def test_get_summary_groups_by_category_ordered_by_spend() -> None:
    rows = [
        _grocery_row(ITEM_ID, "Milk", None, "2.00", "food_dining.groceries.dairy_eggs", "Dairy & Eggs"),
        _grocery_row(
            UUID("33333333-3333-4333-8333-333333333333"),
            "Chips",
            None,
            "20.00",
            "food_dining.groceries.snacks",
            "Snacks & Pantry",
        ),
    ]
    conn = FakeSummaryConn(matched_rows=[], current_rows=rows)

    summary = NutritionRepository(conn, USER_ID).get_summary(
        NutritionSummaryRequest(currency="CAD"), today=lambda: date(2026, 8, 15)
    )

    assert [group.category_name for group in summary.groups] == ["Snacks & Pantry", "Dairy & Eggs"]


def test_get_summary_grade_distribution_sums_to_total_spend() -> None:
    rows = [
        _grocery_row(ITEM_ID, "Milk", "Kirkland Signature", "10.00"),
        _grocery_row(UUID("33333333-3333-4333-8333-333333333333"), "Bananas", None, "5.00"),
    ]
    matched = [_matched_row("milk::kirkland-signature", "Milk", grade="a")]
    conn = FakeSummaryConn(matched_rows=matched, current_rows=rows)

    summary = NutritionRepository(conn, USER_ID).get_summary(
        NutritionSummaryRequest(currency="CAD"), today=lambda: date(2026, 8, 15)
    )

    total_share = sum(bucket.share_percent for bucket in summary.grade_distribution)
    assert total_share == pytest.approx(Decimal("100.0"), abs=Decimal("0.2"))
    grades = {bucket.grade for bucket in summary.grade_distribution}
    assert grades == {"a", "unknown"}


def test_get_summary_weighted_grade_caps_a_dominant_item() -> None:
    # covered_spend = 700 + 4*100 = 1100, cap = 1100*0.35 = 385. The dominant item's weight
    # is capped to 385 instead of counting its full 700, so it can't fully drag the overall
    # grade down to its own "e" - uncapped this would average to "d", capped it lands on "c".
    dominant = _grocery_row(ITEM_ID, "Cheap Snack", "BrandA", "700.00")
    others = [
        _grocery_row(UUID(int=i + 10), f"Healthy Item {i}", "BrandB", "100.00")
        for i in range(4)
    ]
    matched = [_matched_row("cheap-snack::branda", "Cheap Snack", grade="e")] + [
        _matched_row(f"healthy-item-{i}::brandb", f"Healthy Item {i}", grade="a") for i in range(4)
    ]
    conn = FakeSummaryConn(matched_rows=matched, current_rows=[dominant, *others])

    summary = NutritionRepository(conn, USER_ID).get_summary(
        NutritionSummaryRequest(currency="CAD"), today=lambda: date(2026, 8, 15)
    )

    assert summary.overall_grade == "c"


def test_get_summary_confidence_and_coverage_thresholds() -> None:
    grocery_rows = [_grocery_row(UUID(int=i + 1), f"Item {i}", None, "5.00") for i in range(8)]
    matched_rows = [
        _matched_row(f"{row['normalized_name'].lower().replace(' ', '-')}::", row["normalized_name"], grade="a")
        for row in grocery_rows
    ]
    conn = FakeSummaryConn(matched_rows=matched_rows, current_rows=grocery_rows)

    summary = NutritionRepository(conn, USER_ID).get_summary(
        NutritionSummaryRequest(currency="CAD"), today=lambda: date(2026, 8, 15)
    )

    assert summary.total_item_count == 8
    assert summary.matched_item_count == 8
    assert summary.coverage_percent == Decimal("100.0")
    assert summary.confidence == "high"


def test_get_summary_low_confidence_with_few_items() -> None:
    conn = FakeSummaryConn(matched_rows=[], current_rows=[_grocery_row(ITEM_ID, "Milk", None, "5.00")])

    summary = NutritionRepository(conn, USER_ID).get_summary(
        NutritionSummaryRequest(currency="CAD"), today=lambda: date(2026, 8, 15)
    )

    assert summary.confidence == "low"


def test_get_summary_grade_trend_signal_only_with_both_windows_graded() -> None:
    current = [_grocery_row(ITEM_ID, "Milk", "BrandA", "5.00")]
    matched_current = [_matched_row("milk::branda", "Milk", grade="c")]
    conn_no_previous = FakeSummaryConn(matched_rows=matched_current, current_rows=current, previous_rows=[])

    summary = NutritionRepository(conn_no_previous, USER_ID).get_summary(
        NutritionSummaryRequest(currency="CAD"), today=lambda: date(2026, 8, 15)
    )

    assert not any(signal.kind == "grade_trend" for signal in summary.signals)


def test_get_summary_processing_level_signal_for_mostly_whole_foods() -> None:
    rows = [
        _grocery_row(ITEM_ID, "Milk", "BrandA", "5.00"),
        _grocery_row(UUID("33333333-3333-4333-8333-333333333333"), "Yogurt", "BrandB", "5.00"),
    ]
    matched = [
        _matched_row("milk::branda", "Milk", nova=1),
        _matched_row("yogurt::brandb", "Yogurt", nova=2),
    ]
    conn = FakeSummaryConn(matched_rows=matched, current_rows=rows)

    summary = NutritionRepository(conn, USER_ID).get_summary(
        NutritionSummaryRequest(currency="CAD"), today=lambda: date(2026, 8, 15)
    )

    processing_signals = [s for s in summary.signals if s.kind == "processing_level"]
    assert processing_signals
    assert processing_signals[0].tone == "neutral"


# --- status exposure, purchase aggregation, NOVA estimation, Nutri-Score wiring ---


def test_get_summary_surfaces_purchase_count_from_grouped_row() -> None:
    row = _grocery_row(ITEM_ID, "Milk", "BrandA", "15.00", purchase_count=3)
    conn = FakeSummaryConn(matched_rows=[], current_rows=[row])

    summary = NutritionRepository(conn, USER_ID).get_summary(
        NutritionSummaryRequest(currency="CAD"), today=lambda: date(2026, 8, 15)
    )

    item = summary.groups[0].items[0]
    assert item.purchase_count == 3
    assert item.spend_amount == Decimal("15.00")


def test_get_summary_status_no_match_when_lookup_tried_and_failed() -> None:
    row = _grocery_row(ITEM_ID, "Trail Mix", "BrandA", "8.00")
    matched = _matched_row("trail-mix::branda", "Trail Mix", status="no_match")
    conn = FakeSummaryConn(matched_rows=[matched], current_rows=[row])

    summary = NutritionRepository(conn, USER_ID).get_summary(
        NutritionSummaryRequest(currency="CAD"), today=lambda: date(2026, 8, 15)
    )

    item = summary.groups[0].items[0]
    assert item.status == "no_match"
    assert summary.matched_item_count == 0


def test_get_summary_surfaces_nova_group_estimated() -> None:
    row = _grocery_row(ITEM_ID, "Granola Bar", "BrandA", "6.00")
    matched = _matched_row("granola-bar::branda", "Granola Bar", nova=4, nova_group_estimated=True)
    conn = FakeSummaryConn(matched_rows=[matched], current_rows=[row])

    summary = NutritionRepository(conn, USER_ID).get_summary(
        NutritionSummaryRequest(currency="CAD"), today=lambda: date(2026, 8, 15)
    )

    item = summary.groups[0].items[0]
    assert item.nova_group == 4
    assert item.nova_group_estimated is True


def test_save_matched_result_records_nova_estimated_flag() -> None:
    conn = FakeConn()
    payload = NutritionResultInput(
        item_id=ITEM_ID,
        matched=True,
        product_name="Granola Bar",
        source="Open Food Facts",
        nova_group=4,
        nova_group_estimated=True,
        nutriments=NutrimentsInput(
            basis="per_100g",
            energy_kcal=450,
            sugars_g=20,
            protein_g=8,
            saturated_fat_g=5,
            sodium_mg=300,
            fiber_g=3,
        ),
    )

    NutritionRepository(conn, USER_ID).save_result(payload)

    params = conn.updates_matching("status = 'matched'")[0][1]
    assert params["nova_group"] == 4
    assert params["nova_group_estimated"] is True


def test_nova_estimated_requires_nova_group() -> None:
    with pytest.raises(ValidationError, match="nova_group_estimated requires nova_group"):
        NutritionResultInput(
            item_id=ITEM_ID, matched=True, product_name="X", source="Y", nova_group_estimated=True
        )


def test_save_matched_result_computes_nutriscore_when_inputs_complete() -> None:
    conn = FakeConn(category_slug="food_dining.groceries.dairy_eggs")
    payload = NutritionResultInput(
        item_id=ITEM_ID,
        matched=True,
        product_name="Plain Yogurt",
        source="Open Food Facts",
        nutriments=NutrimentsInput(
            basis="per_100g",
            energy_kcal=50,
            sugars_g=0,
            saturated_fat_g=0,
            sodium_mg=5,
            fiber_g=5,
            protein_g=5,
        ),
    )

    NutritionRepository(conn, USER_ID).save_result(payload)

    params = conn.updates_matching("status = 'matched'")[0][1]
    assert params["nutriscore_grade"] == "a"
    assert params["nutriscore_source"] == "computed"


def test_save_matched_result_computes_beverages_via_the_beverage_table() -> None:
    # Beverages used to be entirely unscored (BEVERAGE_TAXONOMY_PREFIX matched
    # everything under "beverages." and compute_nutriscore returned None
    # unconditionally). They're now scored with the real category-specific
    # beverage algorithm - and, same as every other category, a computed grade
    # overrides a source-stated one when all 6 macros are present.
    conn = FakeConn(category_slug="food_dining.groceries.beverages.soft_drinks")
    payload = NutritionResultInput(
        item_id=ITEM_ID,
        matched=True,
        product_name="Cola",
        source="Open Food Facts",
        nutriscore_grade="d",
        nutriments=NutrimentsInput(
            basis="per_100g",
            energy_kcal=180,
            sugars_g=10,
            saturated_fat_g=0,
            sodium_mg=5,
            fiber_g=0,
            protein_g=0,
        ),
    )

    NutritionRepository(conn, USER_ID).save_result(payload)

    params = conn.updates_matching("status = 'matched'")[0][1]
    assert params["nutriscore_source"] == "computed"
    assert params["nutriscore_grade"] == "e"


def test_save_matched_result_falls_back_to_source_stated_grade_when_inputs_incomplete() -> None:
    conn = FakeConn(category_slug="food_dining.groceries.dairy_eggs")
    payload = NutritionResultInput(
        item_id=ITEM_ID,
        matched=True,
        product_name="Cheese Wedge",
        source="Open Food Facts",
        nutriscore_grade="b",
        nutriments=NutrimentsInput(basis="per_100g", energy_kcal=300, protein_g=20),
    )

    NutritionRepository(conn, USER_ID).save_result(payload)

    params = conn.updates_matching("status = 'matched'")[0][1]
    assert params["nutriscore_grade"] == "b"
    assert params["nutriscore_source"] == "source_stated"


def test_matched_result_rejected_when_missing_even_one_core_field_and_no_source_grade() -> None:
    # 5 of 6 required fields (missing fiber) used to be enough to pass the completeness
    # gate, but compute_nutriscore() needs all 6 - a match that passes but can never be
    # scored is worse than an honest rejection, so the gate now requires every field
    # unless the source stated a grade directly.
    with pytest.raises(ValidationError, match="needs either a source-stated nutriscore_grade"):
        NutritionResultInput(
            item_id=ITEM_ID,
            matched=True,
            product_name="Mystery Item",
            source="Open Food Facts",
            nutriments=NutrimentsInput(
                basis="per_100g", energy_kcal=300, sugars_g=5, saturated_fat_g=2, sodium_mg=100, protein_g=10
            ),
        )


def test_matched_result_rejected_when_too_few_macros_and_no_source_grade() -> None:
    # Only energy + protein, no grade either - this can never be scored, so the tool
    # should reject it outright rather than silently accepting a useless "match".
    with pytest.raises(ValidationError, match="needs either a source-stated nutriscore_grade"):
        NutritionResultInput(
            item_id=ITEM_ID,
            matched=True,
            product_name="Mystery Item",
            source="Open Food Facts",
            nutriments=NutrimentsInput(basis="per_100g", energy_kcal=300, protein_g=20),
        )


def test_matched_result_with_few_macros_allowed_when_grade_is_source_stated() -> None:
    # A real source-stated grade is valuable on its own even with a thin macro panel -
    # only the "neither macros nor a grade" combination should be rejected.
    payload = NutritionResultInput(
        item_id=ITEM_ID,
        matched=True,
        product_name="Mystery Item",
        source="Open Food Facts",
        nutriscore_grade="c",
        nutriments=NutrimentsInput(basis="per_100g", energy_kcal=300, protein_g=20),
    )
    assert payload.nutriscore_grade == "c"
