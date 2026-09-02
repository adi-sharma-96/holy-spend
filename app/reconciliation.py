from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from app.clock import local_today
from app.config import Settings
from app.models import (
    AdjustmentType,
    TaxonomyReviewStatus,
    TransactionClassificationMode,
    TransactionDetail,
    TransactionType,
    ValidationIssue,
    ValidationSeverity,
)

ZERO = Decimal("0.00")


def money(value: Decimal | None) -> Decimal:
    return value if value is not None else ZERO


def issue(
    severity: ValidationSeverity,
    code: str,
    message: str,
    metadata: dict[str, Any] | None = None,
) -> ValidationIssue:
    return ValidationIssue(
        severity=severity,
        code=code,
        message=message,
        metadata=metadata or {},
    )


def adjustment_total(
    transaction: TransactionDetail,
    adjustment_types: set[AdjustmentType],
) -> Decimal:
    return sum(
        (
            abs(adjustment.amount)
            for adjustment in transaction.adjustments
            if adjustment.type in adjustment_types and adjustment.affects_total
        ),
        ZERO,
    )


def summary_component(
    explicit: Decimal | None,
    transaction: TransactionDetail,
    adjustment_types: set[AdjustmentType],
) -> Decimal:
    # Printed summary fields are authoritative. Adjustments are a fallback breakdown,
    # not an additional amount to apply a second time.
    return explicit if explicit is not None else adjustment_total(transaction, adjustment_types)


def item_gross_total(transaction: TransactionDetail) -> Decimal:
    total = ZERO
    for item in transaction.items:
        if item.line_subtotal_amount is not None:
            total += item.line_subtotal_amount
            continue
        total += (
            item.line_total_amount
            + money(item.line_discount_amount)
            - money(item.line_tax_amount)
            - money(item.line_fee_amount)
        )
    return total


class ReconciliationService:
    def __init__(self, settings: Settings) -> None:
        self.accepted = Decimal(settings.reconciliation_accepted_cents) / Decimal(100)
        self.warning = Decimal(settings.reconciliation_warning_cents) / Decimal(100)
        self.supported_currencies = {currency.upper() for currency in settings.supported_currencies}
        self.settings = settings

    def validate(self, transaction: TransactionDetail) -> tuple[Decimal | None, list[ValidationIssue]]:
        issues: list[ValidationIssue] = []

        if transaction.currency.upper() not in self.supported_currencies:
            issues.append(
                issue(
                    ValidationSeverity.BLOCKING,
                    "unsupported_currency",
                    f"Currency {transaction.currency} is not supported.",
                )
            )

        if transaction.transaction_date > local_today(self.settings) + timedelta(days=1):
            issues.append(
                issue(
                    ValidationSeverity.BLOCKING,
                    "future_date",
                    "Transaction date is implausibly far in the future.",
                )
            )
        elif transaction.transaction_date < date(1990, 1, 1):
            issues.append(
                issue(
                    ValidationSeverity.WARNING,
                    "old_date",
                    "Transaction date is unusually old.",
                )
            )

        if not transaction.items:
            issues.append(
                issue(
                    ValidationSeverity.BLOCKING,
                    "missing_classification_line",
                    "Add at least one classified product, service, or whole-bill line before confirmation.",
                )
            )
        if (
            transaction.classification_mode == TransactionClassificationMode.WHOLE_BILL
            and len(transaction.items) != 1
        ):
            issues.append(
                issue(
                    ValidationSeverity.BLOCKING,
                    "invalid_whole_bill_structure",
                    "A whole-bill transaction must contain exactly one semantic line.",
                )
            )

        if transaction.transaction_type != TransactionType.REFUND:
            summary_amounts = {
                "subtotal_amount": transaction.subtotal_amount,
                "tax_amount": transaction.tax_amount,
                "fee_amount": transaction.fee_amount,
                "discount_amount": transaction.discount_amount,
                "tip_amount": transaction.tip_amount,
                "deposit_amount": transaction.deposit_amount,
                "total_amount": transaction.total_amount,
            }
            for field_name, value in summary_amounts.items():
                if value is not None and value < 0:
                    issues.append(
                        issue(
                            ValidationSeverity.BLOCKING,
                            "negative_summary_amount",
                            f"{field_name} must be a non-negative magnitude for non-refund transactions.",
                            {"field": field_name},
                        )
                    )

        for item in transaction.items:
            if item.taxonomy_node_key == "unclassified.needs_review":
                issues.append(
                    issue(
                        ValidationSeverity.BLOCKING,
                        "taxonomy_needs_review",
                        "Choose a specific taxonomy leaf before confirmation.",
                        {"item_id": str(item.id)},
                    )
                )
            elif item.classification_review_status == TaxonomyReviewStatus.NEEDS_REVIEW:
                issues.append(
                    issue(
                        ValidationSeverity.BLOCKING,
                        "taxonomy_review_required",
                        "Review this item's taxonomy classification before confirmation.",
                        {
                            "item_id": str(item.id),
                            "taxonomy_node_key": item.taxonomy_node_key,
                        },
                    )
                )
            if item.quantity is not None and item.quantity <= 0:
                issues.append(
                    issue(
                        ValidationSeverity.BLOCKING,
                        "non_positive_quantity",
                        "Item quantity must be positive when present.",
                        {"item_id": str(item.id)},
                    )
                )

            amount_fields = {
                "unit_price_amount": item.unit_price_amount,
                "line_subtotal_amount": item.line_subtotal_amount,
                "line_discount_amount": item.line_discount_amount,
                "line_tax_amount": item.line_tax_amount,
                "line_fee_amount": item.line_fee_amount,
                "line_total_amount": item.line_total_amount,
            }
            if transaction.transaction_type != TransactionType.REFUND:
                for field_name, value in amount_fields.items():
                    if value is not None and value < 0:
                        issues.append(
                            issue(
                                ValidationSeverity.BLOCKING,
                                "negative_item_amount",
                                f"{field_name} must be non-negative for non-refund transactions.",
                                {"item_id": str(item.id), "field": field_name},
                            )
                        )

        discount = summary_component(
            transaction.discount_amount,
            transaction,
            {AdjustmentType.COUPON, AdjustmentType.DISCOUNT, AdjustmentType.REFUND},
        )
        tax = summary_component(transaction.tax_amount, transaction, {AdjustmentType.TAX})
        fee = summary_component(transaction.fee_amount, transaction, {AdjustmentType.FEE})
        tip = summary_component(transaction.tip_amount, transaction, {AdjustmentType.TIP})
        deposit = summary_component(transaction.deposit_amount, transaction, {AdjustmentType.DEPOSIT})
        rounding = (
            transaction.rounding_amount
            if transaction.rounding_amount is not None
            else sum(
                (
                    adjustment.amount
                    for adjustment in transaction.adjustments
                    if adjustment.type == AdjustmentType.ROUNDING and adjustment.affects_total
                ),
                ZERO,
            )
        )

        subtotal_base = transaction.subtotal_amount
        if subtotal_base is None and transaction.items:
            subtotal_base = item_gross_total(transaction)

        expected_total: Decimal | None = None
        if subtotal_base is not None:
            expected_total = (
                money(subtotal_base)
                + tax
                + fee
                + tip
                + deposit
                + rounding
                - discount
            )

        delta: Decimal | None = None
        if expected_total is not None:
            delta = (transaction.total_amount - expected_total).quantize(Decimal("0.01"))
            self._append_reconciliation_issue(issues, "total", delta, expected_total)

        if transaction.items and transaction.subtotal_amount is not None:
            allocated_discount = sum((money(item.line_discount_amount) for item in transaction.items), ZERO)
            allocated_tax = sum((money(item.line_tax_amount) for item in transaction.items), ZERO)
            allocated_fee = sum((money(item.line_fee_amount) for item in transaction.items), ZERO)
            item_expected_total = (
                sum((item.line_total_amount for item in transaction.items), ZERO)
                + (tax - allocated_tax)
                + (fee - allocated_fee)
                + tip
                + deposit
                + rounding
                - (discount - allocated_discount)
            )
            item_delta = (transaction.total_amount - item_expected_total).quantize(Decimal("0.01"))
            self._append_reconciliation_issue(issues, "item", item_delta, item_expected_total)

        return delta, issues

    def _append_reconciliation_issue(
        self,
        issues: list[ValidationIssue],
        basis: str,
        delta: Decimal,
        expected_total: Decimal,
    ) -> None:
        abs_delta = abs(delta)
        metadata = {"delta": str(delta), "expected_total": str(expected_total), "basis": basis}
        if abs_delta > self.warning:
            issues.append(
                issue(
                    ValidationSeverity.BLOCKING,
                    f"{basis}_reconciliation_blocking",
                    f"Receipt total differs from the {basis} calculation by more than the blocking threshold.",
                    metadata,
                )
            )

        elif abs_delta > self.accepted:
            issues.append(
                issue(
                    ValidationSeverity.WARNING,
                    f"{basis}_reconciliation_warning",
                    f"Receipt total differs from the {basis} calculation by more than the accepted threshold.",
                    metadata,
                )
            )


def has_blocking_issues(issues: list[ValidationIssue]) -> bool:
    return any(issue.severity == ValidationSeverity.BLOCKING for issue in issues)
