from decimal import Decimal

from app.measurements import NormalizedPrice, derive_normalized_price, normalize_unit


def derive(**overrides: object) -> NormalizedPrice:
    values: dict[str, object] = {
        "quantity": None,
        "unit": None,
        "measured_value": None,
        "measured_unit": None,
        "package_value": None,
        "package_unit": None,
        "unit_price_amount": None,
        "unit_price_basis_value": None,
        "unit_price_basis_unit": None,
        "line_subtotal_amount": None,
        "line_discount_amount": None,
        "line_tax_amount": None,
        "line_fee_amount": None,
        "line_total_amount": Decimal("0"),
    }
    values.update(overrides)
    return derive_normalized_price(**values)  # type: ignore[arg-type]


def normalized(**overrides: object) -> tuple[str | None, Decimal | None]:
    result = derive(**overrides)
    return result.normalized_unit, result.normalized_unit_price_amount


def test_mass_unit_aliases_normalize_to_kilograms() -> None:
    assert normalize_unit("LB") is not None
    assert normalize_unit("LB").normalized_unit == "kg"  # type: ignore[union-attr]
    assert normalize_unit("grams").factor == Decimal("0.001")  # type: ignore[union-attr]


def test_receipt_item_aliases_are_comparable_each_units() -> None:
    unit, price = normalized(
        quantity=Decimal("2"),
        unit="items",
        line_total_amount=Decimal("2.98"),
    )

    assert unit == "each"
    assert price == Decimal("1.490000")


def test_measured_produce_price_is_comparable_per_kilogram() -> None:
    unit, price = normalized(
        measured_value=Decimal("2"),
        measured_unit="lb",
        line_total_amount=Decimal("5.98"),
    )

    assert unit == "kg"
    assert price == Decimal("6.591822")


def test_printed_price_basis_takes_precedence() -> None:
    unit, price = normalized(
        measured_value=Decimal("0.9"),
        measured_unit="kg",
        unit_price_amount=Decimal("2.99"),
        unit_price_basis_value=Decimal("1"),
        unit_price_basis_unit="lb",
        line_total_amount=Decimal("5.50"),
    )

    assert unit == "kg"
    assert price == Decimal("6.591822")


def test_package_count_and_size_are_combined() -> None:
    unit, price = normalized(
        quantity=Decimal("2"),
        package_value=Decimal("500"),
        package_unit="g",
        line_total_amount=Decimal("8"),
    )

    assert unit == "kg"
    assert price == Decimal("8.000000")


def test_discount_is_removed_from_subtotal_for_comparable_price() -> None:
    unit, price = normalized(
        quantity=Decimal("2"),
        unit="each",
        line_subtotal_amount=Decimal("10"),
        line_discount_amount=Decimal("2"),
        line_total_amount=Decimal("9.04"),
        line_tax_amount=Decimal("1.04"),
    )

    assert unit == "each"
    assert price == Decimal("4.000000")


def test_unknown_or_incompatible_units_are_not_compared() -> None:
    assert normalized(
        measured_value=Decimal("2"),
        measured_unit="bunch",
        line_total_amount=Decimal("4"),
    ) == (None, None)


def test_bare_quantity_with_no_unit_is_flagged_as_estimated() -> None:
    # The eggs/avocados bug: "1" of something with no unit at all can't be told apart
    # from a multi-count pack whose package_value/package_unit was never captured.
    result = derive(quantity=Decimal("1"), line_total_amount=Decimal("10.49"))

    assert result.normalized_unit == "each"
    assert result.is_estimated is True


def test_package_value_and_size_grounded_each_is_not_estimated() -> None:
    result = derive(
        quantity=Decimal("1"),
        package_value=Decimal("18"),
        package_unit="count",
        line_total_amount=Decimal("10.49"),
    )

    assert result.normalized_unit == "each"
    assert result.is_estimated is False


def test_quantity_with_an_explicit_unit_is_not_estimated() -> None:
    result = derive(quantity=Decimal("2"), unit="lb", line_total_amount=Decimal("5.98"))

    assert result.is_estimated is False


def test_measured_value_grounded_price_is_not_estimated() -> None:
    result = derive(
        measured_value=Decimal("2"),
        measured_unit="lb",
        line_total_amount=Decimal("5.98"),
    )

    assert result.is_estimated is False


def test_printed_basis_price_is_not_estimated() -> None:
    result = derive(
        measured_value=Decimal("0.9"),
        measured_unit="kg",
        unit_price_amount=Decimal("2.99"),
        unit_price_basis_value=Decimal("1"),
        unit_price_basis_unit="lb",
        line_total_amount=Decimal("5.50"),
    )

    assert result.is_estimated is False
