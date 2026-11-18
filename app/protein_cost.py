from collections import Counter
from collections.abc import Mapping
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.measurements import normalize_unit
from app.plugin_models import ProteinCostGroup, ProteinCostLine, ProteinCostSummary, ProteinLabel
from app.product_evidence import TRUSTED_MEASUREMENTS, EvidenceSource, ItemEvidence


def _finite(value: Any) -> Decimal | None:
    if value is None:
        return None
    number = Decimal(str(value))
    return number if number.is_finite() else None


def _purchase_measurement(
    row: Mapping[str, Any], evidence: ItemEvidence,
) -> tuple[Decimal | None, str | None, str | None]:
    value = row.get("measured_value")
    unit = row.get("measured_unit")
    if value is not None:
        if evidence.measured_value.source not in TRUSTED_MEASUREMENTS:
            return None, None, "unverified_measurement"
    elif row.get("package_value") is not None:
        if evidence.package_size.source not in TRUSTED_MEASUREMENTS:
            return None, None, "unverified_package_size"
        count = _finite(row.get("quantity"))
        count_unit = normalize_unit(row.get("unit"))
        if (count is None or count <= 0 or count != count.to_integral_value()
                or evidence.package_count.source not in TRUSTED_MEASUREMENTS
                or (row.get("unit") is not None and (count_unit is None or count_unit.normalized_unit != "each"))):
            return None, None, "unverified_package_count"
        value = row["package_value"] * count
        unit = row.get("package_unit")
    elif evidence.quantity.source in TRUSTED_MEASUREMENTS:
        value = row.get("quantity")
        unit = row.get("unit")
    measurement = _finite(value)
    definition = normalize_unit(unit)
    if measurement is None or measurement <= 0 or definition is None or definition.normalized_unit == "each":
        return None, None, "missing_physical_quantity"
    base_unit = "g" if definition.normalized_unit == "kg" else "mL"
    return measurement * definition.factor * 1000, base_unit, None


def protein_cost_line(
    row: Mapping[str, Any], lookup: Mapping[str, Any] | None,
) -> ProteinCostLine:
    """Evaluate one line in its recorded currency and original label units."""
    evidence = ItemEvidence.model_validate(row.get("field_provenance") or {})
    label = ProteinLabel.model_validate(lookup["protein_label"]) if lookup and lookup.get("protein_label") else None
    amount = Decimal(str(row["price_amount"]))
    quantity, unit, quantity_error = _purchase_measurement(row, evidence)
    matched = lookup is not None and lookup["status"] == "matched"
    reason = None
    if row["transaction_type"] == "refund":
        reason = "return_or_refund_line"
    elif row.get("refund_reason"):
        reason = row["refund_reason"]
    elif row.get("unallocated_discount"):
        reason = "discount_allocation_unknown"
    elif amount < 0:
        reason = "invalid_purchase_cost"
    elif not matched:
        reason = "no_nutrition_match"
    elif label is None or not lookup or not lookup.get("source_ref"):
        reason = "original_label_unverified"
    elif label.product_identity_key and (
        evidence.identity.source != EvidenceSource.USER_CONFIRMED
        or row.get("product_identity_key") != label.product_identity_key
    ):
        reason = "unverified_exact_match"
    elif quantity_error:
        reason = quantity_error
    elif not label.protein_g or label.protein_g <= 0:
        reason = "zero_or_unknown_protein"

    grams = None
    if reason is None and label is not None and quantity is not None:
        basis_unit = "mL" if label.basis == "per_100ml" else "g"
        equivalent_quantity = quantity
        if unit != basis_unit and label.density_g_ml is None:
            reason = "density_required"
        elif unit != basis_unit and label.density_g_ml is not None:
            equivalent_quantity = quantity * label.density_g_ml if unit == "mL" else quantity / label.density_g_ml
        if reason is None:
            serving = label.serving_size_g if label.basis == "per_serving" else Decimal(100)
            assert serving is not None
            grams = equivalent_quantity * label.protein_g / serving

    return ProteinCostLine(
        item_id=row["id"], transaction_id=row["transaction_id"], purchase_date=row["transaction_date"],
        display_name=row.get("normalized_name") or row["raw_name"], currency=row["currency"],
        price_source=row["source_type"], price_amount=amount, price_basis="net_line_before_tax_and_fees",
        price_basis_source=row["price_basis_source"],
        nutrition_source=lookup.get("source") if lookup else None,
        nutrition_source_ref=lookup.get("source_ref") if lookup else None,
        nutrition_recorded_at=lookup.get("updated_at") if lookup else None,
        nutrition_lookup_id=lookup.get("id") if lookup else None,
        match_type=("exact" if label and label.product_identity_key else "generic") if label else None,
        protein_label=label, purchase_quantity=quantity, purchase_unit=unit,
        purchased_protein_g=grams, exclusion_reason=reason,
        cost_per_100g=(amount * 100 / grams).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if grams else None,
    )


def summarize_protein_cost(lines: list[ProteinCostLine], offset: int) -> ProteinCostSummary:
    eligible = [line for line in lines if line.exclusion_reason is None]
    groups = []
    for match_type in ("exact", "generic"):
        subset = [line for line in eligible if line.match_type == match_type]
        amount = sum((line.price_amount for line in subset), Decimal(0))
        grams = sum((line.purchased_protein_g or Decimal(0) for line in subset), Decimal(0))
        groups.append(ProteinCostGroup(
            match_type=match_type, eligible_count=len(subset), eligible_spend=amount, purchased_protein_g=grams,
            cost_per_100g=(amount * 100 / grams).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if grams else None,
        ))
    return ProteinCostSummary(
        groups=groups, total_count=len(lines), excluded_count=len(lines) - len(eligible),
        total_spend=sum((line.price_amount for line in lines), Decimal(0)),
        excluded_spend=sum((line.price_amount for line in lines if line.exclusion_reason is not None), Decimal(0)),
        reasons=dict(Counter(line.exclusion_reason for line in lines if line.exclusion_reason is not None)),
        detail_offset=offset, lines=lines[offset:offset + 25],
    )
