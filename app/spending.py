from collections.abc import Iterable, Mapping
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID

from app.errors import ConflictError, NotFoundError
from app.plugin_models import (
    CoverageDeclaration,
    CoverageInput,
    DashboardWindow,
    SpendingComparison,
    SpendingReview,
    SpendingReviewInput,
    SpendingTransaction,
)

COMPARISON_LABELS = {
    "coverage_unknown": "Tracking coverage is incomplete or undeclared.",
    "unequal_windows": "The calendar windows have different numbers of days.",
    "missing_baseline": "No eligible transactions were recorded in the comparison window.",
    "zero_baseline": "The comparison window has zero net spend.",
    "negative_baseline": "The comparison window has negative net spend.",
    "unreviewed_spend": "Transactions still need spending classification review.",
}


def coverage_for_dates(
    start: date, end: date, coverage: Iterable[CoverageDeclaration],
) -> tuple[int, list[str]]:
    unknown = 0
    bases: set[str] = set()
    declarations = tuple(coverage)
    for offset in range((end - start).days + 1):
        day = start + timedelta(days=offset)
        active = {entry.kind for entry in declarations if entry.start_date <= day <= (entry.end_date or end)}
        if not active or "gap" in active:
            unknown += 1
        bases.update(active)
    return unknown, sorted(bases)


def compare_spending(
    window: DashboardWindow,
    currency: str,
    current: Decimal,
    previous: Decimal,
    current_count: int,
    previous_count: int,
    declarations: Iterable[CoverageDeclaration],
    *,
    unreviewed: int = 0,
) -> SpendingComparison:
    coverage = [entry for entry in declarations if entry.currency == currency]

    current_unknown, current_basis = coverage_for_dates(window.current_start, window.current_end, coverage)
    previous_unknown, previous_basis = coverage_for_dates(window.previous_start, window.previous_end, coverage)
    reasons: list[str] = []
    if current_unknown or previous_unknown:
        reasons.append("coverage_unknown")
    if window.current_end - window.current_start != window.previous_end - window.previous_start:
        reasons.append("unequal_windows")
    if previous_count == 0:
        reasons.append("missing_baseline")
    elif previous == 0:
        reasons.append("zero_baseline")
    elif previous < 0:
        reasons.append("negative_baseline")
    if unreviewed:
        reasons.append("unreviewed_spend")
    percent = None
    if not reasons:
        percent = ((current - previous) / previous * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return SpendingComparison(
        currency=currency,
        window=window,
        current_amount=current,
        previous_amount=previous,
        current_count=current_count,
        previous_count=previous_count,
        current_unknown_days=current_unknown,
        previous_unknown_days=previous_unknown,
        current_basis=current_basis,
        previous_basis=previous_basis,
        reasons=reasons,
        label=" ".join(COMPARISON_LABELS[reason] for reason in reasons) if reasons else "Owner-declared coverage.",
        delta_percent=percent,
    )


SPENDING_REVIEW_JOIN = """
    left join lateral (
        select r.classification, r.id
        from spending_classification_reviews r
        where r.user_id = t.user_id and r.transaction_id = t.id and r.transaction_revision = t.updated_at
        order by r.recorded_at desc, r.id desc
        limit 1
    ) spending_review on true
"""


class SpendingRepository:
    def __init__(self, conn: Any, user_id: UUID) -> None:
        self.conn = conn
        self.user_id = user_id

    def declarations(self, start: date | None = None, end: date | None = None) -> list[CoverageDeclaration]:
        rows = self.conn.execute(
            """/* spending:coverage */
            select id, currency, start_date, end_date, kind, reason, recorded_at
            from spending_coverage_declarations
            where user_id = %(user)s
              and (%(start)s::date is null or end_date is null or end_date >= %(start)s::date)
              and (%(end)s::date is null or start_date <= %(end)s::date)
            order by start_date, recorded_at, id
            """,
            {"user": self.user_id, "start": start, "end": end},
        ).fetchall()
        return [CoverageDeclaration.model_validate(row) for row in rows]

    def declare(self, request: CoverageInput) -> CoverageDeclaration:
        row = self.conn.execute(
            """insert into spending_coverage_declarations (user_id, currency, start_date, end_date, kind, reason)
            values (%(user)s, %(currency)s, %(start_date)s, %(end_date)s, %(kind)s, %(reason)s)
            returning id, currency, start_date, end_date, kind, reason, recorded_at
            """,
            {**request.model_dump(), "user": self.user_id},
        ).fetchone()
        return CoverageDeclaration.model_validate(row)

    def remove_declaration(self, declaration_id: UUID) -> None:
        row = self.conn.execute(
            """delete from spending_coverage_declarations where user_id = %s and id = %s returning id""",
            (self.user_id, declaration_id),
        ).fetchone()
        if row is None:
            raise NotFoundError("Coverage declaration not found")

    def transactions(
        self, start: date, end: date, currency: str, limit: int, offset: int,
    ) -> list[SpendingTransaction]:
        rows = self.conn.execute(
            f"""select t.id, t.transaction_date, t.updated_at as revision,
                coalesce(t.merchant_name_normalized, t.merchant_name_raw) as merchant,
                t.currency, t.transaction_type,
                case when t.transaction_type = 'refund' then -abs(t.total_amount) else t.total_amount end as amount,
                coalesce(spending_review.classification, 'unreviewed') as classification,
                spending_review.id as review_id,
                array(
                    select distinct value.stable_key
                    from transaction_items i
                    join transaction_item_facets item_facet
                      on item_facet.item_id = i.id and item_facet.user_id = i.user_id
                    join taxonomy_facet_values value on value.id = item_facet.facet_value_id
                    join taxonomy_facets facet on facet.id = value.facet_id
                    where i.user_id = t.user_id and i.transaction_id = t.id and facet.stable_key = 'recurrence'
                    order by value.stable_key
                ) as recurrence
            from transactions t
            {SPENDING_REVIEW_JOIN}
            where t.user_id = %(user)s and t.status = 'confirmed'
                and t.transaction_type in ('expense', 'refund') and t.currency = %(currency)s
                and t.transaction_date between %(start)s and %(end)s
            order by t.transaction_date desc, t.id desc limit %(limit)s offset %(offset)s
            """,
            {"user": self.user_id, "start": start, "end": end, "currency": currency, "limit": limit, "offset": offset},
        ).fetchall()
        return [SpendingTransaction.model_validate(row) for row in rows]

    def classify(self, request: SpendingReviewInput) -> SpendingReview:
        transaction = self.conn.execute(
            """select updated_at from transactions where user_id = %s and id = %s
            and status = 'confirmed' and transaction_type in ('expense', 'refund') for update""",
            (self.user_id, request.transaction_id),
        ).fetchone()
        if transaction is None:
            raise NotFoundError("Confirmed spending transaction not found")
        if transaction["updated_at"] != request.expected_revision:
            raise ConflictError("Transaction changed since review")
        params: Mapping[str, Any] = {**request.model_dump(), "user": self.user_id}
        latest = self.conn.execute(
            """select id from spending_classification_reviews
               where user_id = %(user)s and transaction_id = %(transaction_id)s
                 and transaction_revision = %(expected_revision)s
               order by recorded_at desc, id desc limit 1""",
            params,
        ).fetchone()
        if (latest["id"] if latest else None) != request.expected_review_id:
            raise ConflictError("Spending classification changed since review")
        row = self.conn.execute(
            """insert into spending_classification_reviews
                (user_id, transaction_id, transaction_revision, classification, reason)
               values (%(user)s, %(transaction_id)s, %(expected_revision)s, %(classification)s, %(reason)s)
               returning id, transaction_id, transaction_revision, classification, reason, recorded_at
            """,
            params,
        ).fetchone()
        return SpendingReview.model_validate(row)
