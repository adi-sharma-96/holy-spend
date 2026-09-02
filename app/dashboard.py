from collections import defaultdict
from collections.abc import Callable
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID

from app.models import TransactionSummary
from app.personal_basket import exact_basket_identity
from app.plugin_models import (
    BasketProduct,
    CategorySpend,
    CurrencySpend,
    DailySpend,
    DashboardInsight,
    DashboardPeriod,
    DashboardWindow,
    ExpenseDashboard,
    ExpenseDashboardRequest,
    ItemPriceHistory,
    ItemPriceHistoryRequest,
    ItemPricePoint,
    ItemPriceSeries,
    KnownItemMatch,
    MerchantBreakdownRequest,
    MerchantBreakdownResponse,
    MerchantSpend,
    PersonalBasketIndex,
    PersonalBasketRequest,
    PriceChange,
    SearchKnownItemsRequest,
    SearchKnownItemsResponse,
    SpendTrendPoint,
)
from app.price_watch import TRACKABLE_PREFIXES, canonical_price_watch_identity

PERCENT_QUANTUM = Decimal("0.1")
BASKET_WINDOW_DAYS = 180
BASKET_MAX_PRODUCT_WEIGHT_SHARE = Decimal("0.35")
BASKET_HIGH_CONFIDENCE_MIN_PRODUCTS = 8
BASKET_HIGH_CONFIDENCE_MIN_COVERAGE = Decimal("50")
BASKET_TREND_SAMPLE_SIZE = 3


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value or 0))


def _quantity_label(row: Any) -> str | None:
    def display(value: Any) -> str:
        number = _decimal(value)
        return format(number.normalize(), "f")

    measured_value = row.get("measured_value")
    measured_unit = row.get("measured_unit")
    if measured_value and measured_unit:
        return f"{display(measured_value)} {measured_unit}"

    package_value = row.get("package_value")
    package_unit = row.get("package_unit")
    quantity = row.get("quantity")
    if package_value and package_unit:
        if quantity and _decimal(quantity) > 1:
            return f"{display(quantity)} × {display(package_value)} {package_unit}"
        return f"{display(package_value)} {package_unit}"

    unit = row.get("unit")
    if quantity and unit and str(unit).lower() not in {"each", "ea", "item", "unit"}:
        return f"{display(quantity)} {unit}"
    return None


def _percent_delta(current: Decimal, previous: Decimal) -> Decimal | None:
    if previous == 0:
        return None
    return (((current - previous) / abs(previous)) * Decimal("100")).quantize(
        PERCENT_QUANTUM,
        rounding=ROUND_HALF_UP,
    )


def dashboard_window(period: DashboardPeriod, today: date) -> DashboardWindow:
    if period == DashboardPeriod.MONTH:
        current_start = today.replace(day=1)
        previous_month_end = current_start - timedelta(days=1)
        previous_start = previous_month_end.replace(day=1)
        elapsed_days = (today - current_start).days
        previous_end = min(
            previous_start + timedelta(days=elapsed_days),
            previous_month_end,
        )
        label = today.strftime("%B")
    elif period == DashboardPeriod.THIRTY_DAYS:
        current_start = today - timedelta(days=29)
        previous_end = current_start - timedelta(days=1)
        previous_start = previous_end - timedelta(days=29)
        label = "Last 30 days"
    elif period == DashboardPeriod.NINETY_DAYS:
        current_start = today - timedelta(days=89)
        previous_end = current_start - timedelta(days=1)
        previous_start = previous_end - timedelta(days=89)
        label = "Last 90 days"
    else:
        current_start = today.replace(month=1, day=1)
        previous_start = current_start.replace(year=current_start.year - 1)
        try:
            previous_end = today.replace(year=today.year - 1)
        except ValueError:
            # February 29 compares through February 28 in a non-leap prior year.
            previous_end = today.replace(year=today.year - 1, day=28)
        label = str(today.year)
    return DashboardWindow(
        label=label,
        current_start=current_start,
        current_end=today,
        previous_start=previous_start,
        previous_end=previous_end,
    )


class DashboardRepository:
    def __init__(
        self,
        conn: Any,
        user_id: UUID,
        *,
        today: Callable[[], date] = date.today,
        fallback_currency: str = "CAD",
    ) -> None:
        self.conn = conn
        self.user_id = user_id
        self.today = today
        self.fallback_currency = fallback_currency

    def get_dashboard(self, request: ExpenseDashboardRequest) -> ExpenseDashboard:
        window = dashboard_window(request.period, self.today())
        params: dict[str, Any] = {
            "user_id": self.user_id,
            "current_start": window.current_start,
            "current_end": window.current_end,
            "previous_start": window.previous_start,
            "previous_end": window.previous_end,
        }
        profile = self.conn.execute(
            """
            /* dashboard:profile */
            select display_name, default_currency
            from profiles
            where id = %(user_id)s
            """,
            {"user_id": self.user_id},
        ).fetchone()

        total_rows = self.conn.execute(
            """
            /* dashboard:totals */
            select t.currency,
                   coalesce(sum(case
                       when t.transaction_date between %(current_start)s and %(current_end)s
                           and t.transaction_type = 'expense' then t.total_amount
                       when t.transaction_date between %(current_start)s and %(current_end)s
                           and t.transaction_type = 'refund' then -abs(t.total_amount)
                       else 0
                   end), 0) as current_amount,
                   coalesce(sum(case
                       when t.transaction_date between %(previous_start)s and %(previous_end)s
                           and t.transaction_type = 'expense' then t.total_amount
                       when t.transaction_date between %(previous_start)s and %(previous_end)s
                           and t.transaction_type = 'refund' then -abs(t.total_amount)
                       else 0
                   end), 0) as previous_amount
            from transactions t
            where t.user_id = %(user_id)s
              and t.status = 'confirmed'
              and t.transaction_date between %(previous_start)s and %(current_end)s
              and t.transaction_type in ('expense', 'refund')
            group by t.currency
            order by t.currency
            """,
            params,
        ).fetchall()
        totals = []
        for row in total_rows:
            current = _decimal(row["current_amount"])
            previous = _decimal(row["previous_amount"])
            totals.append(
                CurrencySpend(
                    currency=row["currency"],
                    current_amount=current,
                    previous_amount=previous,
                    delta_amount=current - previous,
                    delta_percent=_percent_delta(current, previous),
                )
            )

        category_rows = self.conn.execute(
            """
            /* dashboard:categories */
            select reporting_category.stable_key as category_slug,
                   reporting_category.name as category_name,
                   reporting_category.level as taxonomy_level,
                   reporting_version.level_names ->> (reporting_category.level - 1)
                       as taxonomy_level_name,
                   exists (
                       select 1
                       from taxonomy_nodes child
                       where child.version_id = reporting_category.version_id
                         and child.parent_id = reporting_category.id
                   ) as has_children,
                   t.currency,
                   coalesce(sum(case
                       when t.transaction_date between %(current_start)s and %(current_end)s
                           and t.transaction_type = 'expense' then i.line_total_amount
                       when t.transaction_date between %(current_start)s and %(current_end)s
                           and t.transaction_type = 'refund' then -abs(i.line_total_amount)
                       else 0
                   end), 0) as current_amount,
                   coalesce(sum(case
                       when t.transaction_date between %(previous_start)s and %(previous_end)s
                           and t.transaction_type = 'expense' then i.line_total_amount
                       when t.transaction_date between %(previous_start)s and %(previous_end)s
                           and t.transaction_type = 'refund' then -abs(i.line_total_amount)
                       else 0
                   end), 0) as previous_amount
            from transactions t
            join transaction_items i on i.transaction_id = t.id and i.user_id = t.user_id
            join taxonomy_nodes category on category.id = i.taxonomy_node_id
            join taxonomy_node_closure reporting_path
              on reporting_path.version_id = category.version_id
             and reporting_path.descendant_id = category.id
            join taxonomy_nodes reporting_category
              on reporting_category.id = reporting_path.ancestor_id
             and reporting_category.level = least(2, category.level)
            join taxonomy_versions reporting_version
              on reporting_version.id = reporting_category.version_id
            where t.user_id = %(user_id)s
              and t.status = 'confirmed'
              and t.transaction_date between %(previous_start)s and %(current_end)s
              and t.transaction_type in ('expense', 'refund')
              and category.stable_key not like 'unclassified.%%'
            group by reporting_category.id, reporting_category.stable_key,
                     reporting_category.name, reporting_category.level,
                     reporting_category.version_id, reporting_version.level_names,
                     t.currency
            order by t.currency, current_amount desc, reporting_category.name
            """,
            params,
        ).fetchall()
        category_totals: dict[str, Decimal] = defaultdict(Decimal)
        category_previous_totals: dict[str, Decimal] = defaultdict(Decimal)
        for row in category_rows:
            category_totals[row["currency"]] += _decimal(row["current_amount"])
            category_previous_totals[row["currency"]] += _decimal(row["previous_amount"])

        # Category rows only sum item line amounts; a transaction's total also
        # includes tax, fees, tips, deposits, discounts, and rounding, none of
        # which are attached to any single item/category. Left alone, that
        # residual silently vanishes from "where did my money go" - the
        # category list would sum to less than the real total with no
        # indication why. Folding it into a synthetic row (and into the
        # denominator below) means every share_percent reflects the true
        # total, not just the classified portion of it.
        adjustments_current: dict[str, Decimal] = {}
        adjustments_previous: dict[str, Decimal] = {}
        for spend in totals:
            residual_current = spend.current_amount - category_totals.get(spend.currency, Decimal("0"))
            if residual_current > 0:
                adjustments_current[spend.currency] = residual_current
                adjustments_previous[spend.currency] = max(
                    spend.previous_amount - category_previous_totals.get(spend.currency, Decimal("0")),
                    Decimal("0"),
                )
                category_totals[spend.currency] += residual_current

        category_counts: dict[str, int] = defaultdict(int)
        categories = []
        for row in category_rows:
            currency = row["currency"]
            current = _decimal(row["current_amount"])
            if current == 0:
                # No spend here this period - a $0 row carries no information and
                # otherwise reads as misleadingly "new" when it's just empty.
                continue
            if category_counts[currency] >= request.category_limit:
                continue
            previous = _decimal(row["previous_amount"])
            denominator = category_totals[currency]
            share = (
                ((current / denominator) * Decimal("100")).quantize(
                    PERCENT_QUANTUM,
                    rounding=ROUND_HALF_UP,
                )
                if denominator
                else Decimal("0")
            )
            categories.append(
                CategorySpend(
                    category_slug=row["category_slug"],
                    category_name=row["category_name"],
                    taxonomy_level=int(row["taxonomy_level"]),
                    taxonomy_level_name=row["taxonomy_level_name"],
                    has_children=bool(row["has_children"]),
                    currency=currency,
                    current_amount=current,
                    previous_amount=previous,
                    delta_percent=_percent_delta(current, previous),
                    share_percent=share,
                )
            )
            category_counts[currency] += 1

        # Always shown, never counted against category_limit - this is a
        # reconciliation figure, not a competing spending category, so it
        # shouldn't be able to push a real category out of a capped list.
        for currency, amount in adjustments_current.items():
            denominator = category_totals[currency]
            share = (
                ((amount / denominator) * Decimal("100")).quantize(
                    PERCENT_QUANTUM,
                    rounding=ROUND_HALF_UP,
                )
                if denominator
                else Decimal("0")
            )
            previous = adjustments_previous[currency]
            categories.append(
                CategorySpend(
                    category_slug="adjustments.taxes_fees",
                    category_name="Taxes, Fees & Adjustments",
                    taxonomy_level=2,
                    taxonomy_level_name="Group",
                    has_children=False,
                    currency=currency,
                    current_amount=amount,
                    previous_amount=previous,
                    delta_percent=_percent_delta(amount, previous),
                    share_percent=share,
                )
            )

        trend_rows = self.conn.execute(
            """
            /* dashboard:spend-trend */
            with months as (
                select generate_series(
                    date_trunc('month', %(current_end)s::date) - interval '5 months',
                    date_trunc('month', %(current_end)s::date),
                    interval '1 month'
                )::date as period_start
            ),
            currencies as (
                select distinct currency
                from transactions
                where user_id = %(user_id)s
                  and status = 'confirmed'
                  and transaction_date <= %(current_end)s
                  and transaction_type in ('expense', 'refund')
            )
            select months.period_start,
                   to_char(months.period_start, 'Mon') as label,
                   currencies.currency,
                   coalesce(sum(case
                       when t.transaction_type = 'expense' then t.total_amount
                       when t.transaction_type = 'refund' then -abs(t.total_amount)
                       else 0
                   end), 0) as amount
            from months
            cross join currencies
            left join transactions t
              on t.user_id = %(user_id)s
             and t.currency = currencies.currency
             and t.status = 'confirmed'
             and t.transaction_type in ('expense', 'refund')
             and t.transaction_date >= months.period_start
             and t.transaction_date < (months.period_start + interval '1 month')
             and t.transaction_date <= %(current_end)s
            group by months.period_start, currencies.currency
            order by currencies.currency, months.period_start
            """,
            {
                "user_id": self.user_id,
                "current_end": window.current_end,
            },
        ).fetchall()
        spend_trend = [SpendTrendPoint.model_validate(row) for row in trend_rows]

        daily_rows = self.conn.execute(
            """
            /* dashboard:daily-spend */
            select t.transaction_date as spend_date, t.currency,
                   sum(case
                       when t.transaction_type = 'expense' then t.total_amount
                       when t.transaction_type = 'refund' then -abs(t.total_amount)
                       else 0
                   end) as amount,
                   count(*)::integer as transaction_count
            from transactions t
            where t.user_id = %(user_id)s
              and t.status = 'confirmed'
              and t.transaction_type in ('expense', 'refund')
              and t.transaction_date <= %(current_end)s
              and t.transaction_date >= (
                  date_trunc('month', %(current_end)s::date) - interval '11 months'
              )
            group by t.transaction_date, t.currency
            order by t.transaction_date, t.currency
            """,
            {
                "user_id": self.user_id,
                "current_end": window.current_end,
            },
        ).fetchall()
        daily_spend = [DailySpend.model_validate(row) for row in daily_rows]

        review_row = self.conn.execute(
            """
            /* dashboard:review */
            select count(*)::integer as needs_review_count
            from transactions transaction
            where transaction.user_id = %(user_id)s
              and (
                  transaction.status = 'draft'
                  or (
                      transaction.status = 'confirmed'
                      and exists (
                          select 1
                          from transaction_items item
                          join taxonomy_nodes node on node.id = item.taxonomy_node_id
                          where item.transaction_id = transaction.id
                            and item.user_id = transaction.user_id
                            and node.stable_key = 'unclassified.needs_review'
                      )
                  )
              )
            """,
            {"user_id": self.user_id},
        ).fetchone()
        needs_review_count = int(review_row["needs_review_count"]) if review_row else 0

        recent_rows = self.conn.execute(
            """
            /* dashboard:recent */
            select t.id, t.transaction_type, t.source_type, t.classification_mode,
                   t.ingestion_method, t.purchase_channel, t.provider_key,
                   t.status, t.transaction_date,
                   t.merchant_name_raw, t.merchant_name_normalized, t.currency,
                   t.total_amount, t.confirmed_at,
                   (
                       select count(*)
                       from transaction_items recent_item
                       where recent_item.transaction_id = t.id
                         and recent_item.user_id = t.user_id
                   )::integer as item_count
            from transactions t
            where t.user_id = %(user_id)s and t.status <> 'void'
            order by t.transaction_date desc, t.updated_at desc, t.id desc
            limit %(recent_limit)s
            """,
            {"user_id": self.user_id, "recent_limit": request.recent_limit},
        ).fetchall()
        recent = [TransactionSummary.model_validate(row) for row in recent_rows]

        price_changes = self._price_changes(window, request.price_change_limit)
        insights = self._insights(totals, categories, price_changes, needs_review_count)
        return ExpenseDashboard(
            display_name=profile["display_name"] if profile else None,
            default_currency=(profile["default_currency"] if profile else self.fallback_currency),
            window=window,
            totals=totals,
            categories=categories,
            spend_trend=spend_trend,
            daily_spend=daily_spend,
            insights=insights[:3],
            recent_transactions=recent,
            needs_review_count=needs_review_count,
            price_changes=price_changes,
        )

    def get_merchant_breakdown(self, request: MerchantBreakdownRequest) -> MerchantBreakdownResponse:
        window = dashboard_window(request.period, self.today())
        params: dict[str, Any] = {
            "user_id": self.user_id,
            "currency": request.currency,
            "current_start": window.current_start,
            "current_end": window.current_end,
            "previous_start": window.previous_start,
            "previous_end": window.previous_end,
        }
        rows = self.conn.execute(
            """
            /* dashboard:merchants */
            select coalesce(t.merchant_name_normalized, t.merchant_name_raw, 'Unknown merchant')
                       as merchant_name,
                   coalesce(sum(case
                       when t.transaction_date between %(current_start)s and %(current_end)s
                           and t.transaction_type = 'expense' then t.total_amount
                       when t.transaction_date between %(current_start)s and %(current_end)s
                           and t.transaction_type = 'refund' then -abs(t.total_amount)
                       else 0
                   end), 0) as current_amount,
                   coalesce(sum(case
                       when t.transaction_date between %(previous_start)s and %(previous_end)s
                           and t.transaction_type = 'expense' then t.total_amount
                       when t.transaction_date between %(previous_start)s and %(previous_end)s
                           and t.transaction_type = 'refund' then -abs(t.total_amount)
                       else 0
                   end), 0) as previous_amount,
                   count(*) filter (
                       where t.transaction_date between %(current_start)s and %(current_end)s
                         and t.transaction_type = 'expense'
                   ) as visit_count
            from transactions t
            where t.user_id = %(user_id)s
              and t.status = 'confirmed'
              and t.currency = %(currency)s
              and t.transaction_date between %(previous_start)s and %(current_end)s
              and t.transaction_type in ('expense', 'refund')
            group by merchant_name
            order by current_amount desc, merchant_name
            """,
            params,
        ).fetchall()

        total_current = sum((_decimal(row["current_amount"]) for row in rows), Decimal("0"))
        merchants: list[MerchantSpend] = []
        for row in rows:
            current = _decimal(row["current_amount"])
            if current == 0:
                # No visits this period - not "new," just empty; don't list it.
                continue
            if len(merchants) >= request.limit:
                break
            previous = _decimal(row["previous_amount"])
            visit_count = int(row["visit_count"])
            share = (
                ((current / total_current) * Decimal("100")).quantize(
                    PERCENT_QUANTUM,
                    rounding=ROUND_HALF_UP,
                )
                if total_current
                else Decimal("0")
            )
            average_amount = (
                (current / visit_count).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                if visit_count
                else Decimal("0")
            )
            merchants.append(
                MerchantSpend(
                    merchant_name=row["merchant_name"],
                    currency=request.currency,
                    current_amount=current,
                    previous_amount=previous,
                    delta_percent=_percent_delta(current, previous),
                    share_percent=share,
                    visit_count=visit_count,
                    average_amount=average_amount,
                )
            )
        return MerchantBreakdownResponse(window=window, currency=request.currency, merchants=merchants)

    def _price_changes(self, window: DashboardWindow, limit: int) -> list[PriceChange]:
        if limit == 0:
            return []
        # normalized_price_is_estimated rows came from the bare "each" fallback with no
        # captured package size - excluded here so a multi-count pack with an
        # under-captured size can't surface as a false per-unit price swing.
        rows = self.conn.execute(
            """
            /* dashboard:price-changes */
            select i.normalized_name, node.stable_key as taxonomy_key,
                   node.name as taxonomy_name, t.currency, i.normalized_unit,
                   i.normalized_unit_price_amount as price, t.transaction_date,
                   coalesce(t.merchant_name_normalized, t.merchant_name_raw) as merchant,
                   i.quantity, i.unit, i.measured_value, i.measured_unit,
                   i.package_value, i.package_unit,
                   i.updated_at, i.id
            from transaction_items i
            join transactions t on t.id = i.transaction_id and t.user_id = i.user_id
            left join taxonomy_nodes node on node.id = i.taxonomy_node_id
            where i.user_id = %(user_id)s
              and t.status = 'confirmed'
              and t.transaction_type = 'expense'
              and t.transaction_date <= %(current_end)s
              and i.normalized_unit_price_amount is not null
              and not i.normalized_price_is_estimated
              and i.normalized_name is not null
            order by t.transaction_date desc, i.updated_at desc, i.id desc
            """,
            {
                "user_id": self.user_id,
                "current_end": window.current_end,
            },
        ).fetchall()

        grouped: dict[tuple[str, str, str], list[Any]] = defaultdict(list)
        labels: dict[str, str] = {}
        taxonomy_keys: dict[str, str] = {}
        for row in rows:
            identity = canonical_price_watch_identity(
                row["normalized_name"],
                row["taxonomy_key"],
                row["taxonomy_name"],
                row["normalized_unit"],
            )
            if identity is None:
                continue
            labels[identity.key] = identity.label
            taxonomy_keys.setdefault(identity.key, row["taxonomy_key"])
            grouped[(identity.key, row["currency"], row["normalized_unit"])].append(row)

        changes: list[PriceChange] = []
        for (identity_key, currency, normalized_unit), product_rows in grouped.items():
            current_row = product_rows[0]
            previous_row = product_rows[1] if len(product_rows) > 1 else None
            best_row = min(product_rows, key=lambda row: _decimal(row["price"]))
            comparison_row = next(
                (
                    row
                    for row in product_rows
                    if row is not best_row
                    and row["merchant"] != best_row["merchant"]
                    and _decimal(row["price"]) > _decimal(best_row["price"])
                ),
                None,
            )
            if comparison_row is None:
                alternatives = [
                    row
                    for row in product_rows
                    if row is not best_row
                    and _decimal(row["price"]) > _decimal(best_row["price"])
                ]
                comparison_row = max(
                    alternatives,
                    key=lambda row: _decimal(row["price"]),
                    default=None,
                )
            current = _decimal(current_row["price"])
            previous = _decimal(previous_row["price"]) if previous_row else None
            best = _decimal(best_row["price"])
            comparison = (
                _decimal(comparison_row["price"]) if comparison_row is not None else best
            )
            changes.append(
                PriceChange(
                    identity_key=identity_key,
                    label=labels[identity_key],
                    taxonomy_key=taxonomy_keys.get(identity_key),
                    currency=currency,
                    normalized_unit=normalized_unit,
                    current_price=current,
                    previous_price=previous,
                    delta_amount=current - previous if previous is not None else None,
                    delta_percent=(
                        _percent_delta(current, previous)
                        if previous is not None
                        else None
                    ),
                    current_date=current_row["transaction_date"],
                    previous_date=previous_row["transaction_date"] if previous_row else None,
                    current_merchant=current_row["merchant"],
                    previous_merchant=previous_row["merchant"] if previous_row else None,
                    best_price=best,
                    best_date=best_row["transaction_date"],
                    best_merchant=best_row["merchant"],
                    best_quantity_label=_quantity_label(best_row),
                    comparison_price=(
                        comparison if comparison_row is not None else None
                    ),
                    comparison_merchant=(
                        comparison_row["merchant"] if comparison_row is not None else None
                    ),
                    savings_amount=comparison - best,
                    savings_percent=(
                        (((comparison - best) / comparison) * Decimal("100")).quantize(
                            PERCENT_QUANTUM,
                            rounding=ROUND_HALF_UP,
                        )
                        if comparison > best and comparison > 0
                        else Decimal("0")
                    ),
                    sample_size=len(product_rows),
                    # Oldest-to-newest so sparklines read left to right.
                    recent_prices=[
                        _decimal(row["price"]) for row in reversed(product_rows[:6])
                    ],
                )
            )
        changes.sort(
            key=lambda change: (
                change.previous_price is not None,
                abs(change.delta_percent or Decimal("0")),
                change.current_date,
                change.identity_key,
            ),
            reverse=True,
        )
        return changes[:limit]

    def get_personal_basket(self, request: PersonalBasketRequest) -> PersonalBasketIndex:
        """A personal cost-of-living index, deliberately separate from Price
        Watch's family-level grouping (see app/personal_basket.py). For each
        *exact* product bought at least twice within a 180-day window,
        compares the average of its earliest purchases against the average
        of its most recent ones (up to BASKET_TREND_SAMPLE_SIZE each side,
        degrading to a plain earliest-vs-latest comparison when only two
        purchases exist) — smoothing out a single promotion, store switch,
        or data-entry outlier. Products are then averaged into one headline
        figure weighted by spend, with any single product's influence capped
        so one expensive item can't dominate the number.
        """
        window_end = self.today()
        window_start = window_end - timedelta(days=BASKET_WINDOW_DAYS)
        query_params = {
            "user_id": self.user_id,
            "currency": request.currency,
            "window_start": window_start,
            "window_end": window_end,
        }
        total_row = self.conn.execute(
            """
            /* dashboard:tracked-total */
            select coalesce(sum(i.line_total_amount), 0) as total
            from transaction_items i
            join transactions t on t.id = i.transaction_id and t.user_id = i.user_id
            left join taxonomy_nodes node on node.id = i.taxonomy_node_id
            where i.user_id = %(user_id)s
              and t.status = 'confirmed'
              and t.transaction_type = 'expense'
              and t.currency = %(currency)s
              and t.transaction_date >= %(window_start)s
              and t.transaction_date <= %(window_end)s
              and node.stable_key like any(%(trackable_prefixes)s)
            """,
            {
                **query_params,
                "trackable_prefixes": [f"{prefix}%" for prefix in TRACKABLE_PREFIXES],
            },
        ).fetchone()
        total_tracked_spend = _decimal(total_row["total"]) if total_row else Decimal("0")

        rows = self.conn.execute(
            """
            /* dashboard:personal-basket */
            select i.normalized_name, i.brand, node.stable_key as taxonomy_key,
                   i.normalized_unit, i.normalized_unit_price_amount as price,
                   i.line_total_amount, t.transaction_date,
                   coalesce(t.merchant_name_normalized, t.merchant_name_raw) as merchant
            from transaction_items i
            join transactions t on t.id = i.transaction_id and t.user_id = i.user_id
            left join taxonomy_nodes node on node.id = i.taxonomy_node_id
            where i.user_id = %(user_id)s
              and t.status = 'confirmed'
              and t.transaction_type = 'expense'
              and t.currency = %(currency)s
              and t.transaction_date >= %(window_start)s
              and t.transaction_date <= %(window_end)s
              and i.normalized_unit_price_amount is not null
              and not i.normalized_price_is_estimated
              and i.normalized_name is not null
            order by t.transaction_date asc
            """,
            query_params,
        ).fetchall()

        grouped: dict[str, list[Any]] = defaultdict(list)
        labels: dict[str, str] = {}
        for row in rows:
            identity = exact_basket_identity(
                row["normalized_name"],
                row["brand"],
                row["taxonomy_key"],
                row["normalized_unit"],
                row["merchant"],
            )
            if identity is None:
                continue
            labels[identity.key] = identity.label
            grouped[identity.key].append(row)

        products: list[BasketProduct] = []
        for identity_key, item_rows in grouped.items():
            sample_size = len(item_rows)
            if sample_size < 2:
                continue
            take = max(1, min(BASKET_TREND_SAMPLE_SIZE, sample_size // 2))
            baseline_group = item_rows[:take]
            current_group = item_rows[-take:]
            baseline_price = (
                sum((_decimal(row["price"]) for row in baseline_group), Decimal("0")) / take
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            current_price = (
                sum((_decimal(row["price"]) for row in current_group), Decimal("0")) / take
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if baseline_price <= 0:
                continue
            delta_percent = (
                ((current_price - baseline_price) / baseline_price) * Decimal("100")
            ).quantize(PERCENT_QUANTUM, rounding=ROUND_HALF_UP)
            spend_amount = sum(
                (_decimal(item_row["line_total_amount"]) for item_row in item_rows),
                Decimal("0"),
            )
            products.append(
                BasketProduct(
                    identity_key=identity_key,
                    label=labels[identity_key],
                    merchant_name=item_rows[0]["merchant"],
                    currency=request.currency,
                    normalized_unit=str(item_rows[0]["normalized_unit"]),
                    baseline_price=baseline_price,
                    baseline_date=baseline_group[0]["transaction_date"],
                    current_price=current_price,
                    current_date=current_group[-1]["transaction_date"],
                    delta_percent=delta_percent,
                    spend_amount=spend_amount,
                    purchase_count=sample_size,
                )
            )
        products.sort(key=lambda product: product.spend_amount, reverse=True)

        covered_spend = sum((product.spend_amount for product in products), Decimal("0"))
        overall_delta_percent: Decimal | None = None
        if products and covered_spend > 0:
            cap = covered_spend * BASKET_MAX_PRODUCT_WEIGHT_SHARE
            weighted_total = Decimal("0")
            weight_total = Decimal("0")
            for product in products:
                weight = min(product.spend_amount, cap)
                weighted_total += product.delta_percent * weight
                weight_total += weight
            if weight_total > 0:
                overall_delta_percent = (weighted_total / weight_total).quantize(
                    PERCENT_QUANTUM, rounding=ROUND_HALF_UP
                )

        coverage_percent = (
            (covered_spend / total_tracked_spend * Decimal("100")).quantize(
                PERCENT_QUANTUM, rounding=ROUND_HALF_UP
            )
            if total_tracked_spend > 0
            else Decimal("0")
        )
        confidence = (
            "high"
            if len(products) >= BASKET_HIGH_CONFIDENCE_MIN_PRODUCTS
            and coverage_percent >= BASKET_HIGH_CONFIDENCE_MIN_COVERAGE
            else "low"
        )

        return PersonalBasketIndex(
            currency=request.currency,
            window_days=BASKET_WINDOW_DAYS,
            overall_delta_percent=overall_delta_percent,
            product_count=len(products),
            total_tracked_spend=total_tracked_spend,
            covered_spend=covered_spend,
            coverage_percent=coverage_percent,
            confidence=confidence,
            products=products,
        )

    @staticmethod
    def _insights(
        totals: list[CurrencySpend],
        categories: list[CategorySpend],
        price_changes: list[PriceChange],
        needs_review_count: int,
    ) -> list[DashboardInsight]:
        insights: list[DashboardInsight] = []
        if needs_review_count:
            insights.append(
                DashboardInsight(
                    kind="review",
                    title=f"{needs_review_count} expense{'s' if needs_review_count != 1 else ''} need review",
                    detail="Drafts stay out of spending totals until they are validated and confirmed.",
                    tone="attention",
                )
            )
        comparable_changes = [
            change for change in price_changes if change.delta_amount is not None
        ]
        if comparable_changes:
            change = comparable_changes[0]
            delta_amount = change.delta_amount
            assert delta_amount is not None
            direction = "up" if delta_amount > 0 else "down"
            percent = (
                f"{abs(change.delta_percent):.1f}%"
                if change.delta_percent is not None
                else "from its previous price"
            )
            insights.append(
                DashboardInsight(
                    kind="price",
                    title=f"{change.label} is {direction} {percent}",
                    detail=(
                        f"{change.currency} {change.current_price:.2f}/{change.normalized_unit} "
                        f"at {change.current_merchant or 'the latest store'}."
                    ),
                    tone="negative" if delta_amount > 0 else "positive",
                )
            )
        if categories:
            category = max(categories, key=lambda candidate: candidate.current_amount)
            insights.append(
                DashboardInsight(
                    kind="category",
                    title=f"{category.category_name} leads {category.currency} spending",
                    detail=(
                        f"{category.share_percent:.1f}% of total spend in this period."
                    ),
                )
            )
        if len(insights) < 3 and totals:
            total = max(totals, key=lambda candidate: abs(candidate.current_amount))
            if total.delta_percent is None:
                detail = "No comparable spend was recorded in the previous period."
            else:
                direction = "more" if total.delta_amount > 0 else "less"
                detail = f"{abs(total.delta_percent):.1f}% {direction} than the previous period."
            insights.append(
                DashboardInsight(
                    kind="period",
                    title=f"{total.currency} {total.current_amount:.2f} this period",
                    detail=detail,
                    tone="negative" if total.delta_amount > 0 else "positive",
                )
            )
        return insights

    def get_item_price_history(self, request: ItemPriceHistoryRequest) -> ItemPriceHistory:
        identity_type, identity_value = request.identity_key.split(":", 1)
        identity_uuid = UUID(identity_value) if identity_type in {"variant", "concept"} else None
        currency_condition = ""
        query_params: dict[str, Any] = {}
        if request.currency is not None:
            currency_condition = "and t.currency = %(currency)s"
            query_params["currency"] = request.currency

        rows = self.conn.execute(
            f"""
            /* dashboard:item-price-history */
            select t.id as transaction_id, i.id as transaction_item_id,
                   t.transaction_date,
                   coalesce(t.merchant_name_normalized, t.merchant_name_raw) as merchant_name,
                   i.normalized_name, i.brand, i.concept_id, i.variant_id,
                   node.stable_key as taxonomy_key, node.name as taxonomy_name,
                   coalesce(
                       pv.canonical_name,
                       pc.canonical_name,
                       i.normalized_name,
                       i.interpreted_name,
                       i.raw_name
                   ) as display_name,
                   t.currency, i.normalized_unit, i.normalized_unit_price_amount,
                   i.normalized_price_is_estimated as is_estimated,
                   i.quantity, i.unit, i.measured_value, i.measured_unit,
                   i.package_value, i.package_unit, i.line_total_amount
            from transaction_items i
            join transactions t on t.id = i.transaction_id and t.user_id = i.user_id
            left join product_concepts pc on pc.id = i.concept_id
            left join product_variants pv on pv.id = i.variant_id
            left join taxonomy_nodes node on node.id = i.taxonomy_node_id
            where i.user_id = %(user_id)s
              and t.status = 'confirmed'
              and t.transaction_type = 'expense'
              and i.normalized_unit_price_amount is not null
              {currency_condition}
            order by t.transaction_date desc, i.updated_at desc, i.id desc
            """,
            {
                "user_id": self.user_id,
                **query_params,
            },
        ).fetchall()

        target_product_key = identity_value if identity_type == "product" else None
        if identity_type not in {"product", "basket"}:
            for row in rows:
                matches = (
                    identity_type == "name"
                    and str(row["normalized_name"] or "").strip().lower()
                    == identity_value.strip().lower()
                ) or (
                    identity_type == "variant" and row["variant_id"] == identity_uuid
                ) or (
                    identity_type == "concept" and row["concept_id"] == identity_uuid
                )
                if not matches:
                    continue
                canonical = canonical_price_watch_identity(
                    row["normalized_name"],
                    row["taxonomy_key"],
                    row["taxonomy_name"],
                    row["normalized_unit"],
                )
                target_product_key = canonical.key.removeprefix("product:") if canonical else None
                break

        selected_rows = []
        product_label: str | None = None
        for row in rows:
            canonical = canonical_price_watch_identity(
                row["normalized_name"],
                row["taxonomy_key"],
                row["taxonomy_name"],
                row["normalized_unit"],
            )
            # "basket" is a separate, exact identity that must never fall back
            # to Price Watch's blended family match (see app/personal_basket.py).
            basket_identity = exact_basket_identity(
                row["normalized_name"],
                row["brand"],
                row["taxonomy_key"],
                row["normalized_unit"],
                row["merchant_name"],
            )
            matches_product = (
                canonical is not None
                and target_product_key is not None
                and canonical.key == f"product:{target_product_key}"
            )
            matches_exact = (
                target_product_key is None
                and identity_type in {"name", "variant", "concept"}
                and (
                    (
                        identity_type == "name"
                        and str(row["normalized_name"] or "").strip().lower()
                        == identity_value.strip().lower()
                    )
                    or (identity_type == "variant" and row["variant_id"] == identity_uuid)
                    or (identity_type == "concept" and row["concept_id"] == identity_uuid)
                )
            )
            matches_basket = (
                identity_type == "basket"
                and basket_identity is not None
                and basket_identity.key == identity_value
            )
            if not (matches_product or matches_exact or matches_basket):
                continue
            if request.normalized_unit is not None and str(
                row["normalized_unit"] or ""
            ).strip().lower() != request.normalized_unit.strip().lower():
                # A "product" identity_key can span more than one unit (e.g.
                # croissants sold both by weight and by count) - without this,
                # two same-product-different-unit cards collide into whichever
                # unit's series happens to be returned first, regardless of
                # which card was actually clicked.
                continue
            if identity_type == "basket":
                if basket_identity is not None:
                    product_label = basket_identity.label
            elif canonical is not None:
                product_label = canonical.label
            selected_rows.append(row)
            if len(selected_rows) >= request.limit:
                break

        points = [ItemPricePoint.model_validate(row) for row in selected_rows]
        grouped: dict[tuple[str, str], list[ItemPricePoint]] = defaultdict(list)
        for point in points:
            grouped[(point.currency, point.normalized_unit)].append(point)
        series = [
            ItemPriceSeries(currency=currency, normalized_unit=unit, points=series_points)
            for (currency, unit), series_points in sorted(grouped.items())
        ]
        label = product_label or (points[0].display_name if points else identity_value)
        return ItemPriceHistory(identity_key=request.identity_key, label=label, series=series)

    def search_known_items(self, request: SearchKnownItemsRequest) -> SearchKnownItemsResponse:
        # get_item_price_history's "name" identity match is an exact,
        # case-insensitive string comparison - useless for "have I bought
        # something like this before" since that requires already knowing
        # the stored text verbatim. This does a real substring search so a
        # receipt-processing agent can check "milk" and see every existing
        # normalized_name/brand variant before inventing a new one.
        escaped = request.query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        rows = self.conn.execute(
            """
            /* dashboard:search-known-items */
            select
                (array_agg(i.normalized_name order by t.transaction_date desc))[1] as normalized_name,
                i.brand,
                (array_agg(node.stable_key order by t.transaction_date desc))[1] as taxonomy_key,
                (array_agg(node.name order by t.transaction_date desc))[1] as taxonomy_name,
                count(*) as purchase_count,
                max(t.transaction_date) as last_purchased,
                (array_agg(coalesce(t.merchant_name_normalized, t.merchant_name_raw)
                    order by t.transaction_date desc))[1] as last_merchant
            from transaction_items i
            join transactions t on t.id = i.transaction_id and t.user_id = i.user_id
            left join taxonomy_nodes node on node.id = i.taxonomy_node_id
            where i.user_id = %(user_id)s
              and t.status = 'confirmed'
              and t.transaction_type = 'expense'
              and i.normalized_name is not null
              and i.normalized_name ilike %(pattern)s escape '\\'
            group by lower(i.normalized_name), i.brand
            order by count(*) desc, max(t.transaction_date) desc
            limit %(limit)s
            """,
            {
                "user_id": self.user_id,
                "pattern": pattern,
                "limit": request.limit,
            },
        ).fetchall()
        items = [
            KnownItemMatch(
                normalized_name=row["normalized_name"],
                brand=row["brand"],
                taxonomy_key=row["taxonomy_key"],
                taxonomy_name=row["taxonomy_name"],
                purchase_count=row["purchase_count"],
                last_purchased=row["last_purchased"],
                last_merchant=row["last_merchant"],
            )
            for row in rows
        ]
        return SearchKnownItemsResponse(query=request.query, items=items)
