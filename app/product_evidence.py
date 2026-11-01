"""Evidence carried by receipt fields and the strict product comparison gate."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.price_watch import EXCLUDED_SPLIT_PARENT_LEAVES, EXCLUDED_TAXONOMY_LEAVES


class EvidenceSource(StrEnum):
    OBSERVED_RECEIPT = "observed_receipt"
    USER_CONFIRMED = "user_confirmed"
    HISTORICAL_INFERENCE = "historical_inference"
    EXTERNAL_MATCH = "external_match"
    ESTIMATE = "estimate"
    UNKNOWN = "unknown"


class FieldEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: EvidenceSource = EvidenceSource.UNKNOWN
    source_ref: str | None = Field(default=None, max_length=500)
    source_text: str | None = Field(default=None, max_length=500)


EVIDENCE_FIELDS = frozenset(
    {"identity", "product_type", "brand", "quantity", "package_size", "package_count", "measured_value"}
)

# A value edited through the ordinary item API no longer carries the evidence
# for the old value. The review workflow records new user confirmation itself.
EVIDENCE_INPUT_DEPENDENCIES: dict[str, frozenset[str]] = {
    "identity": frozenset({"raw_name", "interpreted_name", "normalized_name", "brand",
                           "concept_id", "variant_id", "product_identity_key", "product_type_key",
                           "taxonomy_node_id", "taxonomy_node_key", "item_role",
                           "quantity", "unit", "measured_value", "measured_unit",
                           "package_value", "package_unit"}),
    "product_type": frozenset({"raw_name", "interpreted_name", "normalized_name", "concept_id",
                               "variant_id", "product_type_key", "taxonomy_node_id", "taxonomy_node_key"}),
    "brand": frozenset({"brand"}),
    "quantity": frozenset({"quantity", "unit"}),
    "package_size": frozenset({"package_value", "package_unit", "unit"}),
    "package_count": frozenset({"quantity", "unit", "package_value", "package_unit"}),
    "measured_value": frozenset({"measured_value", "measured_unit", "unit_price_amount",
                                 "unit_price_basis_value", "unit_price_basis_unit", "unit"}),
}
PRICE_VALUE_INPUTS = frozenset({"line_subtotal_amount", "line_discount_amount", "line_tax_amount",
                                "line_fee_amount", "line_total_amount"})
PRODUCT_CONTEXT_INPUTS = frozenset({"raw_name", "interpreted_name", "normalized_name", "brand",
                                    "concept_id", "variant_id", "product_identity_key", "product_type_key",
                                    "taxonomy_node_id", "taxonomy_node_key", "item_role"})
TRUSTED_MEASUREMENTS = frozenset({EvidenceSource.OBSERVED_RECEIPT, EvidenceSource.USER_CONFIRMED})


class ItemEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identity: FieldEvidence = Field(default_factory=FieldEvidence)
    product_type: FieldEvidence = Field(default_factory=FieldEvidence)
    brand: FieldEvidence = Field(default_factory=FieldEvidence)
    quantity: FieldEvidence = Field(default_factory=FieldEvidence)
    package_size: FieldEvidence = Field(default_factory=FieldEvidence)
    package_count: FieldEvidence = Field(default_factory=FieldEvidence)
    measured_value: FieldEvidence = Field(default_factory=FieldEvidence)


def invalidate_edited_evidence(
    current: Any, updates: Mapping[str, Any], supplied: ItemEvidence | None = None
) -> ItemEvidence | None:
    """Keep unrelated evidence, but never carry verification over changed inputs."""
    changed = {field for field, value in updates.items()
               if field != "field_provenance" and getattr(current, field, None) != value}
    if not changed and supplied is None:
        return None
    evidence = (supplied or ItemEvidence.model_validate(getattr(current, "field_provenance", {})))
    values = evidence.model_dump(mode="json")
    for field, dependencies in EVIDENCE_INPUT_DEPENDENCIES.items():
        if changed & PRODUCT_CONTEXT_INPUTS or changed & dependencies or (changed & PRICE_VALUE_INPUTS and field in {
            "quantity", "package_size", "package_count", "measured_value"
        }):
            values[field] = {"source": "unknown"}
    return ItemEvidence.model_validate(values)


ComparisonKind = Literal["exact_product", "substitute"]


@dataclass(frozen=True)
class ComparisonDecision:
    eligible: bool
    kind: ComparisonKind
    reasons: tuple[str, ...]


def _value(row: Mapping[str, Any], key: str) -> Any:
    return row.get(key)


def _provenance(row: Mapping[str, Any]) -> ItemEvidence:
    value = _value(row, "field_provenance")
    return ItemEvidence.model_validate(value or {})


def readiness_reasons(row: Mapping[str, Any]) -> tuple[str, ...]:
    """Reasons one row cannot support a strict gross unit-price claim."""
    reasons: list[str] = []
    evidence = _provenance(row)
    taxonomy_key = str(_value(row, "taxonomy_key") or "")
    if (not taxonomy_key or taxonomy_key.startswith("unclassified.")
            or taxonomy_key in EXCLUDED_SPLIT_PARENT_LEAVES
            or taxonomy_key in EXCLUDED_TAXONOMY_LEAVES):
        reasons.append("broad_taxonomy")
    if _value(row, "classification_review_status") != "reviewed":
        reasons.append("taxonomy_needs_review")
    if not _value(row, "product_identity_key") or evidence.identity.source != EvidenceSource.USER_CONFIRMED:
        reasons.append("unresolved_identity")
    if not _value(row, "product_type_key") or evidence.product_type.source not in TRUSTED_MEASUREMENTS:
        reasons.append("unresolved_product_type")
    if (not _value(row, "normalized_unit")
            or (_value(row, "normalized_unit_price_amount") is None and _value(row, "price") is None)):
        reasons.append("missing_unit_price")
    if _value(row, "normalized_price_is_estimated"):
        reasons.append("estimated_unit_price")
    if _value(row, "has_refund"):
        reasons.append("refund_allocation_unknown")
    # A printed unit-price basis is independent of package size. Otherwise,
    # require evidence for the input from which normalized price was derived.
    if _value(row, "unit_price_amount") is not None and _value(row, "unit_price_basis_value") is not None:
        if evidence.measured_value.source not in TRUSTED_MEASUREMENTS:
            reasons.append("unverified_price_basis")
    elif _value(row, "measured_value") is not None:
        if evidence.measured_value.source not in TRUSTED_MEASUREMENTS:
            reasons.append("unverified_measurement")
    elif _value(row, "package_value") is not None:
        if evidence.package_size.source not in TRUSTED_MEASUREMENTS:
            reasons.append("unverified_package_size")
        if evidence.package_count.source not in TRUSTED_MEASUREMENTS:
            reasons.append("unverified_package_count")
    elif evidence.quantity.source not in TRUSTED_MEASUREMENTS:
        reasons.append("unverified_quantity")
    return tuple(dict.fromkeys(reasons))


def decide_comparison(
    left: Mapping[str, Any], right: Mapping[str, Any], *, kind: ComparisonKind = "exact_product"
) -> ComparisonDecision:
    reasons = list(readiness_reasons(left)) + list(readiness_reasons(right))
    if left.get("currency") != right.get("currency"):
        reasons.append("currency_mismatch")
    if left.get("normalized_unit") != right.get("normalized_unit"):
        reasons.append("measurement_dimension_mismatch")
    if left.get("product_type_key") != right.get("product_type_key"):
        reasons.append("product_type_mismatch")
    if kind == "exact_product":
        if left.get("product_identity_key") != right.get("product_identity_key"):
            reasons.append("identity_mismatch")
    else:
        # Compatibility preferences are not modeled yet. Do not infer a safe
        # substitution merely from sharing a family, type, leaf or brand.
        reasons.append("substitution_preferences_unavailable")
    unique = tuple(dict.fromkeys(reasons))
    return ComparisonDecision(not unique, kind, unique)
