from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from psycopg.types.json import Jsonb

from app.errors import ConflictError, NotFoundError, ValidationReferenceError
from app.measurements import derive_normalized_price
from app.models import (
    AliasResolution,
    AliasResolveItem,
    Category,
    SourceType,
    TaxonomyBranch,
    TaxonomyFacet,
    TaxonomyManifest,
    TaxonomyNode,
    TaxonomySearchResponse,
    TaxonomyVersion,
    Theme,
    TransactionAdjustment,
    TransactionAdjustmentCreate,
    TransactionAdjustmentUpdate,
    TransactionDetail,
    TransactionDraftCreate,
    TransactionItem,
    TransactionItemCreate,
    TransactionItemUpdate,
    TransactionListFilters,
    TransactionListResponse,
    TransactionPatch,
    TransactionStatus,
    TransactionSummary,
    ValidationIssue,
)
from app.normalization import normalize_lookup_text

PRICE_INPUT_FIELDS = {
    "quantity",
    "unit",
    "measured_value",
    "measured_unit",
    "package_value",
    "package_unit",
    "unit_price_amount",
    "unit_price_basis_value",
    "unit_price_basis_unit",
    "line_subtotal_amount",
    "line_discount_amount",
    "line_tax_amount",
    "line_fee_amount",
    "line_total_amount",
}


def _normalized_price_fields(source: Any) -> dict[str, Decimal | str | bool | None]:
    measurement_pairs = (
        ("measured_value", "measured_unit"),
        ("package_value", "package_unit"),
        ("unit_price_basis_value", "unit_price_basis_unit"),
    )
    for value_field, unit_field in measurement_pairs:
        if (getattr(source, value_field, None) is None) != (getattr(source, unit_field, None) is None):
            raise ValidationReferenceError(f"{value_field} and {unit_field} must be supplied together")
    normalized = derive_normalized_price(
        quantity=getattr(source, "quantity", None),
        unit=getattr(source, "unit", None),
        measured_value=getattr(source, "measured_value", None),
        measured_unit=getattr(source, "measured_unit", None),
        package_value=getattr(source, "package_value", None),
        package_unit=getattr(source, "package_unit", None),
        unit_price_amount=getattr(source, "unit_price_amount", None),
        unit_price_basis_value=getattr(source, "unit_price_basis_value", None),
        unit_price_basis_unit=getattr(source, "unit_price_basis_unit", None),
        line_subtotal_amount=getattr(source, "line_subtotal_amount", None),
        line_discount_amount=getattr(source, "line_discount_amount", None),
        line_tax_amount=getattr(source, "line_tax_amount", None),
        line_fee_amount=getattr(source, "line_fee_amount", None),
        line_total_amount=source.line_total_amount,
    )
    return {
        "normalized_unit": normalized.normalized_unit,
        "normalized_unit_price_amount": normalized.normalized_unit_price_amount,
        "normalized_price_is_estimated": normalized.is_estimated,
    }


class TaxonomyRepository:
    def __init__(self, conn: Any) -> None:
        self.conn = conn

    def list_categories(self) -> list[Category]:
        rows = self.conn.execute(
            """
            select category.id, category.slug, category.parent_id, category.name,
                   category.depth, category.path_slug, category.sort_order,
                   not exists (
                       select 1
                       from categories child
                       where child.parent_id = category.id
                         and child.is_active = true
                   ) as is_assignable
            from categories category
            where category.is_active = true
            order by path_slug
            """
        ).fetchall()
        return [Category.model_validate(row) for row in rows]

    def list_themes(self) -> list[Theme]:
        rows = self.conn.execute(
            """
            select id, slug, name, description
            from themes
            where is_active = true
            order by slug
            """
        ).fetchall()
        return [Theme.model_validate(row) for row in rows]

    @staticmethod
    def _node_projection(alias: str = "node") -> str:
        return f"""
            {alias}.id, {alias}.version_id, {alias}.stable_key, {alias}.parent_id,
            {alias}.level, version.level_names ->> ({alias}.level - 1) as level_name,
            {alias}.name, {alias}.description, {alias}.sort_order,
            {alias}.is_assignable,
            {alias}.allowed_transaction_types::text[] as allowed_transaction_types,
            coalesce((
                select jsonb_agg(
                    jsonb_build_object(
                        'id', ancestor.id,
                        'stable_key', ancestor.stable_key,
                        'level', ancestor.level,
                        'level_name', version.level_names ->> (ancestor.level - 1),
                        'name', ancestor.name
                    )
                    order by ancestor.level
                )
                from taxonomy_node_closure path
                join taxonomy_nodes ancestor on ancestor.id = path.ancestor_id
                where path.version_id = {alias}.version_id
                  and path.descendant_id = {alias}.id
            ), '[]'::jsonb) as path,
            coalesce((
                select jsonb_agg(synonym.term order by synonym.term)
                from taxonomy_synonyms synonym
                where synonym.version_id = {alias}.version_id
                  and synonym.node_id = {alias}.id
            ), '[]'::jsonb) as synonyms,
            {alias}.metadata
        """

    def active_version(self) -> TaxonomyVersion:
        row = self.conn.execute(
            """
            select id, version, content_hash, status, level_names, max_depth
            from taxonomy_versions
            where status = 'active'
            """
        ).fetchone()
        if row is None:
            raise NotFoundError("No active taxonomy version is configured")
        return TaxonomyVersion.model_validate(row)

    def list_nodes(
        self,
        *,
        assignable_only: bool = False,
        transaction_type: str | None = None,
    ) -> list[TaxonomyNode]:
        conditions = ["version.status = 'active'"]
        params: dict[str, Any] = {}
        if assignable_only:
            conditions.append("node.is_assignable = true")
        if transaction_type is not None:
            conditions.append("%(transaction_type)s::transaction_type = any(node.allowed_transaction_types)")
            params["transaction_type"] = transaction_type
        rows = self.conn.execute(
            f"""
            select {self._node_projection()}
            from taxonomy_nodes node
            join taxonomy_versions version on version.id = node.version_id
            where {" and ".join(conditions)}
            order by node.stable_key
            """,
            params,
        ).fetchall()
        return [TaxonomyNode.model_validate(row) for row in rows]

    def list_facets(self) -> list[TaxonomyFacet]:
        rows = self.conn.execute(
            """
            select facet.id, facet.stable_key, facet.name, facet.description,
                   facet.selection_mode,
                   coalesce(
                       jsonb_agg(
                           jsonb_build_object(
                               'id', value.id,
                               'facet_id', value.facet_id,
                               'stable_key', value.stable_key,
                               'name', value.name,
                               'description', value.description,
                               'sort_order', value.sort_order
                           )
                           order by value.sort_order, value.stable_key
                       ) filter (where value.id is not null),
                       '[]'::jsonb
                   ) as values
            from taxonomy_facets facet
            left join taxonomy_facet_values value
              on value.facet_id = facet.id and value.is_active = true
            where facet.is_active = true
            group by facet.id
            order by facet.stable_key
            """
        ).fetchall()
        return [TaxonomyFacet.model_validate(row) for row in rows]

    def manifest(self, *, transaction_type: str | None = None) -> TaxonomyManifest:
        nodes = self.list_nodes(transaction_type=transaction_type)
        return TaxonomyManifest(
            version=self.active_version(),
            roots=[node for node in nodes if node.parent_id is None],
            assignable_nodes=[node for node in nodes if node.is_assignable],
            facets=self.list_facets(),
        )

    def get_node(self, stable_key: str) -> TaxonomyNode:
        row = self.conn.execute(
            f"""
            select {self._node_projection()}
            from taxonomy_nodes node
            join taxonomy_versions version on version.id = node.version_id
            where version.status = 'active' and node.stable_key = %(stable_key)s
            """,
            {"stable_key": stable_key},
        ).fetchone()
        if row is None:
            raise NotFoundError("Taxonomy node not found")
        return TaxonomyNode.model_validate(row)

    def branch(self, stable_key: str) -> TaxonomyBranch:
        root = self.get_node(stable_key)
        rows = self.conn.execute(
            f"""
            select {self._node_projection()}
            from taxonomy_nodes node
            join taxonomy_versions version on version.id = node.version_id
            join taxonomy_node_closure branch
              on branch.version_id = node.version_id
             and branch.descendant_id = node.id
            where version.status = 'active' and branch.ancestor_id = %(root_id)s
            order by node.stable_key
            """,
            {"root_id": root.id},
        ).fetchall()
        return TaxonomyBranch(root=root, nodes=[TaxonomyNode.model_validate(row) for row in rows])

    def search(self, query: str, *, limit: int = 20) -> TaxonomySearchResponse:
        normalized_query = query.strip()
        rows = self.conn.execute(
            f"""
            select {self._node_projection()}
            from taxonomy_nodes node
            join taxonomy_versions version on version.id = node.version_id
            where version.status = 'active'
              and node.is_assignable = true
              and (
                  node.stable_key ilike '%%' || %(query)s || '%%'
                  or node.name ilike '%%' || %(query)s || '%%'
                  or exists (
                      select 1
                      from taxonomy_synonyms synonym
                      where synonym.version_id = node.version_id
                        and synonym.node_id = node.id
                        and synonym.term ilike '%%' || %(query)s || '%%'
                  )
              )
            order by
                case
                    when lower(node.name) = lower(%(query)s) then 0
                    when lower(node.stable_key) = lower(%(query)s) then 1
                    else 2
                end,
                node.level desc,
                node.stable_key
            limit %(limit)s
            """,
            {"query": normalized_query, "limit": limit},
        ).fetchall()
        return TaxonomySearchResponse(
            query=normalized_query,
            results=[TaxonomyNode.model_validate(row) for row in rows],
        )

    def resolve_assignable_node_id(self, stable_key: str, transaction_type: str) -> UUID:
        row = self.conn.execute(
            """
            select node.id
            from taxonomy_nodes node
            join taxonomy_versions version on version.id = node.version_id
            where version.status = 'active'
              and node.stable_key = %(stable_key)s
              and node.is_assignable = true
              and %(transaction_type)s::transaction_type = any(node.allowed_transaction_types)
            union all
            select mapping.taxonomy_node_id
            from categories category
            join legacy_category_taxonomy_map mapping on mapping.category_id = category.id
            join taxonomy_nodes node on node.id = mapping.taxonomy_node_id
            join taxonomy_versions version on version.id = node.version_id
            where version.status = 'active'
              and category.slug = %(stable_key)s
              and node.is_assignable = true
              and %(transaction_type)s::transaction_type = any(node.allowed_transaction_types)
            limit 1
            """,
            {"stable_key": stable_key, "transaction_type": transaction_type},
        ).fetchone()
        if row is None:
            raise ValidationReferenceError(
                f"Unknown, inactive, non-assignable, or incompatible taxonomy node: {stable_key}"
            )
        return cast(UUID, row["id"])

    def legacy_category_id_for_node(self, taxonomy_node_id: UUID) -> UUID | None:
        row = self.conn.execute(
            """
            select mapping.category_id
            from legacy_category_taxonomy_map mapping
            where mapping.taxonomy_node_id = %(taxonomy_node_id)s
            order by (
                select category.depth from categories category where category.id = mapping.category_id
            ) desc, mapping.category_id
            limit 1
            """,
            {"taxonomy_node_id": taxonomy_node_id},
        ).fetchone()
        return cast(UUID | None, row["category_id"] if row is not None else None)

    def facet_value_ids(self, stable_keys: list[str]) -> dict[str, UUID]:
        if not stable_keys:
            return {}
        if len(stable_keys) != len(set(stable_keys)):
            raise ValidationReferenceError("Duplicate facet values are not allowed")
        rows = self.conn.execute(
            """
            select value.id, value.stable_key, facet.id as facet_id, facet.selection_mode
            from taxonomy_facet_values value
            join taxonomy_facets facet on facet.id = value.facet_id
            where value.is_active = true
              and facet.is_active = true
              and value.stable_key = any(%(stable_keys)s)
            """,
            {"stable_keys": stable_keys},
        ).fetchall()
        by_key = {row["stable_key"]: row for row in rows}
        missing = sorted(set(stable_keys) - set(by_key))
        if missing:
            raise ValidationReferenceError(f"Unknown facet values: {', '.join(missing)}")
        single_facets: set[UUID] = set()
        for row in rows:
            if row["selection_mode"] == "single" and row["facet_id"] in single_facets:
                raise ValidationReferenceError("A single-select facet may only have one value")
            if row["selection_mode"] == "single":
                single_facets.add(row["facet_id"])
        return {key: cast(UUID, row["id"]) for key, row in by_key.items()}


class TransactionRepository:
    def __init__(self, conn: Any, user_id: UUID) -> None:
        self.conn = conn
        self.user_id = user_id

    def create_draft(
        self,
        payload: TransactionDraftCreate,
        *,
        transaction_id: UUID | None = None,
        receipt_id: UUID | None = None,
    ) -> TransactionDetail:
        tx_row = self.conn.execute(
            """
            insert into transactions (
                id, user_id, transaction_type, source_type, status, transaction_date,
                classification_mode, ingestion_method, purchase_channel, provider_key,
                merchant_name_raw, merchant_name_normalized, notes, currency,
                subtotal_amount, tax_amount, fee_amount, discount_amount,
                tip_amount, deposit_amount, rounding_amount, total_amount
            )
            values (
                coalesce(%(transaction_id)s, gen_random_uuid()), %(user_id)s,
                %(transaction_type)s, %(source_type)s, 'draft', %(transaction_date)s,
                %(classification_mode)s, %(ingestion_method)s, %(purchase_channel)s, %(provider_key)s,
                %(merchant_name_raw)s, %(merchant_name_normalized)s, %(notes)s, %(currency)s,
                %(subtotal_amount)s, %(tax_amount)s, %(fee_amount)s, %(discount_amount)s,
                %(tip_amount)s, %(deposit_amount)s, %(rounding_amount)s,
                %(total_amount)s
            )
            returning id
            """,
            {
                "user_id": self.user_id,
                "transaction_id": transaction_id,
                "transaction_type": payload.transaction_type.value,
                "source_type": payload.source_type.value,
                "transaction_date": payload.transaction_date,
                "classification_mode": payload.classification_mode.value,
                "ingestion_method": payload.ingestion_method.value,
                "purchase_channel": payload.purchase_channel.value,
                "provider_key": payload.provider_key,
                "merchant_name_raw": payload.merchant_name_raw,
                "merchant_name_normalized": payload.merchant_name_normalized,
                "notes": payload.notes,
                "currency": payload.currency,
                "subtotal_amount": payload.subtotal_amount,
                "tax_amount": payload.tax_amount,
                "fee_amount": payload.fee_amount,
                "discount_amount": payload.discount_amount,
                "tip_amount": payload.tip_amount,
                "deposit_amount": payload.deposit_amount,
                "rounding_amount": payload.rounding_amount,
                "total_amount": payload.total_amount,
            },
        ).fetchone()
        transaction_id = tx_row["id"]

        if payload.receipt is not None or payload.source_type == SourceType.RECEIPT:
            receipt = payload.receipt
            self.conn.execute(
                """
                insert into receipts (
                    id, user_id, transaction_id, receipt_date, receipt_number, raw_payload
                )
                values (
                    coalesce(%(receipt_id)s, gen_random_uuid()), %(user_id)s,
                    %(transaction_id)s, %(receipt_date)s, %(receipt_number)s, %(raw_payload)s
                )
                """,
                {
                    "receipt_id": receipt_id,
                    "user_id": self.user_id,
                    "transaction_id": transaction_id,
                    "receipt_date": receipt.receipt_date if receipt else None,
                    "receipt_number": receipt.receipt_number if receipt else None,
                    "raw_payload": Jsonb(receipt.raw_payload if receipt else {}),
                },
            )

        for item in payload.items:
            self.add_item(transaction_id, item)

        for adjustment in payload.adjustments:
            self.add_adjustment(transaction_id, adjustment)

        self.add_audit_event("transaction", transaction_id, "draft_created", {})
        return self.get_transaction(transaction_id)

    def get_transaction(self, transaction_id: UUID) -> TransactionDetail:
        row = self.conn.execute(
            """
            select id, transaction_type, source_type, classification_mode,
                   ingestion_method, purchase_channel, provider_key, status,
                   transaction_date, merchant_name_raw, merchant_name_normalized, notes, currency,
                   subtotal_amount, tax_amount, fee_amount, discount_amount,
                   tip_amount, deposit_amount, rounding_amount,
                   total_amount, reconciliation_delta_amount, confirmed_at,
                   created_at, updated_at
            from transactions
            where id = %(transaction_id)s and user_id = %(user_id)s
            """,
            {"transaction_id": transaction_id, "user_id": self.user_id},
        ).fetchone()
        if row is None:
            raise NotFoundError("Transaction not found")

        return TransactionDetail(
            **row,
            items=self.list_items(transaction_id),
            adjustments=self.list_adjustments(transaction_id),
            validation_issues=self.list_validation_issues(transaction_id),
        )

    def list_transactions(self, filters: TransactionListFilters) -> TransactionListResponse:
        conditions = ["t.user_id = %(user_id)s"]
        params: dict[str, Any] = {
            "user_id": self.user_id,
            "limit": filters.limit,
            "offset": filters.offset,
        }
        if filters.status is not None:
            params["status"] = filters.status.value
            conditions.append("t.status = %(status)s")
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
            taxonomy_match = "item_node.stable_key = %(taxonomy_node_key)s"
            if filters.include_descendants:
                taxonomy_match = """
                    exists (
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
                    )
                """
            conditions.append(
                f"""exists (
                    select 1
                    from transaction_items fi
                    join taxonomy_nodes item_node on item_node.id = fi.taxonomy_node_id
                    where fi.transaction_id = t.id
                      and fi.user_id = %(user_id)s
                      and {taxonomy_match}
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

        where_clause = " and ".join(conditions)
        total_row = self.conn.execute(
            f"select count(*) as total from transactions t where {where_clause}",
            params,
        ).fetchone()
        rows = self.conn.execute(
            f"""
            select t.id, t.transaction_type, t.source_type, t.classification_mode,
                   t.ingestion_method, t.purchase_channel, t.provider_key,
                   t.status, t.transaction_date,
                   t.merchant_name_raw, t.merchant_name_normalized, t.currency,
                   t.total_amount, t.confirmed_at,
                   (
                       select count(*)
                       from transaction_items summary_item
                       where summary_item.transaction_id = t.id
                         and summary_item.user_id = t.user_id
                   )::integer as item_count
            from transactions t
            where {where_clause}
            order by t.transaction_date desc, t.id desc
            limit %(limit)s offset %(offset)s
            """,
            params,
        ).fetchall()
        return TransactionListResponse(
            transactions=[TransactionSummary.model_validate(row) for row in rows],
            total=int(total_row["total"]),
            limit=filters.limit,
            offset=filters.offset,
        )

    def lock_draft(self, transaction_id: UUID) -> tuple[TransactionStatus, datetime]:
        row = self.conn.execute(
            """
            select status, updated_at
            from transactions
            where id = %(transaction_id)s and user_id = %(user_id)s
            for update
            """,
            {"transaction_id": transaction_id, "user_id": self.user_id},
        ).fetchone()
        if row is None:
            raise NotFoundError("Transaction not found")
        return TransactionStatus(row["status"]), row["updated_at"]

    def replace_draft(self, transaction_id: UUID, payload: TransactionDraftCreate) -> TransactionDetail:
        status, _revision = self.lock_draft(transaction_id)
        if status != TransactionStatus.DRAFT:
            raise ConflictError("Only draft transactions can be replaced atomically")

        self.conn.execute(
            """
            update transactions
            set transaction_type = %(transaction_type)s,
                source_type = %(source_type)s,
                classification_mode = %(classification_mode)s,
                ingestion_method = %(ingestion_method)s,
                purchase_channel = %(purchase_channel)s,
                provider_key = %(provider_key)s,
                transaction_date = %(transaction_date)s,
                merchant_name_raw = %(merchant_name_raw)s,
                merchant_name_normalized = %(merchant_name_normalized)s,
                notes = %(notes)s,
                currency = %(currency)s,
                subtotal_amount = %(subtotal_amount)s,
                tax_amount = %(tax_amount)s,
                fee_amount = %(fee_amount)s,
                discount_amount = %(discount_amount)s,
                tip_amount = %(tip_amount)s,
                deposit_amount = %(deposit_amount)s,
                rounding_amount = %(rounding_amount)s,
                total_amount = %(total_amount)s
            where id = %(transaction_id)s and user_id = %(user_id)s
            """,
            {
                "transaction_id": transaction_id,
                "user_id": self.user_id,
                "transaction_type": payload.transaction_type.value,
                "source_type": payload.source_type.value,
                "classification_mode": payload.classification_mode.value,
                "ingestion_method": payload.ingestion_method.value,
                "purchase_channel": payload.purchase_channel.value,
                "provider_key": payload.provider_key,
                "transaction_date": payload.transaction_date,
                "merchant_name_raw": payload.merchant_name_raw,
                "merchant_name_normalized": payload.merchant_name_normalized,
                "notes": payload.notes,
                "currency": payload.currency,
                "subtotal_amount": payload.subtotal_amount,
                "tax_amount": payload.tax_amount,
                "fee_amount": payload.fee_amount,
                "discount_amount": payload.discount_amount,
                "tip_amount": payload.tip_amount,
                "deposit_amount": payload.deposit_amount,
                "rounding_amount": payload.rounding_amount,
                "total_amount": payload.total_amount,
            },
        )

        if payload.receipt is not None or payload.source_type == SourceType.RECEIPT:
            receipt = payload.receipt
            self.conn.execute(
                """
                insert into receipts (
                    user_id, transaction_id, receipt_date, receipt_number, raw_payload
                )
                values (
                    %(user_id)s, %(transaction_id)s, %(receipt_date)s,
                    %(receipt_number)s, %(raw_payload)s
                )
                on conflict (transaction_id) do update
                set receipt_date = excluded.receipt_date,
                    receipt_number = excluded.receipt_number,
                    raw_payload = excluded.raw_payload
                """,
                {
                    "user_id": self.user_id,
                    "transaction_id": transaction_id,
                    "receipt_date": receipt.receipt_date if receipt else None,
                    "receipt_number": receipt.receipt_number if receipt else None,
                    "raw_payload": Jsonb(receipt.raw_payload if receipt else {}),
                },
            )

        self.conn.execute(
            """
            delete from transaction_adjustments
            where transaction_id = %(transaction_id)s and user_id = %(user_id)s
            """,
            {"transaction_id": transaction_id, "user_id": self.user_id},
        )
        self.conn.execute(
            """
            delete from transaction_items
            where transaction_id = %(transaction_id)s and user_id = %(user_id)s
            """,
            {"transaction_id": transaction_id, "user_id": self.user_id},
        )
        for item in payload.items:
            self.add_item(transaction_id, item)

        self.clear_validation_issues(transaction_id)
        self.add_audit_event("transaction", transaction_id, "draft_replaced", {})
        return self.get_transaction(transaction_id)

    def replace_confirmed(
        self,
        transaction_id: UUID,
        payload: TransactionDraftCreate,
        correction_reason: str,
    ) -> TransactionDetail:
        """Atomically replace a confirmed expense and retain one before/after audit record."""
        status, _revision = self.lock_draft(transaction_id)
        if status != TransactionStatus.CONFIRMED:
            raise ConflictError("Only confirmed expenses can be replaced through corrections")
        current = self.get_transaction(transaction_id)
        self.add_correction(
            transaction_id,
            None,
            "expense_snapshot",
            current.model_dump(mode="json"),
            payload.model_dump(mode="json"),
            correction_reason,
        )

        self.conn.execute(
            """
            update transactions
            set transaction_type = %(transaction_type)s,
                source_type = %(source_type)s,
                classification_mode = %(classification_mode)s,
                ingestion_method = %(ingestion_method)s,
                purchase_channel = %(purchase_channel)s,
                provider_key = %(provider_key)s,
                transaction_date = %(transaction_date)s,
                merchant_name_raw = %(merchant_name_raw)s,
                merchant_name_normalized = %(merchant_name_normalized)s,
                notes = %(notes)s,
                currency = %(currency)s,
                subtotal_amount = %(subtotal_amount)s,
                tax_amount = %(tax_amount)s,
                fee_amount = %(fee_amount)s,
                discount_amount = %(discount_amount)s,
                tip_amount = %(tip_amount)s,
                deposit_amount = %(deposit_amount)s,
                rounding_amount = %(rounding_amount)s,
                total_amount = %(total_amount)s
            where id = %(transaction_id)s and user_id = %(user_id)s
            """,
            {
                "transaction_id": transaction_id,
                "user_id": self.user_id,
                "transaction_type": payload.transaction_type.value,
                "source_type": payload.source_type.value,
                "classification_mode": payload.classification_mode.value,
                "ingestion_method": payload.ingestion_method.value,
                "purchase_channel": payload.purchase_channel.value,
                "provider_key": payload.provider_key,
                "transaction_date": payload.transaction_date,
                "merchant_name_raw": payload.merchant_name_raw,
                "merchant_name_normalized": payload.merchant_name_normalized,
                "notes": payload.notes,
                "currency": payload.currency,
                "subtotal_amount": payload.subtotal_amount,
                "tax_amount": payload.tax_amount,
                "fee_amount": payload.fee_amount,
                "discount_amount": payload.discount_amount,
                "tip_amount": payload.tip_amount,
                "deposit_amount": payload.deposit_amount,
                "rounding_amount": payload.rounding_amount,
                "total_amount": payload.total_amount,
            },
        )

        if payload.receipt is not None or payload.source_type == SourceType.RECEIPT:
            receipt = payload.receipt
            self.conn.execute(
                """
                insert into receipts (
                    user_id, transaction_id, receipt_date, receipt_number, raw_payload
                )
                values (
                    %(user_id)s, %(transaction_id)s, %(receipt_date)s,
                    %(receipt_number)s, %(raw_payload)s
                )
                on conflict (transaction_id) do update
                set receipt_date = excluded.receipt_date,
                    receipt_number = excluded.receipt_number,
                    raw_payload = excluded.raw_payload
                """,
                {
                    "user_id": self.user_id,
                    "transaction_id": transaction_id,
                    "receipt_date": receipt.receipt_date if receipt else None,
                    "receipt_number": receipt.receipt_number if receipt else None,
                    "raw_payload": Jsonb(receipt.raw_payload if receipt else {}),
                },
            )

        self.conn.execute(
            """
            delete from transaction_adjustments
            where transaction_id = %(transaction_id)s and user_id = %(user_id)s
            """,
            {"transaction_id": transaction_id, "user_id": self.user_id},
        )
        self.conn.execute(
            """
            delete from transaction_items
            where transaction_id = %(transaction_id)s and user_id = %(user_id)s
            """,
            {"transaction_id": transaction_id, "user_id": self.user_id},
        )
        for item in payload.items:
            self.add_item(transaction_id, item)

        self.clear_validation_issues(transaction_id)
        self.touch_transaction(transaction_id)
        self.add_audit_event(
            "transaction",
            transaction_id,
            "confirmed_expense_corrected",
            {"reason": correction_reason},
        )
        return self.get_transaction(transaction_id)

    def acquire_mutation_lock(self, client_request_id: str) -> None:
        self.conn.execute(
            """
            select pg_advisory_xact_lock(
                hashtextextended(cast(%(user_id)s as text) || ':' || %(client_request_id)s, 0)
            )
            """,
            {"user_id": self.user_id, "client_request_id": client_request_id},
        )

    def get_mutation_result(self, client_request_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            select request_hash, transaction_id
            from expense_mutation_requests
            where user_id = %(user_id)s and client_request_id = %(client_request_id)s
            """,
            {"user_id": self.user_id, "client_request_id": client_request_id},
        ).fetchone()
        return dict(row) if row is not None else None

    def record_mutation_result(
        self,
        client_request_id: str,
        request_hash: str,
        transaction_id: UUID,
    ) -> None:
        self.conn.execute(
            """
            insert into expense_mutation_requests (
                user_id, client_request_id, request_hash, transaction_id
            )
            values (%(user_id)s, %(client_request_id)s, %(request_hash)s, %(transaction_id)s)
            """,
            {
                "user_id": self.user_id,
                "client_request_id": client_request_id,
                "request_hash": request_hash,
                "transaction_id": transaction_id,
            },
        )

    def update_transaction(self, transaction_id: UUID, payload: TransactionPatch) -> TransactionDetail:
        current = self.get_transaction(transaction_id)
        if current.status == TransactionStatus.VOID:
            raise ConflictError("Voided transactions cannot be edited")
        if current.status == TransactionStatus.CONFIRMED and not payload.correction_reason:
            raise ConflictError("Editing a confirmed transaction requires correction_reason")

        updates = payload.model_dump(exclude_unset=True, exclude={"correction_reason"})
        if updates:
            assignments = ", ".join(f"{field} = %({field})s" for field in updates)
            self.conn.execute(
                f"""
                update transactions
                set {assignments}
                where id = %(transaction_id)s and user_id = %(user_id)s
                """,
                {**updates, "transaction_id": transaction_id, "user_id": self.user_id},
            )
            if current.status == TransactionStatus.CONFIRMED:
                for field, value in updates.items():
                    self.add_correction(
                        transaction_id,
                        None,
                        field,
                        getattr(current, field),
                        value,
                        payload.correction_reason or "",
                    )

        self.clear_validation_issues(transaction_id)
        self.add_audit_event("transaction", transaction_id, "updated", {"fields": list(updates)})
        updated = self.get_transaction(transaction_id)
        if current.status == TransactionStatus.CONFIRMED and {
            "merchant_name_raw",
            "merchant_name_normalized",
        } & updates.keys():
            self.write_aliases_from_confirmed_items(transaction_id)
        return updated

    def add_item(self, transaction_id: UUID, payload: TransactionItemCreate) -> TransactionItem:
        transaction = self.get_transaction(transaction_id)
        if transaction.status == TransactionStatus.VOID:
            raise ConflictError("Voided transactions cannot be edited")
        taxonomy_key = payload.taxonomy_node_key or payload.category_slug
        if taxonomy_key is None:
            raise ValidationReferenceError("taxonomy_node_key is required")
        taxonomy_node_id = TaxonomyRepository(self.conn).resolve_assignable_node_id(
            taxonomy_key,
            transaction.transaction_type.value,
        )
        category_id = TaxonomyRepository(self.conn).legacy_category_id_for_node(taxonomy_node_id)
        concept_id, variant_id = self.validate_product_references(payload.concept_id, payload.variant_id)
        normalized_price = _normalized_price_fields(payload)
        row = self.conn.execute(
            """
            insert into transaction_items (
                user_id, transaction_id, raw_name, interpreted_name, normalized_name, brand,
                concept_id, variant_id, category_id, taxonomy_node_id,
                item_role, classification_source, classification_confidence,
                classification_review_status, classification_reviewed_at,
                quantity, unit,
                measured_value, measured_unit, package_value, package_unit,
                unit_price_amount, unit_price_basis_value, unit_price_basis_unit,
                normalized_unit, normalized_unit_price_amount, normalized_price_is_estimated,
                line_subtotal_amount,
                line_discount_amount, line_tax_amount, line_fee_amount, line_total_amount,
                confidence
            )
            values (
                %(user_id)s, %(transaction_id)s, %(raw_name)s, %(interpreted_name)s,
                %(normalized_name)s, %(brand)s, %(concept_id)s, %(variant_id)s, %(category_id)s,
                %(taxonomy_node_id)s, %(item_role)s, %(classification_source)s,
                %(classification_confidence)s, %(classification_review_status)s,
                %(classification_reviewed_at)s,
                %(quantity)s, %(unit)s,
                %(measured_value)s, %(measured_unit)s, %(package_value)s, %(package_unit)s,
                %(unit_price_amount)s, %(unit_price_basis_value)s, %(unit_price_basis_unit)s,
                %(normalized_unit)s, %(normalized_unit_price_amount)s,
                %(normalized_price_is_estimated)s,
                %(line_subtotal_amount)s, %(line_discount_amount)s,
                %(line_tax_amount)s, %(line_fee_amount)s, %(line_total_amount)s,
                %(confidence)s
            )
            returning id
            """,
            {
                "user_id": self.user_id,
                "transaction_id": transaction_id,
                "raw_name": payload.raw_name,
                "interpreted_name": payload.interpreted_name,
                "normalized_name": payload.normalized_name,
                "brand": payload.brand,
                "concept_id": concept_id,
                "variant_id": variant_id,
                "category_id": category_id,
                "taxonomy_node_id": taxonomy_node_id,
                "item_role": payload.item_role.value,
                "classification_source": payload.classification_source.value,
                "classification_confidence": payload.classification_confidence,
                "classification_review_status": payload.classification_review_status.value,
                "classification_reviewed_at": (
                    datetime.now(UTC)
                    if payload.classification_review_status.value == "reviewed"
                    else None
                ),
                "quantity": payload.quantity,
                "unit": payload.unit,
                "measured_value": payload.measured_value,
                "measured_unit": payload.measured_unit,
                "package_value": payload.package_value,
                "package_unit": payload.package_unit,
                "unit_price_amount": payload.unit_price_amount,
                "unit_price_basis_value": payload.unit_price_basis_value,
                "unit_price_basis_unit": payload.unit_price_basis_unit,
                **normalized_price,
                "line_subtotal_amount": payload.line_subtotal_amount,
                "line_discount_amount": payload.line_discount_amount,
                "line_tax_amount": payload.line_tax_amount,
                "line_fee_amount": payload.line_fee_amount,
                "line_total_amount": payload.line_total_amount,
                "confidence": payload.confidence,
            },
        ).fetchone()
        self.replace_item_themes(row["id"], payload.theme_slugs)
        self.replace_item_facets(
            row["id"],
            payload.facet_value_keys,
            source=payload.classification_source.value,
            confidence=payload.classification_confidence,
        )
        self.touch_transaction(transaction_id)
        self.clear_validation_issues(transaction_id)
        self.add_audit_event("transaction_item", row["id"], "created", {"transaction_id": str(transaction_id)})
        return self.get_item(transaction_id, row["id"])

    def update_item(
        self,
        transaction_id: UUID,
        item_id: UUID,
        payload: TransactionItemUpdate,
    ) -> TransactionItem:
        transaction = self.get_transaction(transaction_id)
        if transaction.status == TransactionStatus.VOID:
            raise ConflictError("Voided transactions cannot be edited")
        if transaction.status == TransactionStatus.CONFIRMED and not payload.correction_reason:
            raise ConflictError("Editing a confirmed item requires correction_reason")
        current = self.get_item(transaction_id, item_id)

        updates = payload.model_dump(
            exclude_unset=True,
            exclude={
                "category_slug",
                "taxonomy_node_key",
                "theme_slugs",
                "facet_value_keys",
                "correction_reason",
            },
        )
        for enum_field in {
            "item_role",
            "classification_source",
            "classification_review_status",
        }:
            value = updates.get(enum_field)
            if value is not None:
                updates[enum_field] = value.value
        if "classification_review_status" in updates:
            updates["classification_reviewed_at"] = (
                datetime.now(UTC)
                if updates["classification_review_status"] == "reviewed"
                else None
            )
        reference_fields = {"concept_id", "variant_id"} & payload.model_fields_set
        if reference_fields:
            requested_concept = payload.concept_id if "concept_id" in payload.model_fields_set else current.concept_id
            requested_variant = payload.variant_id if "variant_id" in payload.model_fields_set else current.variant_id
            concept_id, variant_id = self.validate_product_references(requested_concept, requested_variant)
            updates["concept_id"] = concept_id
            updates["variant_id"] = variant_id
        requested_taxonomy_key = payload.taxonomy_node_key or payload.category_slug
        if requested_taxonomy_key is not None:
            taxonomy_node_id = TaxonomyRepository(self.conn).resolve_assignable_node_id(
                requested_taxonomy_key,
                transaction.transaction_type.value,
            )
            updates["taxonomy_node_id"] = taxonomy_node_id
            updates["category_id"] = TaxonomyRepository(self.conn).legacy_category_id_for_node(
                taxonomy_node_id
            )
        if PRICE_INPUT_FIELDS & updates.keys():
            merged = current.model_copy(update=updates)
            updates.update(_normalized_price_fields(merged))
        if updates:
            assignments = ", ".join(f"{field} = %({field})s" for field in updates)
            self.conn.execute(
                f"""
                update transaction_items
                set {assignments}
                where id = %(item_id)s
                  and transaction_id = %(transaction_id)s
                  and user_id = %(user_id)s
                """,
                {
                    **updates,
                    "item_id": item_id,
                    "transaction_id": transaction_id,
                    "user_id": self.user_id,
                },
            )
            if transaction.status == TransactionStatus.CONFIRMED:
                for field, value in updates.items():
                    self.add_correction(
                        transaction_id,
                        item_id,
                        field,
                        getattr(current, field, None),
                        value,
                        payload.correction_reason or "",
                    )
        if payload.theme_slugs is not None:
            self.replace_item_themes(item_id, payload.theme_slugs)
        if payload.facet_value_keys is not None:
            self.replace_item_facets(
                item_id,
                payload.facet_value_keys,
                source=(
                    payload.classification_source.value
                    if payload.classification_source is not None
                    else current.classification_source.value
                ),
                confidence=(
                    payload.classification_confidence
                    if "classification_confidence" in payload.model_fields_set
                    else current.classification_confidence
                ),
            )
        self.touch_transaction(transaction_id)
        self.clear_validation_issues(transaction_id)
        self.add_audit_event("transaction_item", item_id, "updated", {"transaction_id": str(transaction_id)})
        updated = self.get_item(transaction_id, item_id)
        if transaction.status == TransactionStatus.CONFIRMED and (
            {"raw_name", "interpreted_name", "normalized_name", "category_id", "concept_id", "variant_id"}
            & updates.keys()
        ):
            self.write_alias_for_confirmed_item(transaction, updated)
        return updated

    def delete_item(self, transaction_id: UUID, item_id: UUID) -> None:
        transaction = self.get_transaction(transaction_id)
        if transaction.status != TransactionStatus.DRAFT:
            raise ConflictError("Only draft items can be deleted without correction workflow")
        result = self.conn.execute(
            """
            delete from transaction_items
            where id = %(item_id)s and transaction_id = %(transaction_id)s and user_id = %(user_id)s
            """,
            {"item_id": item_id, "transaction_id": transaction_id, "user_id": self.user_id},
        )
        if result.rowcount == 0:
            raise NotFoundError("Item not found")
        self.touch_transaction(transaction_id)
        self.clear_validation_issues(transaction_id)
        self.add_audit_event("transaction_item", item_id, "deleted", {"transaction_id": str(transaction_id)})

    def void_transaction(self, transaction_id: UUID) -> None:
        result = self.conn.execute(
            """
            update transactions
            set status = 'void'
            where id = %(transaction_id)s and user_id = %(user_id)s
            """,
            {"transaction_id": transaction_id, "user_id": self.user_id},
        )
        if result.rowcount == 0:
            raise NotFoundError("Transaction not found")
        self.add_audit_event("transaction", transaction_id, "voided", {})

    def set_validation_result(
        self,
        transaction_id: UUID,
        delta: Decimal | None,
        issues: list[ValidationIssue],
    ) -> list[ValidationIssue]:
        self.clear_validation_issues(transaction_id)
        self.conn.execute(
            """
            update transactions
            set reconciliation_delta_amount = %(delta)s
            where id = %(transaction_id)s and user_id = %(user_id)s
            """,
            {"delta": delta, "transaction_id": transaction_id, "user_id": self.user_id},
        )
        persisted: list[ValidationIssue] = []
        for candidate in issues:
            row = self.conn.execute(
                """
                insert into validation_issues (
                    user_id, transaction_id, item_id, severity, code, message, metadata
                )
                values (
                    %(user_id)s, %(transaction_id)s, %(item_id)s, %(severity)s,
                    %(code)s, %(message)s, %(metadata)s
                )
                returning id
                """,
                {
                    "user_id": self.user_id,
                    "transaction_id": transaction_id,
                    "item_id": candidate.item_id,
                    "severity": candidate.severity.value,
                    "code": candidate.code,
                    "message": candidate.message,
                    "metadata": Jsonb(candidate.metadata),
                },
            ).fetchone()
            persisted.append(candidate.model_copy(update={"id": row["id"], "transaction_id": transaction_id}))
        return persisted

    def confirm_transaction(self, transaction_id: UUID) -> TransactionDetail:
        current = self.get_transaction(transaction_id)
        if current.status == TransactionStatus.CONFIRMED:
            return current
        if current.status == TransactionStatus.VOID:
            raise ConflictError("Voided transactions cannot be confirmed")
        # Explicit transaction approval is also the user's review of every
        # non-blocking semantic classification in that transaction. Preserve
        # the original classification_source while recording the review event.
        self.conn.execute(
            """
            update transaction_items
            set classification_review_status = 'reviewed',
                classification_reviewed_at = now()
            where transaction_id = %(transaction_id)s
              and user_id = %(user_id)s
              and classification_review_status <> 'reviewed'
            """,
            {"transaction_id": transaction_id, "user_id": self.user_id},
        )
        result = self.conn.execute(
            """
            update transactions
            set status = 'confirmed', confirmed_at = now()
            where id = %(transaction_id)s and user_id = %(user_id)s and status = 'draft'
            """,
            {"transaction_id": transaction_id, "user_id": self.user_id},
        )
        if result.rowcount == 0:
            raise NotFoundError("Transaction not found")
        self.write_aliases_from_confirmed_items(transaction_id)
        self.add_audit_event("transaction", transaction_id, "confirmed", {})
        return self.get_transaction(transaction_id)

    def resolve_aliases(
        self,
        merchant_normalized: str | None,
        items: list[AliasResolveItem],
    ) -> list[AliasResolution]:
        resolutions: list[AliasResolution] = []
        for item in items:
            normalized = normalize_lookup_text(item.raw_name)
            row = None
            if merchant_normalized:
                row = self.conn.execute(
                    """
                    select a.source, a.category_id, c.slug as category_slug,
                           a.taxonomy_node_id, node.stable_key as taxonomy_node_key,
                           a.concept_id, a.variant_id
                    from user_product_aliases a
                    left join categories c on c.id = a.category_id
                    left join taxonomy_nodes node on node.id = a.taxonomy_node_id
                    where a.user_id = %(user_id)s
                      and a.raw_name_normalized = %(raw_name)s
                      and a.merchant_normalized = %(merchant)s
                      and a.source = 'user_merchant'
                    limit 1
                    """,
                    {"user_id": self.user_id, "raw_name": normalized, "merchant": merchant_normalized},
                ).fetchone()
            if row is None:
                row = self.conn.execute(
                    """
                    select a.source, a.category_id, c.slug as category_slug,
                           a.taxonomy_node_id, node.stable_key as taxonomy_node_key,
                           a.concept_id, a.variant_id
                    from user_product_aliases a
                    left join categories c on c.id = a.category_id
                    left join taxonomy_nodes node on node.id = a.taxonomy_node_id
                    where a.user_id = %(user_id)s
                      and a.raw_name_normalized = %(raw_name)s
                      and a.merchant_id is null
                      and a.merchant_normalized is null
                      and a.source = 'user_global'
                    limit 1
                    """,
                    {"user_id": self.user_id, "raw_name": normalized},
                ).fetchone()

            resolutions.append(
                AliasResolution(
                    raw_name=item.raw_name,
                    raw_name_normalized=normalized,
                    source=row["source"] if row else None,
                    category_id=row["category_id"] if row else None,
                    category_slug=row["category_slug"] if row else None,
                    taxonomy_node_id=row.get("taxonomy_node_id") if row else None,
                    taxonomy_node_key=row.get("taxonomy_node_key") if row else None,
                    concept_id=row["concept_id"] if row else None,
                    variant_id=row["variant_id"] if row else None,
                    unresolved=row is None,
                )
            )
        return resolutions

    def add_adjustment(self, transaction_id: UUID, payload: TransactionAdjustmentCreate) -> TransactionAdjustment:
        transaction = self.get_transaction(transaction_id)
        if transaction.status == TransactionStatus.VOID:
            raise ConflictError("Voided transactions cannot be edited")
        if transaction.status == TransactionStatus.CONFIRMED and not payload.correction_reason:
            raise ConflictError("Editing a confirmed transaction requires correction_reason")
        if payload.item_id is not None:
            self.get_item(transaction_id, payload.item_id)
        row = self.conn.execute(
            """
            insert into transaction_adjustments (
                user_id, transaction_id, item_id, type, subtype, amount, description,
                raw_label, affects_total, metadata
            )
            values (
                %(user_id)s, %(transaction_id)s, %(item_id)s, %(type)s, %(subtype)s,
                %(amount)s, %(description)s, %(raw_label)s, %(affects_total)s, %(metadata)s
            )
            returning id
            """,
            {
                "user_id": self.user_id,
                "transaction_id": transaction_id,
                "item_id": payload.item_id,
                "type": payload.type.value,
                "subtype": payload.subtype.value if payload.subtype is not None else None,
                "amount": payload.amount,
                "description": payload.description,
                "raw_label": payload.raw_label,
                "affects_total": payload.affects_total,
                "metadata": Jsonb(payload.metadata),
            },
        ).fetchone()
        created = TransactionAdjustment(
            id=row["id"],
            **payload.model_dump(exclude={"correction_reason"}),
        )
        if transaction.status == TransactionStatus.CONFIRMED:
            self.add_correction(
                transaction_id,
                payload.item_id,
                "adjustment",
                None,
                created.model_dump(mode="json"),
                payload.correction_reason or "",
            )
        self.touch_transaction(transaction_id)
        self.clear_validation_issues(transaction_id)
        self.add_audit_event(
            "transaction_adjustment",
            created.id,
            "created",
            {"transaction_id": str(transaction_id)},
        )
        return created

    def update_adjustment(
        self,
        transaction_id: UUID,
        adjustment_id: UUID,
        payload: TransactionAdjustmentUpdate,
    ) -> TransactionAdjustment:
        transaction = self.get_transaction(transaction_id)
        if transaction.status == TransactionStatus.VOID:
            raise ConflictError("Voided transactions cannot be edited")
        if transaction.status == TransactionStatus.CONFIRMED and not payload.correction_reason:
            raise ConflictError("Editing a confirmed transaction requires correction_reason")
        current = self.get_adjustment(transaction_id, adjustment_id)
        updates = payload.model_dump(exclude_unset=True, exclude={"correction_reason"})
        if "type" in updates and updates["type"] is not None:
            updates["type"] = updates["type"].value
        if "subtype" in updates and updates["subtype"] is not None:
            updates["subtype"] = updates["subtype"].value
        if "metadata" in updates and updates["metadata"] is not None:
            updates["metadata"] = Jsonb(updates["metadata"])
        if "item_id" in updates and updates["item_id"] is not None:
            self.get_item(transaction_id, updates["item_id"])
        TransactionAdjustmentCreate(
            item_id=updates.get("item_id", current.item_id),
            type=updates.get("type", current.type),
            subtype=updates.get("subtype", current.subtype),
            amount=updates.get("amount", current.amount),
            description=updates.get("description", current.description),
            raw_label=updates.get("raw_label", current.raw_label),
            affects_total=updates.get("affects_total", current.affects_total),
            metadata=payload.metadata if "metadata" in payload.model_fields_set else current.metadata,
            correction_reason=payload.correction_reason,
        )
        if updates:
            assignments = ", ".join(f"{field} = %({field})s" for field in updates)
            self.conn.execute(
                f"""
                update transaction_adjustments
                set {assignments}
                where id = %(adjustment_id)s
                  and transaction_id = %(transaction_id)s
                  and user_id = %(user_id)s
                """,
                {
                    **updates,
                    "adjustment_id": adjustment_id,
                    "transaction_id": transaction_id,
                    "user_id": self.user_id,
                },
            )
            if transaction.status == TransactionStatus.CONFIRMED:
                self.add_correction(
                    transaction_id,
                    current.item_id,
                    "adjustment",
                    current.model_dump(mode="json"),
                    updates,
                    payload.correction_reason or "",
                )
        self.touch_transaction(transaction_id)
        self.clear_validation_issues(transaction_id)
        self.add_audit_event(
            "transaction_adjustment",
            adjustment_id,
            "updated",
            {"transaction_id": str(transaction_id), "fields": list(updates)},
        )
        return self.get_adjustment(transaction_id, adjustment_id)

    def delete_adjustment(
        self,
        transaction_id: UUID,
        adjustment_id: UUID,
        correction_reason: str | None = None,
    ) -> None:
        transaction = self.get_transaction(transaction_id)
        if transaction.status == TransactionStatus.VOID:
            raise ConflictError("Voided transactions cannot be edited")
        if transaction.status == TransactionStatus.CONFIRMED and not correction_reason:
            raise ConflictError("Editing a confirmed transaction requires correction_reason")
        current = self.get_adjustment(transaction_id, adjustment_id)
        result = self.conn.execute(
            """
            delete from transaction_adjustments
            where id = %(adjustment_id)s
              and transaction_id = %(transaction_id)s
              and user_id = %(user_id)s
            """,
            {
                "adjustment_id": adjustment_id,
                "transaction_id": transaction_id,
                "user_id": self.user_id,
            },
        )
        if result.rowcount == 0:
            raise NotFoundError("Adjustment not found")
        if transaction.status == TransactionStatus.CONFIRMED:
            self.add_correction(
                transaction_id,
                current.item_id,
                "adjustment",
                current.model_dump(mode="json"),
                None,
                correction_reason or "",
            )
        self.touch_transaction(transaction_id)
        self.clear_validation_issues(transaction_id)
        self.add_audit_event(
            "transaction_adjustment",
            adjustment_id,
            "deleted",
            {"transaction_id": str(transaction_id)},
        )

    def category_id_for_slug(self, slug: str) -> UUID:
        row = self.conn.execute(
            """
            select id
            from categories
            where slug = %(slug)s
              and is_active = true
              and not exists (
                  select 1
                  from categories child
                  where child.parent_id = categories.id
                    and child.is_active = true
              )
            """,
            {"slug": slug},
        ).fetchone()
        if row is None:
            raise ValidationReferenceError(f"Unknown, inactive, or non-assignable category slug: {slug}")
        return cast(UUID, row["id"])

    def validate_product_references(
        self,
        concept_id: UUID | None,
        variant_id: UUID | None,
    ) -> tuple[UUID | None, UUID | None]:
        if concept_id is not None:
            concept = self.conn.execute(
                """
                select id
                from product_concepts
                where id = %(concept_id)s
                  and (owner_user_id is null or owner_user_id = %(user_id)s)
                """,
                {"concept_id": concept_id, "user_id": self.user_id},
            ).fetchone()
            if concept is None:
                raise ValidationReferenceError("Unknown or inaccessible product concept")
        if variant_id is None:
            return concept_id, None

        variant = self.conn.execute(
            """
            select id, concept_id
            from product_variants
            where id = %(variant_id)s
              and (owner_user_id is null or owner_user_id = %(user_id)s)
            """,
            {"variant_id": variant_id, "user_id": self.user_id},
        ).fetchone()
        if variant is None:
            raise ValidationReferenceError("Unknown or inaccessible product variant")
        if concept_id is not None and variant["concept_id"] != concept_id:
            raise ValidationReferenceError("Product variant does not belong to the selected concept")
        return cast(UUID, variant["concept_id"]), variant_id

    def theme_ids_for_slugs(self, slugs: list[str]) -> dict[str, UUID]:
        if not slugs:
            return {}
        rows = self.conn.execute(
            "select slug, id from themes where slug = any(%(slugs)s) and is_active = true",
            {"slugs": slugs},
        ).fetchall()
        found = {row["slug"]: row["id"] for row in rows}
        missing = sorted(set(slugs) - set(found))
        if missing:
            raise ValidationReferenceError(f"Unknown or inactive theme slugs: {', '.join(missing)}")
        return found

    def list_items(self, transaction_id: UUID) -> list[TransactionItem]:
        rows = self.conn.execute(
            """
            select i.id, i.raw_name, i.interpreted_name, i.normalized_name,
                   i.concept_id, i.variant_id, pc.canonical_name as concept_name,
                   pv.canonical_name as variant_name, i.brand, pv.size_text,
                   i.category_id, c.slug as category_slug,
                   i.taxonomy_node_id, node.stable_key as taxonomy_node_key,
                   node.name as taxonomy_node_name, version.version as taxonomy_version,
                   coalesce((
                       select jsonb_agg(
                           jsonb_build_object(
                               'id', ancestor.id,
                               'stable_key', ancestor.stable_key,
                               'level', ancestor.level,
                               'level_name', version.level_names ->> (ancestor.level - 1),
                               'name', ancestor.name
                           )
                           order by ancestor.level
                       )
                       from taxonomy_node_closure path
                       join taxonomy_nodes ancestor on ancestor.id = path.ancestor_id
                       where path.version_id = node.version_id
                         and path.descendant_id = node.id
                   ), '[]'::jsonb) as taxonomy_path,
                   i.item_role, i.classification_source, i.classification_confidence,
                   i.classification_review_status, i.classification_reviewed_at,
                   i.quantity, i.unit,
                   i.measured_value, i.measured_unit, i.package_value, i.package_unit,
                   i.unit_price_amount, i.unit_price_basis_value, i.unit_price_basis_unit,
                   i.normalized_unit, i.normalized_unit_price_amount,
                   i.normalized_price_is_estimated,
                   i.line_subtotal_amount, i.line_discount_amount,
                   i.line_tax_amount, i.line_fee_amount, i.line_total_amount, i.confidence
            from transaction_items i
            join taxonomy_nodes node on node.id = i.taxonomy_node_id
            join taxonomy_versions version on version.id = node.version_id
            left join categories c on c.id = i.category_id
            left join product_concepts pc on pc.id = i.concept_id
            left join product_variants pv on pv.id = i.variant_id
            where i.transaction_id = %(transaction_id)s and i.user_id = %(user_id)s
            order by i.created_at, i.id
            """,
            {"transaction_id": transaction_id, "user_id": self.user_id},
        ).fetchall()
        return [
            TransactionItem(
                **row,
                theme_slugs=self.theme_slugs_for_item(row["id"]),
                facet_value_keys=self.facet_value_keys_for_item(row["id"]),
            )
            for row in rows
        ]

    def get_item(self, transaction_id: UUID, item_id: UUID) -> TransactionItem:
        for item in self.list_items(transaction_id):
            if item.id == item_id:
                return item
        raise NotFoundError("Item not found")

    def list_adjustments(self, transaction_id: UUID) -> list[TransactionAdjustment]:
        rows = self.conn.execute(
            """
            select id, item_id, type, subtype, amount, description,
                   raw_label, affects_total, metadata
            from transaction_adjustments
            where transaction_id = %(transaction_id)s and user_id = %(user_id)s
            order by created_at, id
            """,
            {"transaction_id": transaction_id, "user_id": self.user_id},
        ).fetchall()
        return [TransactionAdjustment.model_validate(row) for row in rows]

    def get_adjustment(self, transaction_id: UUID, adjustment_id: UUID) -> TransactionAdjustment:
        row = self.conn.execute(
            """
            select id, item_id, type, subtype, amount, description,
                   raw_label, affects_total, metadata
            from transaction_adjustments
            where id = %(adjustment_id)s
              and transaction_id = %(transaction_id)s
              and user_id = %(user_id)s
            """,
            {
                "adjustment_id": adjustment_id,
                "transaction_id": transaction_id,
                "user_id": self.user_id,
            },
        ).fetchone()
        if row is None:
            raise NotFoundError("Adjustment not found")
        return TransactionAdjustment.model_validate(row)

    def list_validation_issues(self, transaction_id: UUID) -> list[ValidationIssue]:
        rows = self.conn.execute(
            """
            select id, transaction_id, item_id, severity, code, message, metadata
            from validation_issues
            where transaction_id = %(transaction_id)s
              and user_id = %(user_id)s
              and resolved_at is null
            order by created_at, id
            """,
            {"transaction_id": transaction_id, "user_id": self.user_id},
        ).fetchall()
        return [ValidationIssue.model_validate(row) for row in rows]

    def clear_validation_issues(self, transaction_id: UUID) -> None:
        self.conn.execute(
            """
            delete from validation_issues
            where transaction_id = %(transaction_id)s and user_id = %(user_id)s
            """,
            {"transaction_id": transaction_id, "user_id": self.user_id},
        )

    def touch_transaction(self, transaction_id: UUID) -> None:
        self.conn.execute(
            """
            update transactions
            set updated_at = now()
            where id = %(transaction_id)s and user_id = %(user_id)s
            """,
            {"transaction_id": transaction_id, "user_id": self.user_id},
        )

    def replace_item_themes(self, item_id: UUID, theme_slugs: list[str]) -> None:
        theme_ids = self.theme_ids_for_slugs(theme_slugs)
        self.conn.execute(
            "delete from transaction_item_themes where item_id = %(item_id)s and user_id = %(user_id)s",
            {"item_id": item_id, "user_id": self.user_id},
        )
        for theme_id in theme_ids.values():
            self.conn.execute(
                """
                insert into transaction_item_themes (user_id, item_id, theme_id)
                values (%(user_id)s, %(item_id)s, %(theme_id)s)
                """,
                {"user_id": self.user_id, "item_id": item_id, "theme_id": theme_id},
            )

    def replace_item_facets(
        self,
        item_id: UUID,
        stable_keys: list[str],
        *,
        source: str,
        confidence: Decimal | None,
    ) -> None:
        value_ids = TaxonomyRepository(self.conn).facet_value_ids(stable_keys)
        self.conn.execute(
            "delete from transaction_item_facets where item_id = %(item_id)s and user_id = %(user_id)s",
            {"item_id": item_id, "user_id": self.user_id},
        )
        for value_id in value_ids.values():
            self.conn.execute(
                """
                insert into transaction_item_facets (
                    user_id, item_id, facet_value_id, source, confidence
                )
                values (
                    %(user_id)s, %(item_id)s, %(facet_value_id)s,
                    %(source)s, %(confidence)s
                )
                """,
                {
                    "user_id": self.user_id,
                    "item_id": item_id,
                    "facet_value_id": value_id,
                    "source": source,
                    "confidence": confidence,
                },
            )

    def facet_value_keys_for_item(self, item_id: UUID) -> list[str]:
        rows = self.conn.execute(
            """
            select value.stable_key
            from transaction_item_facets item_facet
            join taxonomy_facet_values value on value.id = item_facet.facet_value_id
            where item_facet.item_id = %(item_id)s
              and item_facet.user_id = %(user_id)s
            order by value.stable_key
            """,
            {"item_id": item_id, "user_id": self.user_id},
        ).fetchall()
        return [cast(str, row["stable_key"]) for row in rows]

    def theme_slugs_for_item(self, item_id: UUID) -> list[str]:
        rows = self.conn.execute(
            """
            select t.slug
            from transaction_item_themes it
            join themes t on t.id = it.theme_id
            where it.item_id = %(item_id)s and it.user_id = %(user_id)s
            order by t.slug
            """,
            {"item_id": item_id, "user_id": self.user_id},
        ).fetchall()
        return [row["slug"] for row in rows]

    def add_correction(
        self,
        transaction_id: UUID,
        item_id: UUID | None,
        field_name: str,
        old_value: object,
        new_value: object,
        reason: str,
    ) -> None:
        self.conn.execute(
            """
            insert into user_corrections (
                user_id, transaction_id, item_id, field_name, old_value, new_value
            )
            values (%(user_id)s, %(transaction_id)s, %(item_id)s, %(field_name)s, %(old_value)s, %(new_value)s)
            """,
            {
                "user_id": self.user_id,
                "transaction_id": transaction_id,
                "item_id": item_id,
                "field_name": field_name,
                "old_value": Jsonb({"value": str(old_value), "reason": reason}),
                "new_value": Jsonb({"value": str(new_value)}),
            },
        )
        self.add_audit_event("transaction", transaction_id, "corrected", {"field": field_name})

    def add_audit_event(
        self,
        entity_type: str,
        entity_id: UUID,
        action: str,
        metadata: dict[str, Any],
    ) -> None:
        self.conn.execute(
            """
            insert into audit_events (user_id, entity_type, entity_id, action, metadata)
            values (%(user_id)s, %(entity_type)s, %(entity_id)s, %(action)s, %(metadata)s)
            """,
            {
                "user_id": self.user_id,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "action": action,
                "metadata": Jsonb(metadata),
            },
        )

    def write_aliases_from_confirmed_items(self, transaction_id: UUID) -> None:
        transaction = self.get_transaction(transaction_id)
        for item in transaction.items:
            self.write_alias_for_confirmed_item(transaction, item)

    def write_alias_for_confirmed_item(
        self,
        transaction: TransactionDetail,
        item: TransactionItem,
    ) -> None:
        source_name = item.raw_name or item.interpreted_name or item.normalized_name
        if not source_name:
            return
        normalized = normalize_lookup_text(source_name)
        params = {
            "user_id": self.user_id,
            "raw_name": normalized,
            "category_id": item.category_id,
            "taxonomy_node_id": item.taxonomy_node_id,
            "concept_id": item.concept_id,
            "variant_id": item.variant_id,
        }
        if transaction.merchant_name_normalized:
            self.conn.execute(
                """
                insert into user_product_aliases (
                    user_id, merchant_normalized, raw_name_normalized, category_id, taxonomy_node_id,
                    concept_id, variant_id, source, confirmed_count
                )
                values (
                    %(user_id)s, %(merchant)s, %(raw_name)s, %(category_id)s, %(taxonomy_node_id)s,
                    %(concept_id)s, %(variant_id)s, 'user_merchant', 1
                )
                on conflict (user_id, merchant_normalized, raw_name_normalized)
                where merchant_id is null and merchant_normalized is not null
                do update set
                    category_id = excluded.category_id,
                    taxonomy_node_id = excluded.taxonomy_node_id,
                    concept_id = excluded.concept_id,
                    variant_id = excluded.variant_id,
                    confirmed_count = user_product_aliases.confirmed_count + 1,
                    updated_at = now()
                """,
                {**params, "merchant": transaction.merchant_name_normalized},
            )
        self.conn.execute(
            """
            insert into user_product_aliases (
                user_id, raw_name_normalized, category_id, taxonomy_node_id, concept_id, variant_id,
                source, confirmed_count
            )
            values (
                %(user_id)s, %(raw_name)s, %(category_id)s, %(taxonomy_node_id)s, %(concept_id)s,
                %(variant_id)s, 'user_global', 1
            )
            on conflict (user_id, raw_name_normalized)
            where merchant_id is null and merchant_normalized is null
            do update set
                category_id = excluded.category_id,
                taxonomy_node_id = excluded.taxonomy_node_id,
                concept_id = excluded.concept_id,
                variant_id = excluded.variant_id,
                confirmed_count = user_product_aliases.confirmed_count + 1,
                updated_at = now()
            """,
            params,
        )
