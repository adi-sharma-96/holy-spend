from decimal import Decimal

from app.models import AdjustmentType
from app.plugin_models import ExpenseDraftAdjustment, ExpenseDraftInput

ZERO = Decimal("0.00")
CENT = Decimal("0.01")
DISCOUNT_TYPES = {AdjustmentType.COUPON, AdjustmentType.DISCOUNT, AdjustmentType.REFUND}


def _money(value: Decimal | None) -> Decimal:
    return value if value is not None else ZERO


def normalize_receipt_savings(draft: ExpenseDraftInput) -> ExpenseDraftInput:
    """Make printed savings informational when the charged arithmetic already reconciles.

    Receipt line totals are interpreted as amounts actually charged. If subtotal plus
    charged components already equals the printed total, subtracting a separate savings
    amount would double count it.
    """

    if draft.subtotal_amount is None:
        return draft

    total_without_discount = (
        draft.subtotal_amount
        + _money(draft.tax_amount)
        + _money(draft.fee_amount)
        + _money(draft.tip_amount)
        + _money(draft.deposit_amount)
        + _money(draft.rounding_amount)
    )
    if abs(total_without_discount - draft.total_amount) > CENT:
        return _deduplicate_explicit_discount(draft)

    reported_savings = draft.discount_amount
    normalized_adjustments: list[ExpenseDraftAdjustment] = []
    informational_amount = ZERO
    for adjustment in draft.adjustments:
        if adjustment.type in DISCOUNT_TYPES and adjustment.affects_total:
            informational_amount += abs(adjustment.amount)
            metadata = {
                **adjustment.metadata,
                "normalization": "informational_savings",
                "reason": "printed total already reconciles without subtracting savings",
            }
            normalized_adjustments.append(
                adjustment.model_copy(update={"affects_total": False, "metadata": metadata})
            )
        else:
            normalized_adjustments.append(adjustment)

    if reported_savings is not None and reported_savings > ZERO and informational_amount == ZERO:
        normalized_adjustments.append(
            ExpenseDraftAdjustment(
                type=AdjustmentType.DISCOUNT,
                amount=reported_savings,
                description="Informational savings",
                raw_label="Total Savings",
                affects_total=False,
                metadata={
                    "normalization": "informational_savings",
                    "reason": "printed total already reconciles without subtracting savings",
                    "source": "discount_amount",
                },
            )
        )

    return draft.model_copy(
        update={
            "discount_amount": None,
            "adjustments": normalized_adjustments,
        }
    )


def _deduplicate_explicit_discount(draft: ExpenseDraftInput) -> ExpenseDraftInput:
    """Keep the summary discount authoritative and prevent an equivalent adjustment."""

    if draft.discount_amount is None:
        return draft
    normalized: list[ExpenseDraftAdjustment] = []
    for adjustment in draft.adjustments:
        equivalent = (
            adjustment.type in DISCOUNT_TYPES
            and adjustment.affects_total
            and abs(abs(adjustment.amount) - draft.discount_amount) <= CENT
        )
        if equivalent:
            normalized.append(
                adjustment.model_copy(
                    update={
                        "affects_total": False,
                        "metadata": {
                            **adjustment.metadata,
                            "normalization": "summary_discount_authoritative",
                        },
                    }
                )
            )
        else:
            normalized.append(adjustment)
    return draft.model_copy(update={"adjustments": normalized})
