from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.models import TransactionItemCreate
from app.product_evidence import ItemEvidence, decide_comparison, invalidate_edited_evidence, readiness_reasons


def verified(**changes: object) -> dict[str, object]:
    row: dict[str, object] = {
        "currency": "CAD",
        "taxonomy_key": "food_dining.groceries.produce.fruit.apples_pears.apples",
        "classification_review_status": "reviewed",
        "product_identity_key": "honeycrisp-apple",
        "product_type_key": "apple.honeycrisp",
        "field_provenance": {
            "identity": {"source": "user_confirmed", "source_ref": "review:1"},
            "product_type": {"source": "observed_receipt", "source_text": "Honeycrisp"},
            "measured_value": {"source": "observed_receipt", "source_text": "1 kg"},
            "package_size": {"source": "observed_receipt", "source_text": "1 kg"},
            "package_count": {"source": "observed_receipt", "source_text": "1 pack"},
        },
        "normalized_unit": "kg",
        "normalized_unit_price_amount": Decimal("5.00"),
        "normalized_price_is_estimated": False,
        "measured_value": Decimal("1"),
        "package_value": None,
        "quantity": None,
    }
    row.update(changes)
    return row


@pytest.mark.parametrize(
    ("left_type", "right_type"),
    [
        ("fruit.apple", "fruit.kiwi"),
        ("yogurt.greek", "yogurt.dahi"),
        ("pepper.bell", "pepper.thai_chilli"),
        ("frozen.berries", "frozen.peas"),
        ("flour.corn", "flour.ragi"),
        ("dal.urad", "dal.moong"),
        ("milk.almond", "milk.cow"),
    ],
)
def test_distinct_types_never_compare(left_type: str, right_type: str) -> None:
    left = verified(product_type_key=left_type)
    right = verified(product_type_key=right_type)
    decision = decide_comparison(left, right)
    assert not decision.eligible
    assert "product_type_mismatch" in decision.reasons


def test_repeat_purchase_across_merchants_and_package_sizes_can_compare() -> None:
    left = verified(merchant="A", package_value=Decimal("500"), measured_value=None)
    right = verified(merchant="B", package_value=Decimal("1000"), measured_value=None,
                     normalized_unit_price_amount=Decimal("4.50"))
    assert decide_comparison(left, right).eligible


def test_brand_or_price_cannot_establish_identity() -> None:
    left = verified(product_identity_key=None, brand="Same brand")
    right = verified(product_identity_key=None, brand="Same brand",
                     normalized_unit_price_amount=Decimal("5.00"))
    assert "unresolved_identity" in decide_comparison(left, right).reasons


def test_unknown_legacy_and_estimated_measurement_stay_excluded() -> None:
    legacy = verified(field_provenance={}, product_identity_key=None,
                      taxonomy_key="food_dining.groceries.frozen_food.frozen_produce")
    assert "broad_taxonomy" in readiness_reasons(legacy)
    assert "unresolved_identity" in readiness_reasons(legacy)
    estimated = verified(field_provenance={
        **verified()["field_provenance"],  # type: ignore[dict-item]
        "package_size": {"source": "estimate", "source_text": "500 g"},
    }, measured_value=None, package_value=Decimal("500"))
    assert "unverified_package_size" in readiness_reasons(estimated)


def test_dimension_currency_and_substitution_rules_are_explicit() -> None:
    first = verified()
    assert "currency_mismatch" in decide_comparison(first, verified(currency="USD")).reasons
    assert "measurement_dimension_mismatch" in decide_comparison(
        first, verified(normalized_unit="L")
    ).reasons
    assert "substitution_preferences_unavailable" in decide_comparison(
        first, verified(), kind="substitute"
    ).reasons


def test_estimated_package_provenance_survives_model_round_trip() -> None:
    item = TransactionItemCreate(
        raw_name="Sample oats", normalized_name="Sample oats",
        taxonomy_node_key="food_dining.groceries.breakfast.cereal_granola",
        package_value=Decimal("500"), package_unit="g", quantity=Decimal("1"),
        line_total_amount=Decimal("4.99"),
        field_provenance={"package_size": {"source": "estimate", "source_text": "500 g"}},
    )
    round_trip = TransactionItemCreate.model_validate_json(item.model_dump_json())
    assert round_trip.field_provenance.package_size.source == "estimate"
    assert ItemEvidence.model_validate({}).package_size.source == "unknown"


@pytest.mark.parametrize(
    ("edit", "invalidated"),
    [
        ({"quantity": Decimal("10")}, {"quantity", "package_count", "identity"}),
        ({"unit": "pack"}, {"quantity", "package_size", "package_count", "measured_value", "identity"}),
        ({"raw_name": "Gala apples"}, {"identity", "product_type", "brand", "quantity",
                                          "package_size", "package_count", "measured_value"}),
        ({"unit_price_basis_value": Decimal("2")}, {"measured_value"}),
        ({"line_total_amount": Decimal("10")}, {"quantity", "package_size", "package_count",
                                                  "measured_value"}),
    ],
)
def test_ordinary_edit_invalidates_all_dependent_evidence(
    edit: dict[str, object], invalidated: set[str]
) -> None:
    confirmed = {field: {"source": "user_confirmed"} for field in ItemEvidence.model_fields}
    current = SimpleNamespace(
        raw_name="Honeycrisp apples", quantity=Decimal("1"), unit="each",
        unit_price_basis_value=Decimal("1"), line_total_amount=Decimal("5"),
        field_provenance=ItemEvidence.model_validate(confirmed),
    )
    # Even explicitly resending the old verified evidence must not preserve it.
    result = invalidate_edited_evidence(current, edit, ItemEvidence.model_validate(confirmed))
    assert result is not None
    for field in invalidated:
        assert getattr(result, field).source == "unknown"
    if "brand" not in invalidated:
        assert result.brand.source == "user_confirmed"
