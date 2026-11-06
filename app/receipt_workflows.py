"""Persisted, client-driven receipt batch and document evidence workflows."""

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, cast
from uuid import UUID

from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field

from app.errors import ConflictError, NotFoundError

AttachmentState = Literal[
    "extraction_pending",
    "extracting",
    "clarification_needed",
    "draft_saved",
    "confirmed",
    "exact_duplicate",
    "possible_duplicate",
    "retryable_failure",
    "terminal_failure",
]

_NEXT: dict[str, set[str]] = {
    "extraction_pending": {"extracting", "clarification_needed", "retryable_failure", "terminal_failure"},
    "extracting": {
        "clarification_needed",
        "draft_saved",
        "exact_duplicate",
        "possible_duplicate",
        "retryable_failure",
        "terminal_failure",
    },
    "clarification_needed": {"extracting", "terminal_failure"},
    "draft_saved": {"confirmed", "clarification_needed", "retryable_failure"},
    "possible_duplicate": {"extracting", "terminal_failure"},
    "retryable_failure": {"extracting", "terminal_failure"},
    "confirmed": set(),
    "exact_duplicate": set(),
    "terminal_failure": set(),
}


class AttachmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_attachment_id: str = Field(min_length=8, max_length=96)
    operation_id: str = Field(min_length=8, max_length=96)


class BatchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_batch_id: str = Field(min_length=8, max_length=96)
    authorization_source: str = Field(min_length=3, max_length=200)
    confirm_authorized: bool = False
    attachments: list[AttachmentInput] = Field(min_length=1, max_length=20)


class AttachmentRecord(BaseModel):
    id: UUID
    client_attachment_id: str
    operation_id: str
    status: AttachmentState
    attempt_count: int
    content_sha256: str | None = None
    provider_key: str | None = None
    order_key: str | None = None
    transaction_id: UUID | None = None
    candidate_transaction_id: UUID | None = None
    receipt_file_id: UUID | None = None
    retry_reason: str | None = None
    distinct_decision_source: str | None = None
    unresolved_issues: list[dict[str, Any]] = Field(default_factory=list)
    updated_at: datetime


class BatchRecord(BaseModel):
    id: UUID
    client_batch_id: str
    authorization_source: str
    confirm_authorized: bool
    attachments: list[AttachmentRecord]
    counts: dict[str, int]


class AttachmentProgress(BaseModel):
    model_config = ConfigDict(extra="forbid")
    batch_id: UUID
    attachment_id: UUID
    status: Literal["extracting", "clarification_needed", "retryable_failure", "terminal_failure"]
    retry_reason: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{2,59}$")
    questions: list[str] = Field(default_factory=list, max_length=20)


class DocumentEventInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    transaction_id: UUID
    expected_revision: datetime
    source_key: str = Field(min_length=8, max_length=200)
    event_kind: Literal[
        "original_charge",
        "order_adjustment",
        "tip",
        "purchase_refund",
        "wallet_top_up",
        "wallet_refund",
        "wallet_use",
        "transfer",
    ]
    amount: Decimal | None = None
    currency: str = Field(min_length=3, max_length=3)
    occurred_at: datetime | None = None
    receipt_file_id: UUID | None = None
    item_id: UUID | None = None
    item_disposition: Literal["kept", "returned", "unknown"] = "unknown"
    attribution_status: Literal["known", "unknown"] = "unknown"
    source_facts: dict[str, Any] = Field(default_factory=dict)
    explicit_approval: bool


class VersionAttachInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    transaction_id: UUID
    expected_revision: datetime
    operation_id: str = Field(min_length=8, max_length=96)
    document_kind: Literal["original", "revision", "adjustment", "refund", "other"]
    provider_order_key: str | None = Field(default=None, max_length=200)
    occurred_at: datetime | None = None
    supersedes_file_id: UUID | None = None
    extracted_facts: dict[str, Any] = Field(default_factory=dict)
    explicit_approval: bool
    batch_id: UUID | None = None
    attachment_id: UUID | None = None


def fingerprint(value: Any) -> str:
    def encode(value: Any) -> str:
        return value.isoformat() if isinstance(value, datetime) else str(value)

    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=encode).encode()).hexdigest()


class ReceiptWorkflowRepository:
    def __init__(self, conn: Any, user_id: UUID) -> None:
        self.conn = conn
        self.user_id = user_id

    def start(self, request: BatchInput) -> BatchRecord:
        ids = [item.client_attachment_id for item in request.attachments]
        operations = [item.operation_id for item in request.attachments]
        if len(set(ids)) != len(ids) or len(set(operations)) != len(operations):
            raise ConflictError("Batch attachment and operation IDs must be unique")
        row = self.conn.execute(
            """insert into receipt_batches (user_id, client_batch_id, authorization_source, confirm_authorized)
               values (%(user_id)s, %(client_batch_id)s, %(source)s, %(authorized)s)
               on conflict (user_id, client_batch_id) do nothing returning id""",
            {
                "user_id": self.user_id,
                "client_batch_id": request.client_batch_id,
                "source": request.authorization_source,
                "authorized": request.confirm_authorized,
            },
        ).fetchone()
        if row is None:
            existing = self.conn.execute(
                """select id, authorization_source, confirm_authorized from receipt_batches
                   where user_id=%(user_id)s and client_batch_id=%(client_batch_id)s""",
                {"user_id": self.user_id, "client_batch_id": request.client_batch_id},
            ).fetchone()
            assert existing is not None
            batch_id = existing["id"]
            current = self.get(batch_id)
            if (
                existing["authorization_source"] != request.authorization_source
                or existing["confirm_authorized"] != request.confirm_authorized
                or [(a.client_attachment_id, a.operation_id) for a in current.attachments]
                != [(a.client_attachment_id, a.operation_id) for a in request.attachments]
            ):
                raise ConflictError("client_batch_id was already used for a different batch or authorization")
            return current
        batch_id = row["id"]
        for ordinal, item in enumerate(request.attachments):
            self.conn.execute(
                """insert into receipt_batch_attachments
                   (user_id, batch_id, client_attachment_id, operation_id, ordinal)
                   values (%(user_id)s, %(batch_id)s, %(attachment_id)s, %(operation_id)s, %(ordinal)s)""",
                {
                    "user_id": self.user_id,
                    "batch_id": batch_id,
                    "attachment_id": item.client_attachment_id,
                    "operation_id": item.operation_id,
                    "ordinal": ordinal,
                },
            )
        return self.get(batch_id)

    def get(self, batch_id: UUID) -> BatchRecord:
        batch = self.conn.execute(
            """select id, client_batch_id, authorization_source, confirm_authorized
               from receipt_batches where id=%(id)s and user_id=%(user_id)s""",
            {"id": batch_id, "user_id": self.user_id},
        ).fetchone()
        if batch is None:
            raise NotFoundError("Receipt batch not found")
        rows = self.conn.execute(
            """select id, client_attachment_id, operation_id, status, attempt_count,
                      content_sha256, provider_key, order_key, transaction_id, candidate_transaction_id,
                      receipt_file_id, retry_reason, distinct_decision_source,
                      unresolved_issues, updated_at
               from receipt_batch_attachments where batch_id=%(id)s and user_id=%(user_id)s
               order by ordinal""",
            {"id": batch_id, "user_id": self.user_id},
        ).fetchall()
        attachments = [AttachmentRecord.model_validate(row) for row in rows]
        counts = {state: sum(a.status == state for a in attachments) for state in _NEXT}
        return BatchRecord(**batch, attachments=attachments, counts=counts)

    def lock_attachment(self, batch_id: UUID, attachment_id: UUID) -> dict[str, Any]:
        row = self.conn.execute(
            """select a.*, b.confirm_authorized from receipt_batch_attachments a
               join receipt_batches b on b.id=a.batch_id and b.user_id=a.user_id
               where a.id=%(id)s and a.batch_id=%(batch_id)s and a.user_id=%(user_id)s
               for update of a""",
            {"id": attachment_id, "batch_id": batch_id, "user_id": self.user_id},
        ).fetchone()
        if row is None:
            raise NotFoundError("Receipt attachment not found")
        return dict(row)

    def progress(self, request: AttachmentProgress) -> BatchRecord:
        self.conn.execute(
            """select id from receipt_batches where id=%(batch_id)s and user_id=%(user_id)s
               for update""",
            {"batch_id": request.batch_id, "user_id": self.user_id},
        )
        row = self.lock_attachment(request.batch_id, request.attachment_id)
        if request.status not in _NEXT[row["status"]]:
            raise ConflictError(f"Cannot change {row['status']} to {request.status}")
        attempts = row["attempt_count"] + int(request.status == "extracting")
        if attempts > 5:
            raise ConflictError("Receipt retry limit reached")
        if request.status == "extracting":
            active = self.conn.execute(
                """select count(*) as count from receipt_batch_attachments
                   where batch_id=%(batch_id)s and user_id=%(user_id)s and status='extracting'""",
                {"batch_id": request.batch_id, "user_id": self.user_id},
            ).fetchone()["count"]
            if active >= 4:
                raise ConflictError("At most four attachments can extract at once")
        if request.status in {"retryable_failure", "terminal_failure"} and not request.retry_reason:
            raise ConflictError("A safe retry reason is required")
        self.conn.execute(
            """update receipt_batch_attachments set status=%(status)s, attempt_count=%(attempts)s,
                      retry_reason=%(reason)s, unresolved_issues=%(issues)s, updated_at=clock_timestamp()
               where id=%(id)s and user_id=%(user_id)s""",
            {
                "status": request.status,
                "attempts": attempts,
                "reason": request.retry_reason,
                "issues": Jsonb([{"question": q[:500]} for q in request.questions]),
                "id": request.attachment_id,
                "user_id": self.user_id,
            },
        )
        return self.get(request.batch_id)

    def record_draft(
        self,
        batch_id: UUID,
        attachment_id: UUID,
        *,
        operation_id: str,
        payload_fingerprint: str,
        content_sha256: str,
        transaction_id: UUID,
        receipt_file_id: UUID,
        duplicate: bool,
        issues: list[dict[str, Any]],
        provider_key: str | None = None,
        order_key: str | None = None,
        distinct_decision_source: str | None = None,
    ) -> None:
        row = self.lock_attachment(batch_id, attachment_id)
        if row["operation_id"] != operation_id:
            raise ConflictError("Operation ID does not match registered attachment")
        if row["payload_fingerprint"] and row["payload_fingerprint"] != payload_fingerprint:
            raise ConflictError("Operation ID was already used with a different payload")
        if row["content_sha256"] and row["content_sha256"] != content_sha256:
            raise ConflictError("Attachment bytes changed since the prior attempt")
        if row["transaction_id"] and row["transaction_id"] != transaction_id:
            raise ConflictError("Attachment already links to a different purchase")
        if row["status"] in {"confirmed", "terminal_failure"}:
            raise ConflictError("Attachment is already terminal")
        purchase = self.conn.execute(
            "select status from transactions where id=%(id)s and user_id=%(user_id)s",
            {"id": transaction_id, "user_id": self.user_id},
        ).fetchone()
        if purchase is None:
            raise ConflictError("Attachment purchase was not found")
        self.conn.execute(
            """update receipt_batch_attachments
               set status=%(status)s, payload_fingerprint=%(fingerprint)s,
                   content_sha256=%(hash)s, transaction_id=%(transaction_id)s,
                   provider_key=%(provider_key)s, order_key=%(order_key)s,
                   distinct_decision_source=%(decision_source)s,
                   receipt_file_id=%(file_id)s, unresolved_issues=%(issues)s,
                   retry_reason=null, updated_at=clock_timestamp()
               where id=%(id)s and user_id=%(user_id)s""",
            {
                # File replay does not turn an unconfirmed draft into a
                # terminal duplicate. A confirmed purchase needs no new
                # confirmation when its exact file appears again.
                "status": "draft_saved" if purchase["status"] == "draft" else "exact_duplicate",
                "fingerprint": payload_fingerprint,
                "hash": content_sha256,
                "transaction_id": transaction_id,
                "provider_key": provider_key,
                "order_key": order_key,
                "decision_source": distinct_decision_source,
                "file_id": receipt_file_id,
                "issues": Jsonb(issues),
                "id": attachment_id,
                "user_id": self.user_id,
            },
        )

    def find_order_candidate(
        self,
        provider_key: str | None,
        order_key: str | None,
        currency: str,
        transaction_date: Any,
        content_sha256: str,
    ) -> UUID | None:
        if not provider_key or not order_key:
            return None
        # This lock serializes two different files for the same source order,
        # while download and extraction happened before opening the transaction.
        params = {
            "user_id": self.user_id,
            "provider": provider_key,
            "order_key": order_key,
            "currency": currency,
            "date": transaction_date,
            "hash": content_sha256,
        }
        self.conn.execute(
            """select pg_advisory_xact_lock(hashtextextended(
                cast(%(user_id)s as text) || ':order:' || %(provider)s || ':' || %(order_key)s, 0))""",
            params,
        )
        row = self.conn.execute(
            """select t.id from transactions t join receipts r on r.transaction_id=t.id
               where t.user_id=%(user_id)s and r.user_id=%(user_id)s
                 and t.provider_key=%(provider)s and r.receipt_number=%(order_key)s
                 and t.currency=%(currency)s and t.transaction_date=%(date)s
                 and not exists (
                    select 1 from receipt_commit_requests c
                    where c.user_id=%(user_id)s and c.transaction_id=t.id
                      and c.source_file_sha256=%(hash)s)
               order by t.created_at, t.id limit 1""",
            params,
        ).fetchone()
        return cast(UUID, row["id"]) if row else None

    def record_candidate(
        self,
        batch_id: UUID,
        attachment_id: UUID,
        *,
        operation_id: str,
        payload_fingerprint: str,
        content_sha256: str,
        provider_key: str,
        order_key: str,
        candidate_id: UUID,
    ) -> BatchRecord:
        row = self.lock_attachment(batch_id, attachment_id)
        if row["operation_id"] != operation_id:
            raise ConflictError("Operation ID does not match registered attachment")
        if row["payload_fingerprint"] and row["payload_fingerprint"] != payload_fingerprint:
            raise ConflictError("Operation payload changed")
        if row["status"] in {"confirmed", "exact_duplicate", "terminal_failure"}:
            raise ConflictError("Attachment is already terminal")
        self.conn.execute(
            """update receipt_batch_attachments set status='possible_duplicate',
                      payload_fingerprint=%(fingerprint)s, content_sha256=%(hash)s,
                      provider_key=%(provider)s, order_key=%(order_key)s,
                      candidate_transaction_id=%(candidate)s, updated_at=clock_timestamp()
               where id=%(id)s and user_id=%(user_id)s""",
            {
                "fingerprint": payload_fingerprint,
                "hash": content_sha256,
                "provider": provider_key,
                "order_key": order_key,
                "candidate": candidate_id,
                "id": attachment_id,
                "user_id": self.user_id,
            },
        )
        return self.get(batch_id)

    def sync_confirmed(self, transaction_id: UUID) -> None:
        self.conn.execute(
            """update receipt_batch_attachments set status='confirmed', updated_at=clock_timestamp()
               where user_id=%(user_id)s and transaction_id=%(transaction_id)s
                 and status='draft_saved'""",
            {"user_id": self.user_id, "transaction_id": transaction_id},
        )

    def record_version_attachment(
        self,
        request: VersionAttachInput,
        file_id: UUID,
        content_sha256: str,
    ) -> None:
        if request.batch_id is None or request.attachment_id is None:
            raise ConflictError("Batch and attachment IDs must be supplied together")
        row = self.lock_attachment(request.batch_id, request.attachment_id)
        if row["operation_id"] != request.operation_id:
            raise ConflictError("Version operation does not match registered attachment")
        if row["candidate_transaction_id"] not in {None, request.transaction_id}:
            raise ConflictError("Version target differs from the reviewed order candidate")
        if row["content_sha256"] not in {None, content_sha256}:
            raise ConflictError("Attachment bytes changed")
        if row["status"] in {"terminal_failure", "exact_duplicate"}:
            raise ConflictError("Attachment is already terminal")
        self.conn.execute(
            """update receipt_batch_attachments set status='confirmed',
                      content_sha256=%(hash)s, transaction_id=%(transaction_id)s,
                      receipt_file_id=%(file_id)s, retry_reason=null,
                      updated_at=clock_timestamp()
               where id=%(id)s and user_id=%(user_id)s""",
            {
                "hash": content_sha256,
                "transaction_id": request.transaction_id,
                "file_id": file_id,
                "id": request.attachment_id,
                "user_id": self.user_id,
            },
        )

    def authorized_transaction(self, batch_id: UUID, attachment_id: UUID) -> UUID:
        row = self.lock_attachment(batch_id, attachment_id)
        if not row["confirm_authorized"]:
            raise ConflictError("This batch did not authorize confirmation")
        if row["status"] not in {"draft_saved", "confirmed"} or row["transaction_id"] is None:
            raise ConflictError("Attachment has no saved draft to confirm")
        return cast(UUID, row["transaction_id"])

    def record_event(self, request: DocumentEventInput) -> dict[str, Any]:
        if not request.explicit_approval:
            raise ConflictError("Explicit approval is required to change a confirmed purchase's documents")
        row = self.conn.execute(
            """select status, currency, updated_at from transactions
               where id=%(id)s and user_id=%(user_id)s for update""",
            {"id": request.transaction_id, "user_id": self.user_id},
        ).fetchone()
        if row is None:
            raise NotFoundError("Purchase not found")
        if row["status"] != "confirmed":
            raise ConflictError("Document events require a confirmed purchase")
        data = request.model_dump(mode="json", exclude={"expected_revision", "explicit_approval"})
        existing = self.conn.execute(
            """select source_facts, event_kind, amount, currency, item_id, item_disposition,
                      attribution_status, receipt_file_id, occurred_at from receipt_document_events
               where user_id=%(user_id)s and transaction_id=%(transaction_id)s and source_key=%(key)s""",
            {"user_id": self.user_id, "transaction_id": request.transaction_id, "key": request.source_key},
        ).fetchone()
        if existing is not None:
            if fingerprint({k: existing[k] for k in existing}) != fingerprint({k: data[k] for k in existing}):
                raise ConflictError("Document source key already has different facts")
            return {"source_key": request.source_key, "idempotent_replay": True}
        if row["updated_at"] != request.expected_revision or row["currency"] != request.currency.upper():
            raise ConflictError("Purchase revision or currency changed; review it again")
        if request.receipt_file_id is not None:
            file = self.conn.execute(
                """select 1 from receipt_files f join receipts r on r.id=f.receipt_id
                   where f.id=%(file_id)s and f.user_id=%(user_id)s
                     and r.transaction_id=%(transaction_id)s and f.upload_status='uploaded'""",
                {"file_id": request.receipt_file_id, "user_id": self.user_id, "transaction_id": request.transaction_id},
            ).fetchone()
            if file is None:
                raise ConflictError("Document file must belong to this purchase")
        if request.item_id is not None:
            item = self.conn.execute(
                """select 1 from transaction_items where id=%(item_id)s
                   and transaction_id=%(transaction_id)s and user_id=%(user_id)s""",
                {"item_id": request.item_id, "transaction_id": request.transaction_id, "user_id": self.user_id},
            ).fetchone()
            if item is None:
                raise ConflictError("Attributed item must belong to this purchase")
        self.conn.execute(
            """insert into receipt_document_events
               (user_id, transaction_id, receipt_file_id, source_key, event_kind, amount,
                currency, occurred_at, item_id, source_item_id, item_disposition, attribution_status, source_facts)
               values (%(user_id)s, %(transaction_id)s, %(receipt_file_id)s, %(source_key)s,
                %(event_kind)s, %(amount)s, %(currency)s, %(occurred_at)s, %(item_id)s,
                %(item_id)s,
                %(item_disposition)s, %(attribution_status)s, %(source_facts)s)""",
            {**data, "user_id": self.user_id, "source_facts": Jsonb(request.source_facts)},
        )
        return {"source_key": request.source_key, "idempotent_replay": False}

    def record_version(
        self,
        transaction_id: UUID,
        file_id: UUID,
        *,
        kind: str,
        order_key: str | None = None,
        occurred_at: datetime | None = None,
        supersedes_file_id: UUID | None = None,
        extracted_facts: dict[str, Any] | None = None,
    ) -> None:
        if supersedes_file_id is not None:
            previous = self.conn.execute(
                """select 1 from receipt_document_versions where receipt_file_id=%(file_id)s
                   and transaction_id=%(transaction_id)s and user_id=%(user_id)s""",
                {"file_id": supersedes_file_id, "transaction_id": transaction_id, "user_id": self.user_id},
            ).fetchone()
            if previous is None:
                raise ConflictError("Superseded document must belong to this purchase")
        self.conn.execute(
            """insert into receipt_document_versions
               (receipt_file_id, user_id, transaction_id, document_kind,
                provider_order_key, occurred_at, supersedes_file_id, extracted_facts)
               values (%(file_id)s, %(user_id)s, %(transaction_id)s, %(kind)s,
                %(order_key)s, %(occurred_at)s, %(supersedes)s, %(facts)s)
               on conflict (receipt_file_id) do nothing""",
            {
                "file_id": file_id,
                "user_id": self.user_id,
                "transaction_id": transaction_id,
                "kind": kind,
                "order_key": order_key,
                "occurred_at": occurred_at,
                "supersedes": supersedes_file_id,
                "facts": Jsonb(extracted_facts or {}),
            },
        )

    def timeline(self, transaction_id: UUID) -> dict[str, Any]:
        purchase = self.conn.execute(
            "select 1 from transactions where id=%(id)s and user_id=%(user_id)s",
            {"id": transaction_id, "user_id": self.user_id},
        ).fetchone()
        if purchase is None:
            raise NotFoundError("Purchase not found")
        params = {"transaction_id": transaction_id, "user_id": self.user_id}
        versions = self.conn.execute(
            """select receipt_file_id, document_kind, provider_order_key, occurred_at,
                      supersedes_file_id, extracted_facts, created_at
               from receipt_document_versions where transaction_id=%(transaction_id)s
                 and user_id=%(user_id)s order by occurred_at nulls last, created_at, receipt_file_id""",
            params,
        ).fetchall()
        events = self.conn.execute(
            """select source_key, event_kind, amount, currency, occurred_at, receipt_file_id,
                      item_id, source_item_id, item_disposition, attribution_status, source_facts
               from receipt_document_events where transaction_id=%(transaction_id)s
                 and user_id=%(user_id)s order by occurred_at nulls last, created_at, id""",
            params,
        ).fetchall()
        return {
            "transaction_id": transaction_id,
            "versions": [dict(row) for row in versions],
            "events": [dict(row) for row in events],
        }
