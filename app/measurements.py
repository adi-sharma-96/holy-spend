from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

PRICE_QUANTUM = Decimal("0.000001")


@dataclass(frozen=True)
class UnitDefinition:
    normalized_unit: str
    factor: Decimal


@dataclass(frozen=True)
class NormalizedPrice:
    normalized_unit: str | None
    normalized_unit_price_amount: Decimal | None
    is_estimated: bool = False


UNIT_DEFINITIONS: dict[str, UnitDefinition] = {
    # Mass is normalized to kilograms.
    "kg": UnitDefinition("kg", Decimal("1")),
    "kgs": UnitDefinition("kg", Decimal("1")),
    "kilogram": UnitDefinition("kg", Decimal("1")),
    "kilograms": UnitDefinition("kg", Decimal("1")),
    "g": UnitDefinition("kg", Decimal("0.001")),
    "gram": UnitDefinition("kg", Decimal("0.001")),
    "grams": UnitDefinition("kg", Decimal("0.001")),
    "lb": UnitDefinition("kg", Decimal("0.45359237")),
    "lbs": UnitDefinition("kg", Decimal("0.45359237")),
    "pound": UnitDefinition("kg", Decimal("0.45359237")),
    "pounds": UnitDefinition("kg", Decimal("0.45359237")),
    "oz": UnitDefinition("kg", Decimal("0.028349523125")),
    "ounce": UnitDefinition("kg", Decimal("0.028349523125")),
    "ounces": UnitDefinition("kg", Decimal("0.028349523125")),
    # Volume is normalized to litres. Ambiguous "fl oz" is intentionally excluded.
    "l": UnitDefinition("L", Decimal("1")),
    "liter": UnitDefinition("L", Decimal("1")),
    "liters": UnitDefinition("L", Decimal("1")),
    "litre": UnitDefinition("L", Decimal("1")),
    "litres": UnitDefinition("L", Decimal("1")),
    "ml": UnitDefinition("L", Decimal("0.001")),
    "milliliter": UnitDefinition("L", Decimal("0.001")),
    "milliliters": UnitDefinition("L", Decimal("0.001")),
    "millilitre": UnitDefinition("L", Decimal("0.001")),
    "millilitres": UnitDefinition("L", Decimal("0.001")),
    # Discrete goods are normalized to each.
    "ea": UnitDefinition("each", Decimal("1")),
    "each": UnitDefinition("each", Decimal("1")),
    "ct": UnitDefinition("each", Decimal("1")),
    "count": UnitDefinition("each", Decimal("1")),
    "pc": UnitDefinition("each", Decimal("1")),
    "pcs": UnitDefinition("each", Decimal("1")),
    "piece": UnitDefinition("each", Decimal("1")),
    "pieces": UnitDefinition("each", Decimal("1")),
    "unit": UnitDefinition("each", Decimal("1")),
    "units": UnitDefinition("each", Decimal("1")),
    "item": UnitDefinition("each", Decimal("1")),
    "items": UnitDefinition("each", Decimal("1")),
}


def _decimal(value: Decimal | int | float | str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def normalize_unit(unit: str | None) -> UnitDefinition | None:
    if unit is None:
        return None
    candidate = unit.strip().lower().replace(".", "")
    return UNIT_DEFINITIONS.get(candidate)


def _paid_amount(
    *,
    line_subtotal_amount: Decimal | None,
    line_discount_amount: Decimal | None,
    line_tax_amount: Decimal | None,
    line_fee_amount: Decimal | None,
    line_total_amount: Decimal,
) -> Decimal:
    if line_subtotal_amount is not None:
        return abs(line_subtotal_amount - (line_discount_amount or Decimal("0")))
    return abs(
        line_total_amount
        - (line_tax_amount or Decimal("0"))
        - (line_fee_amount or Decimal("0"))
    )


def _normalized_quantity(
    value: Decimal | None,
    unit: str | None,
) -> tuple[str, Decimal] | None:
    if value is None or value <= 0:
        return None
    definition = normalize_unit(unit)
    if definition is None:
        return None
    return definition.normalized_unit, value * definition.factor


def derive_normalized_price(
    *,
    quantity: Decimal | None,
    unit: str | None,
    measured_value: Decimal | None,
    measured_unit: str | None,
    package_value: Decimal | None,
    package_unit: str | None,
    unit_price_amount: Decimal | None,
    unit_price_basis_value: Decimal | None,
    unit_price_basis_unit: str | None,
    line_subtotal_amount: Decimal | None,
    line_discount_amount: Decimal | None,
    line_tax_amount: Decimal | None,
    line_fee_amount: Decimal | None,
    line_total_amount: Decimal,
) -> NormalizedPrice:
    """Derive a comparable price without discarding the receipt's original units."""

    values = {
        "quantity": _decimal(quantity),
        "measured_value": _decimal(measured_value),
        "package_value": _decimal(package_value),
        "unit_price_amount": _decimal(unit_price_amount),
        "unit_price_basis_value": _decimal(unit_price_basis_value),
        "line_subtotal_amount": _decimal(line_subtotal_amount),
        "line_discount_amount": _decimal(line_discount_amount),
        "line_tax_amount": _decimal(line_tax_amount),
        "line_fee_amount": _decimal(line_fee_amount),
        "line_total_amount": _decimal(line_total_amount),
    }
    total = values["line_total_amount"]
    if total is None:
        return NormalizedPrice(None, None)

    # A printed basis such as "$2.99 / lb" is the most direct evidence.
    basis = _normalized_quantity(values["unit_price_basis_value"], unit_price_basis_unit)
    printed_price = values["unit_price_amount"]
    if basis is not None and printed_price is not None and printed_price >= 0:
        normalized_unit, normalized_basis = basis
        return NormalizedPrice(
            normalized_unit,
            (printed_price / normalized_basis).quantize(PRICE_QUANTUM, rounding=ROUND_HALF_UP),
        )

    comparable_quantity = _normalized_quantity(values["measured_value"], measured_unit)

    # For packaged goods, quantity is the number of packages. If it was not
    # captured, one package is the conservative default.
    if comparable_quantity is None and values["package_value"] is not None:
        package_quantity = _normalized_quantity(values["package_value"], package_unit)
        if package_quantity is not None:
            normalized_unit, normalized_package_value = package_quantity
            package_count = values["quantity"] or Decimal("1")
            if package_count > 0:
                comparable_quantity = normalized_unit, normalized_package_value * package_count

    # A bare "no unit at all" quantity can't be told apart from a multi-count package
    # whose package_value/package_unit was never captured - treating it as "1 each" is
    # only a guess, not a grounded per-unit price.
    is_estimated = False
    if comparable_quantity is None:
        if unit is None and values["quantity"] is not None and values["quantity"] > 0:
            comparable_quantity = "each", values["quantity"]
            is_estimated = True
        else:
            comparable_quantity = _normalized_quantity(values["quantity"], unit)

    if comparable_quantity is None:
        return NormalizedPrice(None, None)

    normalized_unit, normalized_quantity = comparable_quantity
    paid = _paid_amount(
        line_subtotal_amount=values["line_subtotal_amount"],
        line_discount_amount=values["line_discount_amount"],
        line_tax_amount=values["line_tax_amount"],
        line_fee_amount=values["line_fee_amount"],
        line_total_amount=total,
    )
    return NormalizedPrice(
        normalized_unit,
        (paid / normalized_quantity).quantize(PRICE_QUANTUM, rounding=ROUND_HALF_UP),
        is_estimated=is_estimated,
    )
