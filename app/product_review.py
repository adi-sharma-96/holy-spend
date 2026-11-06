"""Revision-bound, owner-scoped product evidence review and correction."""

import json
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from types import SimpleNamespace
from typing import Any, Literal
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.errors import ConflictError, NotFoundError
from app.product_evidence import ItemEvidence, readiness_reasons
from app.repositories import TaxonomyRepository, _normalized_price_fields

PATCH_FIELDS = frozenset(
    {
        "product_identity_key", "product_type_key", "brand", "quantity", "unit",
        "measured_value", "measured_unit", "package_value", "package_unit",
    }
)
SNAPSHOT_FIELDS = (*sorted(PATCH_FIELDS), "field_provenance", "normalized_unit",
                   "normalized_unit_price_amount", "normalized_price_is_estimated",
                   "taxonomy_node_id", "classification_source", "classification_review_status",
                   "classification_reviewed_at")


class ReviewPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_identity_key: str | None = Field(default=None, max_length=200)
    product_type_key: str | None = Field(default=None, max_length=200)
    taxonomy_node_key: str | None = Field(default=None, max_length=250)
    brand: str | None = Field(default=None, max_length=200)
    quantity: Decimal | None = Field(default=None, gt=0)
    unit: str | None = None
    measured_value: Decimal | None = Field(default=None, gt=0)
    measured_unit: str | None = None
    package_value: Decimal | None = Field(default=None, gt=0)
    package_unit: str | None = None
    confirm_fields: list[Literal[
        "identity", "product_type", "brand", "quantity", "package_size", "package_count", "measured_value"
    ]] = Field(default_factory=list)

    @model_validator(mode="after")
    def paired_measurements(self) -> "ReviewPatch":
        for value, unit in (("measured_value", "measured_unit"), ("package_value", "package_unit")):
            supplied = self.model_fields_set & {value, unit}
            if supplied and supplied != {value, unit}:
                raise ValueError(f"{value} and {unit} must be reviewed together")
        return self


def _json_value(value: Any) -> Any:
    if isinstance(value, (Decimal, UUID, datetime)):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_value(inner) for key, inner in value.items()}
    return value


def _database_value(field: str, value: Any) -> Any:
    if field == "field_provenance":
        return Jsonb(value)
    if field in {"quantity", "measured_value", "package_value", "normalized_unit_price_amount"}:
        return Decimal(value) if value is not None else None
    if field == "classification_reviewed_at":
        return datetime.fromisoformat(value) if value is not None else None
    if field == "taxonomy_node_id":
        return UUID(value) if value is not None else None
    return value


def _request_hash(request: BaseModel) -> str:
    payload = request.model_dump(mode="json", exclude={"operation_id"})
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class ReviewPreviewRequest(BaseModel):
    item_id: UUID
    scope: Literal["item", "confirmed_identity"] = "item"
    patch: ReviewPatch
    operation_id: UUID | None = None


class ReviewPreview(BaseModel):
    item_id: UUID
    scope: Literal["item", "confirmed_identity"]
    operation_id: UUID
    affected: list[dict[str, Any]]
    affected_count: int


class ReviewDecisionRequest(ReviewPreviewRequest):
    operation_id: UUID
    decision: Literal["confirmed", "rejected", "deferred"]
    reason: str = Field(min_length=3, max_length=500)
    expected_revisions: dict[UUID, int]


class ReviewDecisionResult(BaseModel):
    operation_id: UUID
    decision: str
    affected_count: int
    idempotent_replay: bool = False


class ReviewReverseRequest(BaseModel):
    event_id: UUID
    operation_id: UUID
    reason: str = Field(min_length=3, max_length=500)


class ProductReviewRepository:
    def __init__(self, conn: Any, user_id: UUID) -> None:
        self.conn = conn
        self.user_id = user_id

    def _item(self, item_id: UUID, *, lock: bool = False) -> dict[str, Any]:
        if lock:
            parent = self.conn.execute(
                "select transaction_id from transaction_items where id=%(id)s and user_id=%(user_id)s",
                {"id": item_id, "user_id": self.user_id},
            ).fetchone()
            if parent is None:
                raise NotFoundError("Review item not found")
            self.conn.execute(
                "select id from transactions where id=%(id)s and user_id=%(user_id)s for update",
                {"id": parent["transaction_id"], "user_id": self.user_id},
            )
        row = self.conn.execute(
            """
            select i.*, t.status, t.currency, t.transaction_date,
                   coalesce(t.merchant_name_normalized, t.merchant_name_raw) as merchant,
                   node.stable_key as taxonomy_key,
                   exists(select 1 from transaction_adjustments a
                          where a.item_id = i.id and a.type = 'refund') as has_refund
            from transaction_items i
            join transactions t on t.id = i.transaction_id and t.user_id = i.user_id
            left join taxonomy_nodes node on node.id = i.taxonomy_node_id
            where i.id = %(item_id)s and i.user_id = %(user_id)s
            """ + (" for update of i" if lock else ""),
            {"item_id": item_id, "user_id": self.user_id},
        ).fetchone()
        if row is None:
            raise NotFoundError("Review item not found")
        return dict(row)

    def queue(self, *, limit: int = 50, include_suppressed: bool = False) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            select i.id, i.raw_name, i.normalized_name, i.brand, i.product_identity_key,
                   i.product_type_key, i.field_provenance, i.evidence_revision,
                   i.quantity, i.unit, i.package_value, i.package_unit,
                   i.measured_value, i.measured_unit, i.normalized_unit,
                   i.normalized_unit_price_amount, i.normalized_price_is_estimated,
                   i.unit_price_amount, i.unit_price_basis_value, i.line_total_amount,
                   i.classification_review_status, node.stable_key as taxonomy_key,
                   t.currency, t.transaction_date, t.id as transaction_id,
                   coalesce(t.merchant_name_normalized, t.merchant_name_raw) as merchant,
                   exists(select 1 from transaction_adjustments a
                          where a.item_id = i.id and a.type = 'refund') as has_refund,
                   (select n.status from nutrition_lookups n
                    where n.owner_user_id = i.user_id and n.product_name = i.normalized_name
                      and n.brand is not distinct from i.brand
                    order by n.updated_at desc limit 1) as nutrition_status,
                   (select count(distinct coalesce(a.variant_id::text, a.concept_id::text,
                                                    a.taxonomy_node_id::text, a.category_id::text))
                    from user_product_aliases a
                    where a.user_id = i.user_id and a.raw_name_normalized = lower(trim(i.raw_name))
                   ) as alias_targets,
                   count(*) over (partition by i.normalized_name, i.brand) as repeat_count,
                   latest_review.decision as review_decision
            from transaction_items i
            join transactions t on t.id = i.transaction_id and t.user_id = i.user_id
            left join taxonomy_nodes node on node.id = i.taxonomy_node_id
            left join lateral (
                select d.decision from product_review_decisions d
                where d.user_id = i.user_id and d.item_id = i.id
                  and d.issue_key = 'product_data'
                  and d.evidence_revision = i.evidence_revision
                order by d.created_at desc, d.id desc limit 1
            ) latest_review on true
            where i.user_id = %(user_id)s and t.status = 'confirmed'
              and t.transaction_type = 'expense' and i.item_role = 'purchase'
              and (%(include_suppressed)s or latest_review.decision is null
                   or latest_review.decision not in ('rejected', 'deferred'))
            """,
            {"user_id": self.user_id, "include_suppressed": include_suppressed},
        ).fetchall()
        results = []
        for raw in rows:
            row = dict(raw)
            reasons = list(readiness_reasons(row))
            if row["classification_review_status"] != "reviewed":
                reasons.append("taxonomy_needs_review")
            if row["taxonomy_key"] is None or row["taxonomy_key"].startswith("unclassified."):
                reasons.append("broad_taxonomy")
            if row["nutrition_status"] in {"no_match", "error"}:
                reasons.append("nutrition_match_needs_review")
            if row["alias_targets"] > 1:
                reasons.append("conflicting_aliases")
            if not reasons:
                continue
            row["reasons"] = reasons
            row["priority"] = float(abs(row["line_total_amount"])) * (1 + min(row["repeat_count"], 10)) * (
                1 + len(reasons)
            )
            results.append(row)
        results.sort(key=lambda row: (-row["priority"], str(row["id"])))
        return results[:limit]

    def recent_corrections(self, *, limit: int = 50) -> list[dict[str, Any]]:
        """Current owner items with correction events, including resolved items."""
        rows = self.conn.execute(
            """select event.item_id, max(event.created_at) as last_corrected_at
               from product_correction_events event
               join transaction_items i on i.id = event.item_id and i.user_id = event.user_id
               join transactions t on t.id = i.transaction_id and t.user_id = i.user_id
               where event.user_id = %(user_id)s and t.status = 'confirmed'
               group by event.item_id
               order by last_corrected_at desc, event.item_id desc
               limit %(limit)s""",
            {"user_id": self.user_id, "limit": max(1, min(limit, 100))},
        ).fetchall()
        results = []
        for entry in rows:
            item = self._item(entry["item_id"])
            item["reasons"] = list(readiness_reasons(item))
            item["last_corrected_at"] = entry["last_corrected_at"]
            results.append(item)
        return results

    def history(self, item_id: UUID) -> list[dict[str, Any]]:
        self._item(item_id)
        rows = self.conn.execute(
            """select id, operation_id, before_value, after_value, reason,
                      created_at, reverses_event_id,
                      exists(select 1 from product_correction_events reversal
                             where reversal.reverses_event_id = event.id
                               and reversal.user_id = event.user_id) as reversed
               from product_correction_events event
               where event.user_id = %(user_id)s and event.item_id = %(item_id)s
               order by created_at desc, id desc""",
            {"user_id": self.user_id, "item_id": item_id},
        ).fetchall()
        return [dict(row) for row in rows]

    def _scope(self, request: ReviewPreviewRequest, *, lock: bool = False) -> list[dict[str, Any]]:
        anchor = self._item(request.item_id, lock=lock)
        if anchor["status"] != "confirmed":
            raise ConflictError("Only confirmed purchases can be reviewed")
        if request.scope == "item":
            return [anchor]
        provenance = ItemEvidence.model_validate(anchor["field_provenance"])
        if (not anchor["product_identity_key"] or provenance.identity.source != "user_confirmed"
                or not anchor["product_type_key"] or provenance.product_type.source != "user_confirmed"):
            raise ConflictError("Bulk scope requires a confirmed product identity and type")
        rows = self.conn.execute(
            """
            select i.id from transaction_items i
            join transactions t on t.id = i.transaction_id and t.user_id = i.user_id
            where i.user_id = %(user_id)s and t.status = 'confirmed'
              and t.transaction_type = 'expense' and i.item_role = 'purchase'
              and i.product_identity_key = %(identity)s
              and i.product_type_key is not distinct from %(product_type)s
              and i.normalized_name is not distinct from %(name)s
              and i.brand is not distinct from %(brand)s
              and i.taxonomy_node_id is not distinct from %(taxonomy)s
              and i.quantity is not distinct from %(quantity)s
              and i.package_value is not distinct from %(package_value)s
              and i.package_unit is not distinct from %(package_unit)s
              and i.measured_value is not distinct from %(measured_value)s
              and i.measured_unit is not distinct from %(measured_unit)s
            order by i.id
            """,
            {
                "user_id": self.user_id, "identity": anchor["product_identity_key"],
                "product_type": anchor["product_type_key"], "name": anchor["normalized_name"],
                "brand": anchor["brand"], "taxonomy": anchor["taxonomy_node_id"],
                "quantity": anchor["quantity"], "package_value": anchor["package_value"],
                "package_unit": anchor["package_unit"], "measured_value": anchor["measured_value"],
                "measured_unit": anchor["measured_unit"],
            },
        ).fetchall()
        candidates = [self._item(row["id"], lock=lock) for row in rows]
        return [row for row in candidates
                if ItemEvidence.model_validate(row["field_provenance"]).identity.source == "user_confirmed"
                and ItemEvidence.model_validate(row["field_provenance"]).product_type.source == "user_confirmed"]

    @staticmethod
    def _snapshot(row: dict[str, Any]) -> dict[str, Any]:
        return {key: row.get(key) for key in SNAPSHOT_FIELDS}

    def _after(self, row: dict[str, Any], patch: ReviewPatch, operation_id: UUID) -> dict[str, Any]:
        changed = patch.model_dump(exclude_unset=True)
        taxonomy_key = changed.pop("taxonomy_node_key", None)
        confirm_fields = changed.pop("confirm_fields", [])
        evidence = ItemEvidence.model_validate(row["field_provenance"]).model_dump(mode="json")
        merged = {**row, **changed}
        source_field = {
            "product_identity_key": "identity", "product_type_key": "product_type", "brand": "brand",
            "quantity": "package_count" if merged["package_value"] is not None else "quantity",
            "package_value": "package_size", "package_unit": "package_size",
            "measured_value": "measured_value", "measured_unit": "measured_value",
        }
        for field in changed:
            if field in source_field:
                evidence[source_field[field]] = {"source": "user_confirmed", "source_ref": f"review:{operation_id}"}
        required_value = {
            "identity": "product_identity_key", "product_type": "product_type_key", "brand": "brand",
            "quantity": "quantity", "package_size": "package_value", "package_count": "quantity",
            "measured_value": "measured_value",
        }
        for field in confirm_fields:
            if merged[required_value[field]] is None:
                raise ConflictError(f"Cannot confirm missing {field} evidence")
            if field == "package_count" and merged["package_value"] is None:
                raise ConflictError("Package count needs an evidenced package size")
            evidence[field] = {"source": "user_confirmed", "source_ref": f"review:{operation_id}"}
        if taxonomy_key is not None:
            merged["taxonomy_node_id"] = TaxonomyRepository(self.conn).resolve_assignable_node_id(
                taxonomy_key, "expense"
            )
            merged["classification_source"] = "user"
            merged["classification_review_status"] = "reviewed"
            merged["classification_reviewed_at"] = datetime.now(UTC)
        price_fields = {"quantity", "unit", "measured_value", "measured_unit", "package_value", "package_unit"}
        if price_fields & changed.keys() or set(confirm_fields) & {
            "quantity", "package_size", "package_count", "measured_value"
        }:
            normalized = _normalized_price_fields(SimpleNamespace(**merged))
            merged.update(normalized)
        merged["field_provenance"] = evidence
        return self._snapshot(merged)

    def preview(self, request: ReviewPreviewRequest) -> ReviewPreview:
        rows = self._scope(request)
        operation_id = request.operation_id or uuid4()
        return ReviewPreview(
            item_id=request.item_id, scope=request.scope, operation_id=operation_id, affected=[
                {"item_id": row["id"], "transaction_id": row["transaction_id"],
                 "revision": row["evidence_revision"], "before": self._snapshot(row),
                 "after": self._after(row, request.patch, operation_id)}
                for row in rows
            ], affected_count=len(rows),
        )

    def decide(self, request: ReviewDecisionRequest) -> ReviewDecisionResult:
        request_hash = _request_hash(request)
        self.conn.execute(
            "select pg_advisory_xact_lock(hashtextextended(%(key)s, 0))",
            {"key": f"product-review:{self.user_id}:{request.operation_id}"},
        )
        previous = self.conn.execute(
            "select decision, request_hash, count(*) as count from product_review_decisions "
            "where user_id = %(user_id)s and operation_id = %(operation_id)s "
            "group by decision, request_hash",
            {"user_id": self.user_id, "operation_id": request.operation_id},
        ).fetchone()
        if previous is not None:
            if previous["decision"] != request.decision or previous["request_hash"] != request_hash:
                raise ConflictError("Operation ID was already used for another review request")
            return ReviewDecisionResult(operation_id=request.operation_id, decision=request.decision,
                                        affected_count=previous["count"], idempotent_replay=True)
        if self.conn.execute(
            "select 1 from product_correction_events where user_id = %(user_id)s "
            "and operation_id = %(operation_id)s limit 1",
            {"user_id": self.user_id, "operation_id": request.operation_id},
        ).fetchone():
            raise ConflictError("Operation ID was already used for a correction")
        rows = self._scope(request, lock=True)
        actual = {row["id"]: row["evidence_revision"] for row in rows}
        if actual != request.expected_revisions:
            raise ConflictError("Review preview is stale; reload and preview again")
        if request.decision == "confirmed" and not request.patch.model_fields_set:
            raise ConflictError("Confirmation requires a proposed correction")
        if request.decision != "confirmed" and len(rows) != 1:
            raise ConflictError("Reject and defer apply to one reviewed item")
        if request.decision == "confirmed":
            self.conn.execute(
                "select set_config('app.confirmed_child_edit_reason', %(reason)s, true)",
                {"reason": request.reason},
            )
        for row in rows:
            if request.decision == "confirmed":
                before = self._snapshot(row)
                after = self._after(row, request.patch, request.operation_id)
                changed = {key: value for key, value in after.items() if value != before[key]}
                if not changed:
                    raise ConflictError("Correction does not change this item")
                assignments = ", ".join(f"{key} = %({key})s" for key in changed)
                params = {key: Jsonb(value) if key == "field_provenance" else value
                          for key, value in changed.items()}
                updated = self.conn.execute(
                    f"update transaction_items set {assignments} "
                    "where id = %(item_id)s and user_id = %(user_id)s "
                    "and evidence_revision = %(revision)s returning evidence_revision",
                    {**params, "item_id": row["id"], "user_id": self.user_id,
                     "revision": row["evidence_revision"]},
                ).fetchone()
                if updated is None:
                    raise ConflictError("Review item changed during correction")
                self.conn.execute(
                    """insert into product_correction_events
                    (user_id, item_id, operation_id, request_hash, before_value, after_value, applied_revision, reason)
                    values (%(user_id)s, %(item_id)s, %(operation_id)s, %(request_hash)s,
                            %(before)s, %(after)s,
                            %(revision)s, %(reason)s)""",
                    {"user_id": self.user_id, "item_id": row["id"], "operation_id": request.operation_id,
                     "request_hash": request_hash,
                     "before": Jsonb(_json_value(before)), "after": Jsonb(_json_value(after)),
                     "revision": updated["evidence_revision"], "reason": request.reason},
                )
            self.conn.execute(
                """insert into product_review_decisions
                (user_id, item_id, issue_key, evidence_revision, decision, reason, operation_id, request_hash)
                values (%(user_id)s, %(item_id)s, 'product_data', %(revision)s,
                        %(decision)s, %(reason)s, %(operation_id)s, %(request_hash)s)""",
                {"user_id": self.user_id, "item_id": row["id"], "revision": row["evidence_revision"],
                 "decision": request.decision, "reason": request.reason,
                 "operation_id": request.operation_id, "request_hash": request_hash},
            )
        return ReviewDecisionResult(operation_id=request.operation_id, decision=request.decision,
                                    affected_count=len(rows))

    def reverse(self, request: ReviewReverseRequest) -> ReviewDecisionResult:
        request_hash = _request_hash(request)
        self.conn.execute(
            "select pg_advisory_xact_lock(hashtextextended(%(key)s, 0))",
            {"key": f"product-review:{self.user_id}:{request.operation_id}"},
        )
        existing = self.conn.execute(
            "select id, request_hash, reverses_event_id from product_correction_events where user_id = %(user_id)s "
            "and operation_id = %(operation_id)s",
            {"user_id": self.user_id, "operation_id": request.operation_id},
        ).fetchone()
        if existing:
            if existing["request_hash"] != request_hash or existing["reverses_event_id"] != request.event_id:
                raise ConflictError("Operation ID was already used for another correction")
            return ReviewDecisionResult(operation_id=request.operation_id, decision="reversed",
                                        affected_count=1, idempotent_replay=True)
        event = self.conn.execute(
            "select * from product_correction_events where id = %(event_id)s and user_id = %(user_id)s",
            {"event_id": request.event_id, "user_id": self.user_id},
        ).fetchone()
        if event is None:
            raise NotFoundError("Correction event not found")
        row = self._item(event["item_id"], lock=True)
        unchanged = _json_value(self._snapshot(row)) == event["after_value"]
        if row["evidence_revision"] != event["applied_revision"] or not unchanged:
            raise ConflictError("A later edit changed this item; reversal requires review")
        self.conn.execute(
            "select set_config('app.confirmed_child_edit_reason', %(reason)s, true)",
            {"reason": request.reason},
        )
        before = event["before_value"]
        assignments = ", ".join(f"{field} = %({field})s" for field in SNAPSHOT_FIELDS)
        params = {key: _database_value(key, value) for key, value in before.items()}
        updated = self.conn.execute(
            f"update transaction_items set {assignments} where id = %(item_id)s "
            "and user_id = %(user_id)s and evidence_revision = %(revision)s returning evidence_revision",
            {**params, "item_id": row["id"], "user_id": self.user_id,
             "revision": row["evidence_revision"]},
        ).fetchone()
        if updated is None:
            raise ConflictError("Correction changed during reversal")
        self.conn.execute(
            """insert into product_correction_events
            (user_id, item_id, operation_id, request_hash, before_value, after_value,
             applied_revision, reason, reverses_event_id)
            values (%(user_id)s, %(item_id)s, %(operation_id)s, %(request_hash)s,
                    %(before)s, %(after)s, %(revision)s, %(reason)s, %(event_id)s)""",
            {"user_id": self.user_id, "item_id": row["id"], "operation_id": request.operation_id,
             "request_hash": request_hash,
             "before": Jsonb(event["after_value"]), "after": Jsonb(before),
             "revision": updated["evidence_revision"], "reason": request.reason,
             "event_id": request.event_id},
        )
        return ReviewDecisionResult(operation_id=request.operation_id, decision="reversed", affected_count=1)
