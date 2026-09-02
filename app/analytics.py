from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.models import (
    AnalyticsGrouping,
    AnalyticsMetric,
    AnalyticsQueryRequest,
    AnalyticsQueryResponse,
    AnalyticsRow,
)

ITEM_METRICS = {
    AnalyticsMetric.QUANTITY_PURCHASED,
    AnalyticsMetric.AVERAGE_ITEM_PRICE,
}
ITEM_GROUPINGS = {
    AnalyticsGrouping.CATEGORY,
    AnalyticsGrouping.CONCEPT,
    AnalyticsGrouping.VARIANT,
    AnalyticsGrouping.THEME,
    AnalyticsGrouping.FACET,
}


TRANSACTION_METRICS = {
    AnalyticsMetric.TOTAL_SPEND: """
        coalesce(sum(case
            when t.transaction_type = 'expense' then t.total_amount
            when t.transaction_type = 'refund' then -abs(t.total_amount)
            else 0
        end), 0)
    """,
    AnalyticsMetric.PURCHASE_COUNT: "count(*) filter (where t.transaction_type = 'expense')",
    AnalyticsMetric.DISCOUNT_TOTAL: """
        coalesce(sum(case
            when t.transaction_type = 'expense' then coalesce(t.discount_amount, 0)
            when t.transaction_type = 'refund' then -abs(coalesce(t.discount_amount, 0))
            else 0
        end), 0)
    """,
    AnalyticsMetric.TAX_TOTAL: """
        coalesce(sum(case
            when t.transaction_type = 'expense' then coalesce(t.tax_amount, 0)
            when t.transaction_type = 'refund' then -abs(coalesce(t.tax_amount, 0))
            else 0
        end), 0)
    """,
    AnalyticsMetric.FEE_TOTAL: """
        coalesce(sum(case
            when t.transaction_type = 'expense' then coalesce(t.fee_amount, 0)
            when t.transaction_type = 'refund' then -abs(coalesce(t.fee_amount, 0))
            else 0
        end), 0)
    """,
    AnalyticsMetric.REFUND_TOTAL: """
        coalesce(sum(case when t.transaction_type = 'refund' then abs(t.total_amount) else 0 end), 0)
    """,
}


ITEM_LEVEL_METRICS = {
    AnalyticsMetric.TOTAL_SPEND: """
        coalesce(sum(case
            when t.transaction_type = 'expense' then i.line_total_amount
            when t.transaction_type = 'refund' then -abs(i.line_total_amount)
            else 0
        end), 0)
    """,
    AnalyticsMetric.PURCHASE_COUNT: """
        count(distinct t.id) filter (where t.transaction_type = 'expense')
    """,
    AnalyticsMetric.QUANTITY_PURCHASED: """
        coalesce(sum(case
            when t.transaction_type = 'expense' then coalesce(i.quantity, 0)
            when t.transaction_type = 'refund' then -abs(coalesce(i.quantity, 0))
            else 0
        end), 0)
    """,
    AnalyticsMetric.AVERAGE_ITEM_PRICE: """
        coalesce(avg(abs(coalesce(
            i.unit_price_amount,
            i.line_total_amount / nullif(i.quantity, 0),
            i.line_total_amount
        ))) filter (where t.transaction_type in ('expense', 'refund')), 0)
    """,
    AnalyticsMetric.DISCOUNT_TOTAL: """
        coalesce(sum(case
            when t.transaction_type = 'expense' then coalesce(i.line_discount_amount, 0)
            when t.transaction_type = 'refund' then -abs(coalesce(i.line_discount_amount, 0))
            else 0
        end), 0)
    """,
    AnalyticsMetric.TAX_TOTAL: """
        coalesce(sum(case
            when t.transaction_type = 'expense' then coalesce(i.line_tax_amount, 0)
            when t.transaction_type = 'refund' then -abs(coalesce(i.line_tax_amount, 0))
            else 0
        end), 0)
    """,
    AnalyticsMetric.FEE_TOTAL: """
        coalesce(sum(case
            when t.transaction_type = 'expense' then coalesce(i.line_fee_amount, 0)
            when t.transaction_type = 'refund' then -abs(coalesce(i.line_fee_amount, 0))
            else 0
        end), 0)
    """,
    AnalyticsMetric.REFUND_TOTAL: """
        coalesce(sum(case when t.transaction_type = 'refund' then abs(i.line_total_amount) else 0 end), 0)
    """,
}


DIMENSIONS = {
    AnalyticsGrouping.DAY: "t.transaction_date",
    AnalyticsGrouping.WEEK: "date_trunc('week', t.transaction_date)::date",
    AnalyticsGrouping.MONTH: "date_trunc('month', t.transaction_date)::date",
    AnalyticsGrouping.MERCHANT: "coalesce(t.merchant_name_normalized, t.merchant_name_raw, 'Unspecified')",
    AnalyticsGrouping.CATEGORY: "category_node.stable_key",
    AnalyticsGrouping.CONCEPT: "coalesce(pc.canonical_name, 'Unassigned')",
    AnalyticsGrouping.VARIANT: "coalesce(pv.canonical_name, 'Unassigned')",
    AnalyticsGrouping.THEME: "th.slug",
    AnalyticsGrouping.FACET: "facet_value.stable_key",
    AnalyticsGrouping.INGESTION_METHOD: "t.ingestion_method::text",
    AnalyticsGrouping.PURCHASE_CHANNEL: "t.purchase_channel::text",
    AnalyticsGrouping.PROVIDER: "coalesce(t.provider_key, 'none')",
    AnalyticsGrouping.CURRENCY: "t.currency",
}


@dataclass(frozen=True)
class AnalyticsStatement:
    sql: str
    params: dict[str, Any]
    dimension_aliases: tuple[tuple[AnalyticsGrouping, str], ...]
    metric_aliases: tuple[tuple[AnalyticsMetric, str], ...]


class AnalyticsQueryCompiler:
    def __init__(self, today: Callable[[], date] = date.today) -> None:
        self.today = today

    def compile(self, user_id: UUID, request: AnalyticsQueryRequest) -> AnalyticsStatement:
        filters = request.filters
        group_by = list(request.group_by)
        if filters.currency is None and AnalyticsGrouping.CURRENCY not in group_by:
            # Never combine monetary values across currencies. The implicit
            # dimension also keeps count-only queries honest and inspectable.
            group_by.append(AnalyticsGrouping.CURRENCY)
        dimensions = dict(DIMENSIONS)
        params: dict[str, Any] = {"user_id": user_id}
        taxonomy_rollup_level = request.taxonomy_rollup_level
        if taxonomy_rollup_level is None and request.category_rollup_depth is not None:
            taxonomy_rollup_level = request.category_rollup_depth + 1
        params["taxonomy_rollup_level"] = taxonomy_rollup_level or 6
        uses_items = bool(
            set(request.metrics) & ITEM_METRICS
            or set(group_by) & ITEM_GROUPINGS
            or filters.category_slug
            or filters.taxonomy_node_key
            or filters.product_concept_id
            or filters.product_variant_id
            or filters.theme_slug
            or filters.facet_value_key
        )
        metrics = ITEM_LEVEL_METRICS if uses_items else TRANSACTION_METRICS

        joins: list[str] = []
        if uses_items:
            joins.append("join transaction_items i on i.transaction_id = t.id and i.user_id = t.user_id")
        if (
            AnalyticsGrouping.CATEGORY in group_by
            or filters.category_slug
            or filters.taxonomy_node_key
        ):
            joins.extend(
                [
                    "join taxonomy_nodes item_node on item_node.id = i.taxonomy_node_id",
                    """join lateral (
                        select ancestor.id, ancestor.stable_key, ancestor.name, ancestor.level
                        from taxonomy_node_closure path
                        join taxonomy_nodes ancestor on ancestor.id = path.ancestor_id
                        where path.version_id = item_node.version_id
                          and path.descendant_id = item_node.id
                          and ancestor.level <= %(taxonomy_rollup_level)s
                        order by ancestor.level desc
                        limit 1
                    ) category_node on true""",
                ]
            )
        if AnalyticsGrouping.CONCEPT in group_by:
            joins.append("left join product_concepts pc on pc.id = i.concept_id")
        if AnalyticsGrouping.VARIANT in group_by:
            joins.append("left join product_variants pv on pv.id = i.variant_id")
        if AnalyticsGrouping.THEME in group_by:
            joins.extend(
                [
                    "join transaction_item_themes it on it.item_id = i.id and it.user_id = t.user_id",
                    "join themes th on th.id = it.theme_id",
                ]
            )
        if AnalyticsGrouping.FACET in group_by:
            joins.extend(
                [
                    "join transaction_item_facets item_facet on item_facet.item_id = i.id "
                    "and item_facet.user_id = t.user_id",
                    "join taxonomy_facet_values facet_value on facet_value.id = item_facet.facet_value_id",
                ]
            )

        dimension_aliases = tuple(
            (grouping, f"dimension_{index}") for index, grouping in enumerate(group_by)
        )
        metric_aliases = tuple((metric, f"metric_{index}") for index, metric in enumerate(request.metrics))
        select_parts = [f"{dimensions[grouping]} as {alias}" for grouping, alias in dimension_aliases]
        select_parts.extend(f"{metrics[metric]} as {alias}" for metric, alias in metric_aliases)

        conditions = ["t.user_id = %(user_id)s", "t.status = 'confirmed'"]

        if filters.relative_days is not None:
            end_date = self.today()
            params["start_date"] = end_date - timedelta(days=filters.relative_days - 1)
            params["end_date"] = end_date
            conditions.extend(
                ["t.transaction_date >= %(start_date)s", "t.transaction_date <= %(end_date)s"]
            )
        else:
            if filters.start_date is not None:
                params["start_date"] = filters.start_date
                conditions.append("t.transaction_date >= %(start_date)s")
            if filters.end_date is not None:
                params["end_date"] = filters.end_date
                conditions.append("t.transaction_date <= %(end_date)s")
        if filters.merchant is not None:
            params["merchant"] = filters.merchant.strip()
            conditions.append(
                "lower(coalesce(t.merchant_name_normalized, t.merchant_name_raw, '')) = lower(%(merchant)s)"
            )
        taxonomy_filter = filters.taxonomy_node_key or filters.category_slug
        if taxonomy_filter is not None:
            params["taxonomy_node_key"] = taxonomy_filter
            category_condition = "item_node.stable_key = %(taxonomy_node_key)s"
            if filters.include_descendants:
                category_condition = """exists (
                    select 1
                    from taxonomy_nodes selected_node
                    join taxonomy_versions selected_version
                      on selected_version.id = selected_node.version_id
                     and selected_version.status = 'active'
                    join taxonomy_node_closure selected_branch
                      on selected_branch.version_id = selected_node.version_id
                     and selected_branch.ancestor_id = selected_node.id
                     and selected_branch.descendant_id = item_node.id
                    where selected_node.stable_key = %(taxonomy_node_key)s
                )"""
            conditions.append(category_condition)
        if filters.product_concept_id is not None:
            params["product_concept_id"] = filters.product_concept_id
            conditions.append("i.concept_id = %(product_concept_id)s")
        if filters.product_variant_id is not None:
            params["product_variant_id"] = filters.product_variant_id
            conditions.append("i.variant_id = %(product_variant_id)s")
        if filters.theme_slug is not None:
            params["theme_slug"] = filters.theme_slug
            if AnalyticsGrouping.THEME in group_by:
                conditions.append("th.slug = %(theme_slug)s")
            else:
                conditions.append(
                    """exists (
                        select 1
                        from transaction_item_themes fit
                        join themes fth on fth.id = fit.theme_id
                        where fit.item_id = i.id
                          and fit.user_id = t.user_id
                          and fth.slug = %(theme_slug)s
                    )"""
                )
        if filters.facet_value_key is not None:
            params["facet_value_key"] = filters.facet_value_key
            if AnalyticsGrouping.FACET in group_by:
                conditions.append("facet_value.stable_key = %(facet_value_key)s")
            else:
                conditions.append(
                    """exists (
                        select 1
                        from transaction_item_facets filter_item_facet
                        join taxonomy_facet_values filter_facet_value
                          on filter_facet_value.id = filter_item_facet.facet_value_id
                        where filter_item_facet.item_id = i.id
                          and filter_item_facet.user_id = t.user_id
                          and filter_facet_value.stable_key = %(facet_value_key)s
                    )"""
                )
        if filters.source_type is not None:
            params["source_type"] = filters.source_type.value
            conditions.append("t.source_type = %(source_type)s")
        if filters.ingestion_method is not None:
            params["ingestion_method"] = filters.ingestion_method.value
            conditions.append("t.ingestion_method = %(ingestion_method)s")
        if filters.purchase_channel is not None:
            params["purchase_channel"] = filters.purchase_channel.value
            conditions.append("t.purchase_channel = %(purchase_channel)s")
        if filters.provider_key is not None:
            params["provider_key"] = filters.provider_key
            conditions.append("t.provider_key = %(provider_key)s")
        if filters.transaction_type is not None:
            params["transaction_type"] = filters.transaction_type.value
            conditions.append("t.transaction_type = %(transaction_type)s")
        if filters.currency is not None:
            params["currency"] = filters.currency
            conditions.append("t.currency = %(currency)s")

        group_expressions = [dimensions[grouping] for grouping in group_by]
        group_clause = f"group by {', '.join(group_expressions)}" if group_expressions else ""
        order_clause = (
            f"order by {', '.join(alias for _, alias in dimension_aliases)}" if dimension_aliases else ""
        )
        sql = "\n".join(
            part
            for part in [
                f"select {', '.join(select_parts)}",
                "from transactions t",
                *joins,
                f"where {' and '.join(conditions)}",
                group_clause,
                order_clause,
            ]
            if part
        )
        return AnalyticsStatement(sql, params, dimension_aliases, metric_aliases)


class AnalyticsRepository:
    def __init__(
        self,
        conn: Any,
        user_id: UUID,
        compiler: AnalyticsQueryCompiler | None = None,
    ) -> None:
        self.conn = conn
        self.user_id = user_id
        self.compiler = compiler or AnalyticsQueryCompiler()

    def query(self, request: AnalyticsQueryRequest) -> AnalyticsQueryResponse:
        statement = self.compiler.compile(self.user_id, request)
        result = self.conn.execute(statement.sql, statement.params).fetchall()
        rows: list[AnalyticsRow] = []
        for result_row in result:
            dimensions = {
                grouping.value: result_row[alias] for grouping, alias in statement.dimension_aliases
            }
            metric_values = {
                metric.value: Decimal(str(result_row[alias] or 0))
                for metric, alias in statement.metric_aliases
            }
            rows.append(AnalyticsRow(dimensions=dimensions, metrics=metric_values))
        return AnalyticsQueryResponse(rows=rows)
