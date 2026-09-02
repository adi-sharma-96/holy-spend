from typing import Any
from uuid import UUID

from app.plugin_models import (
    CheckEmailProcessedRequest,
    CheckEmailProcessedResponse,
    CheckEmailsProcessedRequest,
    CheckEmailsProcessedResponse,
    ClaimEmailForProcessingRequest,
    ClaimEmailForProcessingResponse,
    EmailIngestionRecord,
    OperationResult,
    RecordEmailProcessedRequest,
)

_CLAIM_STALENESS = "interval '1 hour'"


class EmailIngestionRepository:
    """Tracks which forwarded receipt emails the scheduled ingestion task has already
    looked at, keyed by Gmail's own message id - see 0026_email_ingestion_log.sql and
    the email-receipt-ingestion-design project memory for why this exists instead of
    Gmail labels or Cursor's own automation memory."""

    def __init__(self, conn: Any, user_id: UUID) -> None:
        self.conn = conn
        self.user_id = user_id

    def check_processed(self, request: CheckEmailProcessedRequest) -> CheckEmailProcessedResponse:
        # A 'claimed' row older than the staleness window is an abandoned attempt (a run
        # that crashed or never got a Holy Spend MCP connection - see 2026-08-16's failed
        # run) - excluding it here, not just in claim_for_processing's own SQL, is what
        # actually lets the scheduled task's loop re-offer it, since the loop only calls
        # claim_email_for_processing for ids this check reports as unprocessed.
        row = self.conn.execute(
            f"""
            /* email_ingestion:check */
            select status, transaction_id, note, processed_at
            from email_ingestion_log
            where owner_user_id = %(user_id)s and message_id = %(message_id)s
              and not (status = 'claimed' and processed_at < now() - {_CLAIM_STALENESS})
            """,
            {"user_id": self.user_id, "message_id": request.message_id},
        ).fetchone()
        if row is None:
            return CheckEmailProcessedResponse(message_id=request.message_id, processed=False)
        return CheckEmailProcessedResponse(
            message_id=request.message_id,
            processed=True,
            record=EmailIngestionRecord(
                status=row["status"],
                transaction_id=row["transaction_id"],
                note=row["note"],
                processed_at=row["processed_at"],
            ),
        )

    def check_processed_batch(self, request: CheckEmailsProcessedRequest) -> CheckEmailsProcessedResponse:
        rows = self.conn.execute(
            f"""
            /* email_ingestion:check_batch */
            select message_id, status, transaction_id, note, processed_at
            from email_ingestion_log
            where owner_user_id = %(user_id)s and message_id = any(%(message_ids)s)
              and not (status = 'claimed' and processed_at < now() - {_CLAIM_STALENESS})
            """,
            {"user_id": self.user_id, "message_ids": request.message_ids},
        ).fetchall()
        by_message_id = {row["message_id"]: row for row in rows}
        results = []
        for message_id in request.message_ids:
            row = by_message_id.get(message_id)
            if row is None:
                results.append(CheckEmailProcessedResponse(message_id=message_id, processed=False))
                continue
            results.append(
                CheckEmailProcessedResponse(
                    message_id=message_id,
                    processed=True,
                    record=EmailIngestionRecord(
                        status=row["status"],
                        transaction_id=row["transaction_id"],
                        note=row["note"],
                        processed_at=row["processed_at"],
                    ),
                )
            )
        return CheckEmailsProcessedResponse(results=results)

    def claim_for_processing(
        self, request: ClaimEmailForProcessingRequest
    ) -> ClaimEmailForProcessingResponse:
        # Single atomic statement: a fresh message_id inserts and claims it; an existing
        # 'claimed' row older than an hour (an abandoned/crashed attempt) re-claims via the
        # DO UPDATE; anything else (a finished result, or a claim from the last hour) skips
        # the update, so RETURNING yields no row - the unique constraint on
        # (owner_user_id, message_id) is what actually prevents two concurrent callers from
        # both winning the claim.
        row = self.conn.execute(
            f"""
            /* email_ingestion:claim */
            insert into email_ingestion_log (owner_user_id, message_id, status, processed_at)
            values (%(user_id)s, %(message_id)s, 'claimed', now())
            on conflict (owner_user_id, message_id) do update
            set status = 'claimed', processed_at = now()
            where email_ingestion_log.status = 'claimed'
              and email_ingestion_log.processed_at < now() - {_CLAIM_STALENESS}
            returning id
            """,
            {"user_id": self.user_id, "message_id": request.message_id},
        ).fetchone()
        return ClaimEmailForProcessingResponse(message_id=request.message_id, claimed=row is not None)

    def record_processed(self, request: RecordEmailProcessedRequest) -> OperationResult:
        self.conn.execute(
            """
            /* email_ingestion:record */
            insert into email_ingestion_log
                (owner_user_id, message_id, status, transaction_id, note, processed_at)
            values
                (%(user_id)s, %(message_id)s, %(status)s, %(transaction_id)s, %(note)s, now())
            on conflict (owner_user_id, message_id) do update
            set status = excluded.status,
                transaction_id = excluded.transaction_id,
                note = excluded.note,
                processed_at = excluded.processed_at
            """,
            {
                "user_id": self.user_id,
                "message_id": request.message_id,
                "status": request.status,
                "transaction_id": request.transaction_id,
                "note": request.note,
            },
        )
        return OperationResult(ok=True, message=f"Recorded {request.status} for {request.message_id}.")
