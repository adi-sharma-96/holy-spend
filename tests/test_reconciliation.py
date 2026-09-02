from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch
from uuid import UUID
from zoneinfo import ZoneInfo

from app.config import Settings
from app.models import (
    AdjustmentType,
    SourceType,
    TaxonomyClassificationSource,
    TaxonomyReviewStatus,
    TransactionAdjustment,
    TransactionClassificationMode,
    TransactionDetail,
    TransactionItem,
    TransactionItemRole,
    TransactionStatus,
    TransactionType,
    ValidationSeverity,
)
from app.reconciliation import ReconciliationService


def transaction(total: str, subtotal: str = "10.00") -> TransactionDetail:
    return TransactionDetail(
        id=UUID("11111111-1111-1111-1111-111111111111"),
        transaction_type=TransactionType.EXPENSE,
        source_type=SourceType.MANUAL,
        classification_mode=TransactionClassificationMode.WHOLE_BILL,
        status=TransactionStatus.DRAFT,
        transaction_date=date.today(),
        merchant_name_raw=None,
        merchant_name_normalized=None,
        currency="CAD",
        subtotal_amount=Decimal(subtotal),
        tax_amount=Decimal("0.00"),
        fee_amount=Decimal("0.00"),
        discount_amount=Decimal("0.00"),
        tip_amount=None,
        deposit_amount=None,
        rounding_amount=None,
        total_amount=Decimal(total),
        reconciliation_delta_amount=None,
        confirmed_at=None,
        items=[
            _item(
                "99999999-9999-4999-8999-999999999999",
                "Whole bill",
                subtotal,
                subtotal,
                taxonomy_node_key="unclassified.user_approved_other",
                item_role=TransactionItemRole.WHOLE_BILL,
            )
        ],
        adjustments=[],
        validation_issues=[],
    )


def test_manual_transaction_requires_a_semantic_whole_bill_line() -> None:
    tx = transaction("10.00")
    tx.items = []
    delta, issues = ReconciliationService(Settings()).validate(tx)

    assert delta == Decimal("0.00")
    assert {candidate.code for candidate in issues} >= {
        "missing_classification_line",
        "invalid_whole_bill_structure",
    }


def test_reconciliation_accepted_warning_and_blocking_thresholds() -> None:
    service = ReconciliationService(Settings())

    accepted_delta, accepted = service.validate(transaction("10.02"))
    warning_delta, warning = service.validate(transaction("10.03"))
    blocking_delta, blocking = service.validate(transaction("11.01"))

    assert accepted_delta == Decimal("0.02")
    assert accepted == []
    assert warning_delta == Decimal("0.03")
    assert warning[0].severity == ValidationSeverity.WARNING
    assert blocking_delta == Decimal("1.01")
    assert blocking[0].severity == ValidationSeverity.BLOCKING


def test_printed_summary_discount_is_not_double_counted_as_adjustment() -> None:
    tx = transaction("13.42", "14.00")
    tx.discount_amount = Decimal("0.58")
    tx.adjustments.append(
        TransactionAdjustment(
            id=UUID("44444444-4444-4444-4444-444444444444"),
            item_id=None,
            type=AdjustmentType.DISCOUNT,
            amount=Decimal("0.58"),
            description="2 for $4 mango promotion",
        )
    )
    tx.classification_mode = TransactionClassificationMode.ITEMIZED
    tx.items = [
        _item("55555555-5555-5555-5555-555555555551", "Idli chutney powder", "3.79", "3.79"),
        _item("55555555-5555-5555-5555-555555555552", "Bananas", "2.84", "2.84"),
        _item(
            "55555555-5555-5555-5555-555555555553",
            "Mangoes",
            "4.58",
            "4.00",
            discount="0.58",
        ),
        _item("55555555-5555-5555-5555-555555555554", "Sabudana", "2.79", "2.79"),
    ]

    delta, issues = ReconciliationService(Settings()).validate(tx)

    assert delta == Decimal("0.00")
    assert issues == []


def test_adjustment_is_fallback_when_summary_component_is_missing() -> None:
    tx = transaction("9.42", "10.00")
    tx.discount_amount = None
    tx.adjustments.append(
        TransactionAdjustment(
            id=UUID("66666666-6666-6666-6666-666666666666"),
            item_id=None,
            type=AdjustmentType.COUPON,
            amount=Decimal("0.58"),
            description="Coupon",
        )
    )

    delta, issues = ReconciliationService(Settings()).validate(tx)

    assert delta == Decimal("0.00")
    assert issues == []


def test_restaurant_summary_supports_tax_fee_and_tip_without_items() -> None:
    tx = transaction("29.38", "20.00")
    tx.tax_amount = Decimal("2.60")
    tx.fee_amount = Decimal("1.78")
    tx.tip_amount = Decimal("5.00")

    delta, issues = ReconciliationService(Settings()).validate(tx)

    assert delta == Decimal("0.00")
    assert issues == []


def test_grocery_fee_and_offer_detail_reconciles_to_authoritative_summary() -> None:
    tx = transaction("47.25", "50.00")
    tx.tax_amount = Decimal("2.00")
    tx.fee_amount = Decimal("0.25")
    tx.discount_amount = Decimal("5.00")
    tx.adjustments = [
        _adjustment("10000000-0000-0000-0000-000000000001", AdjustmentType.TAX, "2.00"),
        _adjustment(
            "10000000-0000-0000-0000-000000000002",
            AdjustmentType.FEE,
            "0.25",
            subtype="bag_fee",
        ),
        _adjustment(
            "10000000-0000-0000-0000-000000000003",
            AdjustmentType.DISCOUNT,
            "5.00",
            subtype="offer",
        ),
    ]

    delta, issues = ReconciliationService(Settings()).validate(tx)

    assert delta == Decimal("0.00")
    assert issues == []


def test_food_delivery_multiple_fees_discounts_and_tip_reconcile() -> None:
    tx = transaction("42.33", "35.00")
    tx.tax_amount = Decimal("5.33")
    tx.fee_amount = Decimal("6.00")
    tx.discount_amount = Decimal("10.00")
    tx.tip_amount = Decimal("6.00")
    tx.adjustments = [
        _adjustment(
            "20000000-0000-0000-0000-000000000001",
            AdjustmentType.FEE,
            "2.00",
            subtype="delivery_fee",
        ),
        _adjustment(
            "20000000-0000-0000-0000-000000000002",
            AdjustmentType.FEE,
            "4.00",
            subtype="service_fee",
        ),
        _adjustment("20000000-0000-0000-0000-000000000003", AdjustmentType.TAX, "5.33"),
        _adjustment("20000000-0000-0000-0000-000000000004", AdjustmentType.TIP, "6.00"),
        _adjustment(
            "20000000-0000-0000-0000-000000000005",
            AdjustmentType.DISCOUNT,
            "3.00",
            subtype="membership_benefit",
        ),
        _adjustment(
            "20000000-0000-0000-0000-000000000006",
            AdjustmentType.DISCOUNT,
            "7.00",
            subtype="offer",
        ),
    ]

    delta, issues = ReconciliationService(Settings()).validate(tx)

    assert delta == Decimal("0.00")
    assert issues == []


def test_informational_membership_saving_is_excluded_from_fallback_arithmetic() -> None:
    tx = transaction("10.00", "10.00")
    tx.discount_amount = None
    tx.adjustments = [
        _adjustment(
            "30000000-0000-0000-0000-000000000001",
            AdjustmentType.DISCOUNT,
            "3.99",
            subtype="membership_benefit",
            affects_total=False,
        )
    ]

    delta, issues = ReconciliationService(Settings()).validate(tx)

    assert delta == Decimal("0.00")
    assert issues == []


def test_signed_rounding_fallback_and_refund_behavior_remain_supported() -> None:
    tx = transaction("9.99", "10.00")
    tx.rounding_amount = None
    tx.adjustments = [
        _adjustment(
            "40000000-0000-0000-0000-000000000001",
            AdjustmentType.ROUNDING,
            "-0.01",
        )
    ]
    delta, issues = ReconciliationService(Settings()).validate(tx)
    assert delta == Decimal("0.00")
    assert issues == []

    refund = transaction("-10.00", "-10.00")
    refund.transaction_type = TransactionType.REFUND
    refund.total_amount = Decimal("-10.00")
    refund_delta, refund_issues = ReconciliationService(Settings()).validate(refund)
    assert refund_delta == Decimal("0.00")
    assert not any(issue.code == "negative_summary_amount" for issue in refund_issues)


def test_item_level_reconciliation_detects_inconsistent_net_lines() -> None:
    tx = transaction("13.42", "14.00")
    tx.discount_amount = Decimal("0.58")
    tx.classification_mode = TransactionClassificationMode.ITEMIZED
    tx.items = [
        _item(
            "77777777-7777-7777-7777-777777777777",
            "Mangoes",
            "14.00",
            "14.00",
            discount="0.58",
        )
    ]

    delta, issues = ReconciliationService(Settings()).validate(tx)

    assert delta == Decimal("0.00")
    assert any(candidate.code == "item_reconciliation_warning" for candidate in issues)


def test_quantity_must_be_positive_when_present() -> None:
    tx = transaction("1.00", "1.00")
    tx.classification_mode = TransactionClassificationMode.ITEMIZED
    tx.items = [
        TransactionItem(
            id=UUID("22222222-2222-2222-2222-222222222222"),
            raw_name="Apple",
            interpreted_name="Apple",
            normalized_name="apple",
            category_id=UUID("33333333-3333-3333-3333-333333333333"),
            category_slug="grocery.food.produce.fruit.apples",
            theme_slugs=[],
            quantity=Decimal("0"),
            unit=None,
            unit_price_amount=None,
            line_subtotal_amount=None,
            line_discount_amount=None,
            line_tax_amount=None,
            line_fee_amount=None,
            line_total_amount=Decimal("1.00"),
            confidence=None,
        )
    ]

    _, issues = ReconciliationService(Settings()).validate(tx)

    assert any(issue.code == "non_positive_quantity" for issue in issues)


def test_unsupported_currency_and_future_date_are_blocking() -> None:
    tx = transaction("10.00")
    tx.currency = "ZZZ"
    tx.transaction_date = date.today() + timedelta(days=2)

    _, issues = ReconciliationService(Settings()).validate(tx)

    assert {issue.code for issue in issues} >= {"unsupported_currency", "future_date"}
    assert all(issue.severity == ValidationSeverity.BLOCKING for issue in issues)


def test_future_date_check_follows_the_configured_local_timezone() -> None:
    # 2:00 AM UTC on Aug 1 is still 10:00 PM Jul 31 in US Eastern, so "today"
    # there is Jul 31 and the one-day grace window only reaches Aug 1. A
    # naive server-UTC clock would treat Aug 1 as "today" and wrongly let an
    # Aug 2 date slip through inside its own one-day grace window.
    fixed_utc = datetime(2026, 8, 1, 2, 0, tzinfo=ZoneInfo("UTC"))
    settings = Settings(local_timezone="America/New_York")
    tx = transaction("10.00")
    tx.transaction_date = date(2026, 8, 2)

    def fake_now(tz: ZoneInfo) -> datetime:
        return fixed_utc.astimezone(tz)

    with patch("app.clock.datetime") as mock_datetime:
        mock_datetime.now.side_effect = fake_now
        _, issues = ReconciliationService(settings).validate(tx)

    assert any(issue.code == "future_date" for issue in issues)


def test_same_local_day_is_accepted_even_after_utc_has_rolled_to_tomorrow() -> None:
    fixed_utc = datetime(2026, 8, 1, 2, 0, tzinfo=ZoneInfo("UTC"))
    settings = Settings(local_timezone="America/New_York")
    tx = transaction("10.00")
    tx.transaction_date = date(2026, 7, 31)

    def fake_now(tz: ZoneInfo) -> datetime:
        return fixed_utc.astimezone(tz)

    with patch("app.clock.datetime") as mock_datetime:
        mock_datetime.now.side_effect = fake_now
        _, issues = ReconciliationService(settings).validate(tx)

    assert not any(issue.code == "future_date" for issue in issues)


def _item(
    item_id: str,
    name: str,
    subtotal: str,
    total: str,
    *,
    discount: str | None = None,
    taxonomy_node_key: str = "food_dining.groceries.pantry.staples.miscellaneous.other_staples",
    item_role: TransactionItemRole = TransactionItemRole.PURCHASE,
) -> TransactionItem:
    return TransactionItem(
        id=UUID(item_id),
        raw_name=name,
        interpreted_name=name,
        normalized_name=name.lower(),
        category_id=UUID("33333333-3333-3333-3333-333333333333"),
        category_slug="grocery.food.other",
        taxonomy_node_key=taxonomy_node_key,
        taxonomy_node_name=name,
        taxonomy_version="2.0.0",
        item_role=item_role,
        classification_source=TaxonomyClassificationSource.USER,
        classification_review_status=TaxonomyReviewStatus.REVIEWED,
        theme_slugs=[],
        quantity=Decimal("1"),
        unit=None,
        unit_price_amount=None,
        line_subtotal_amount=Decimal(subtotal),
        line_discount_amount=Decimal(discount) if discount is not None else None,
        line_tax_amount=None,
        line_fee_amount=None,
        line_total_amount=Decimal(total),
        confidence=None,
    )


def _adjustment(
    adjustment_id: str,
    adjustment_type: AdjustmentType,
    amount: str,
    *,
    subtype: str | None = None,
    affects_total: bool = True,
) -> TransactionAdjustment:
    return TransactionAdjustment(
        id=UUID(adjustment_id),
        item_id=None,
        type=adjustment_type,
        subtype=subtype,
        amount=Decimal(amount),
        description=None,
        raw_label=None,
        affects_total=affects_total,
        metadata={},
    )
