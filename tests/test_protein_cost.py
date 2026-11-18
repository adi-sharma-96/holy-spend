from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest

from app.protein_cost import protein_cost_line, summarize_protein_cost


def purchase(**overrides: Any) -> dict[str, Any]:
    return {
        "id": uuid4(), "transaction_id": uuid4(), "raw_name": "Synthetic beans", "normalized_name": "Beans",
        "transaction_date": date(2026, 7, 11), "currency": "CAD", "source_type": "manual",
        "transaction_type": "expense", "price_amount": Decimal(6), "price_basis_source": "subtotal_less_line_discount",
        "measured_value": Decimal(500), "measured_unit": "g", "product_identity_key": "synthetic:beans",
        "field_provenance": {
            "measured_value": {"source": "observed_receipt"}, "identity": {"source": "user_confirmed"},
            "package_size": {"source": "observed_receipt"}, "package_count": {"source": "observed_receipt"},
        },
        **overrides,
    }


def label(**overrides: Any) -> Mapping[str, Any]:
    return {
        "id": uuid4(), "source": "synthetic label", "source_ref": "synthetic:label", "status": "matched",
        "protein_label": {"basis": "per_100g", "protein_g": 20, "product_identity_key": "synthetic:beans", **overrides},
    }


def test_worked_example_and_weighted_aggregation() -> None:
    first = protein_cost_line(purchase(), label())
    second = protein_cost_line(purchase(price_amount=Decimal(20), measured_value=Decimal(1000)), label())
    generic = protein_cost_line(purchase(price_amount=Decimal(1)), label(product_identity_key=None))
    assert first.purchased_protein_g == Decimal(100)
    assert first.cost_per_100g == Decimal("6.00")
    summary = summarize_protein_cost([first, second, generic], 0)
    assert summary.total_spend == Decimal(27)
    assert summary.groups[0].cost_per_100g == Decimal("8.67")
    assert summary.groups[1].cost_per_100g == Decimal("1.00")
    assert summary.groups[0].purchased_protein_g == Decimal(300)
    assert summary.excluded_count == 0


def test_multipack_and_original_serving_basis() -> None:
    row = purchase(measured_value=None, quantity=Decimal(3), unit="each", package_value=Decimal(200), package_unit="g")
    line = protein_cost_line(row, label(basis="per_serving", serving_size_g=30, protein_g=6))
    assert line.purchase_quantity == Decimal(600)
    assert line.purchased_protein_g == Decimal(120)
    assert line.cost_per_100g == Decimal("5.00")


def test_liquid_label_and_documented_density() -> None:
    row = purchase(measured_unit="ml", measured_value=Decimal(250))
    liquid = protein_cost_line(row, label(basis="per_100ml", protein_g=Decimal(4)))
    assert liquid.purchased_protein_g == Decimal(10)
    assert liquid.cost_per_100g == Decimal("60.00")
    assert protein_cost_line(row, label()).exclusion_reason == "density_required"
    density = protein_cost_line(row, label(density_g_ml=Decimal("1.2"), density_source_ref="synthetic:density"))
    assert density.purchased_protein_g == Decimal(60)


@pytest.mark.parametrize(("changes", "facts", "reason"), [
    ({"field_provenance": {"measured_value": {"source": "estimate"}},
      "product_identity_key": None}, label(product_identity_key=None), "unverified_measurement"),
    ({"product_identity_key": "synthetic:other"}, label(), "unverified_exact_match"),
    ({}, None, "no_nutrition_match"),
    ({}, label(protein_g=0), "zero_or_unknown_protein"),
    ({"transaction_type": "refund", "price_amount": Decimal(-6)}, label(), "return_or_refund_line"),
    ({"refund_reason": "refund_allocation_unknown"}, label(), "refund_allocation_unknown"),
    ({"unallocated_discount": True}, label(), "discount_allocation_unknown"),
])
def test_reported_exclusions_are_never_priced(
    changes: dict[str, Any], facts: Mapping[str, Any] | None, reason: str,
) -> None:
    line = protein_cost_line(purchase(**changes), facts)
    assert line.exclusion_reason == reason
    assert line.purchased_protein_g is None
    summary = summarize_protein_cost([line], 0)
    assert summary.excluded_spend == line.price_amount
    assert summary.reasons == {reason: 1}
    assert all(group.cost_per_100g is None for group in summary.groups)
