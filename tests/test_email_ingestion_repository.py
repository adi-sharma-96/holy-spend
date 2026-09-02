from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.email_ingestion_repository import EmailIngestionRepository
from app.plugin_models import (
    CheckEmailProcessedRequest,
    CheckEmailsProcessedRequest,
    ClaimEmailForProcessingRequest,
    RecordEmailProcessedRequest,
)

USER_ID = UUID("11111111-1111-4111-8111-111111111111")
TRANSACTION_ID = UUID("22222222-2222-4222-8222-222222222222")


@dataclass
class FakeCursor:
    rows: list[dict[str, Any]] = field(default_factory=list)

    def fetchone(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None

    def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


class FakeConn:
    def __init__(
        self,
        existing_row: dict[str, Any] | None = None,
        batch_rows: list[dict[str, Any]] | None = None,
        claim_returns_row: bool = True,
    ) -> None:
        self.existing_row = existing_row
        self.batch_rows = batch_rows or []
        self.claim_returns_row = claim_returns_row
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def execute(self, sql: str, params: dict[str, Any] | None = None) -> FakeCursor:
        self.calls.append((sql, params or {}))
        # check_batch's marker is checked first since it's a superstring of check's own
        # marker ("email_ingestion:check" is a substring of "email_ingestion:check_batch").
        if "email_ingestion:check_batch" in sql:
            return FakeCursor(rows=self.batch_rows)
        if "email_ingestion:claim" in sql:
            return FakeCursor(rows=[{"id": "some-id"}] if self.claim_returns_row else [])
        if "email_ingestion:check" in sql:
            return FakeCursor(rows=[self.existing_row] if self.existing_row else [])
        return FakeCursor()


def test_check_processed_returns_unprocessed_when_no_row_exists() -> None:
    conn = FakeConn()

    response = EmailIngestionRepository(conn, USER_ID).check_processed(
        CheckEmailProcessedRequest(message_id="msg-123")
    )

    assert response.message_id == "msg-123"
    assert response.processed is False
    assert response.record is None


def test_check_processed_returns_the_prior_outcome_when_a_row_exists() -> None:
    conn = FakeConn(
        existing_row={
            "status": "drafted",
            "transaction_id": TRANSACTION_ID,
            "note": None,
            "processed_at": datetime(2026, 8, 14, tzinfo=UTC),
        }
    )

    response = EmailIngestionRepository(conn, USER_ID).check_processed(
        CheckEmailProcessedRequest(message_id="msg-456")
    )

    assert response.processed is True
    assert response.record is not None
    assert response.record.status == "drafted"
    assert response.record.transaction_id == TRANSACTION_ID


def test_check_processed_excludes_a_stale_claimed_row() -> None:
    # Real bug found 2026-08-16: a message claimed but never finalized (a crashed run, or
    # a dead Holy Spend MCP connection mid-processing) must not block re-processing
    # forever - the loop only ever calls claim_email_for_processing for ids this check
    # reports as unprocessed, so claim_for_processing's own 1-hour staleness window can
    # never fire unless this check already excludes a stale claim too.
    conn = FakeConn()

    EmailIngestionRepository(conn, USER_ID).check_processed(CheckEmailProcessedRequest(message_id="msg-stale"))

    sql, _ = next(call for call in conn.calls if "email_ingestion:check" in call[0])
    assert "not (status = 'claimed' and processed_at < now() - interval '1 hour')" in sql


def test_check_processed_batch_excludes_a_stale_claimed_row() -> None:
    conn = FakeConn()

    EmailIngestionRepository(conn, USER_ID).check_processed_batch(
        CheckEmailsProcessedRequest(message_ids=["msg-stale"])
    )

    sql, _ = next(call for call in conn.calls if "email_ingestion:check_batch" in call[0])
    assert "not (status = 'claimed' and processed_at < now() - interval '1 hour')" in sql


def test_check_processed_scopes_the_lookup_by_owner_and_message_id() -> None:
    conn = FakeConn()

    EmailIngestionRepository(conn, USER_ID).check_processed(CheckEmailProcessedRequest(message_id="msg-789"))

    _, params = next(call for call in conn.calls if "email_ingestion:check" in call[0])
    assert params["user_id"] == USER_ID
    assert params["message_id"] == "msg-789"


def test_record_processed_writes_drafted_status_with_transaction_id() -> None:
    conn = FakeConn()

    result = EmailIngestionRepository(conn, USER_ID).record_processed(
        RecordEmailProcessedRequest(message_id="msg-abc", status="drafted", transaction_id=TRANSACTION_ID)
    )

    assert result.ok is True
    _, params = next(call for call in conn.calls if "email_ingestion:record" in call[0])
    assert params["status"] == "drafted"
    assert params["transaction_id"] == TRANSACTION_ID
    assert params["note"] is None


def test_record_processed_writes_flagged_status_with_a_note_and_no_transaction() -> None:
    conn = FakeConn()

    EmailIngestionRepository(conn, USER_ID).record_processed(
        RecordEmailProcessedRequest(
            message_id="msg-def",
            status="flagged",
            note="Uber Eats grocery order - no items in email",
        )
    )

    _, params = next(call for call in conn.calls if "email_ingestion:record" in call[0])
    assert params["status"] == "flagged"
    assert params["transaction_id"] is None
    assert params["note"] == "Uber Eats grocery order - no items in email"


def test_record_processed_is_an_upsert_not_an_error_on_a_repeat_call() -> None:
    # A retried record_email_processed call after an uncertain prior attempt (e.g. the
    # network dropped the response but the write actually landed) must overwrite, not
    # raise a unique-constraint violation - the SQL itself handles this via ON CONFLICT
    # DO UPDATE; this test just confirms the repository sends that clause.
    conn = FakeConn()

    EmailIngestionRepository(conn, USER_ID).record_processed(
        RecordEmailProcessedRequest(message_id="msg-ghi", status="not_a_receipt")
    )

    sql, _ = next(call for call in conn.calls if "email_ingestion:record" in call[0])
    assert "on conflict (owner_user_id, message_id) do update" in sql


def test_check_processed_batch_is_one_call_regardless_of_how_many_ids() -> None:
    conn = FakeConn(
        batch_rows=[
            {
                "message_id": "msg-2",
                "status": "not_a_receipt",
                "transaction_id": None,
                "note": None,
                "processed_at": datetime(2026, 8, 14, tzinfo=UTC),
            }
        ]
    )

    EmailIngestionRepository(conn, USER_ID).check_processed_batch(
        CheckEmailsProcessedRequest(message_ids=["msg-1", "msg-2", "msg-3"])
    )

    batch_calls = [call for call in conn.calls if "email_ingestion:check_batch" in call[0]]
    assert len(batch_calls) == 1
    _, params = batch_calls[0]
    assert params["message_ids"] == ["msg-1", "msg-2", "msg-3"]


def test_check_processed_batch_returns_one_result_per_id_in_the_same_order() -> None:
    conn = FakeConn(
        batch_rows=[
            {
                "message_id": "msg-2",
                "status": "drafted",
                "transaction_id": TRANSACTION_ID,
                "note": None,
                "processed_at": datetime(2026, 8, 14, tzinfo=UTC),
            }
        ]
    )

    response = EmailIngestionRepository(conn, USER_ID).check_processed_batch(
        CheckEmailsProcessedRequest(message_ids=["msg-1", "msg-2", "msg-3"])
    )

    assert [result.message_id for result in response.results] == ["msg-1", "msg-2", "msg-3"]
    assert response.results[0].processed is False
    assert response.results[0].record is None
    assert response.results[1].processed is True
    assert response.results[1].record is not None
    assert response.results[1].record.status == "drafted"
    assert response.results[1].record.transaction_id == TRANSACTION_ID
    assert response.results[2].processed is False


def test_drafted_status_requires_a_transaction_id() -> None:
    # A real gap flagged by external review: nothing previously tied 'drafted' to
    # actually having a transaction_id, so a caller could silently record a draft
    # outcome with no way to trace which transaction it refers to.
    with pytest.raises(ValidationError, match="requires transaction_id"):
        RecordEmailProcessedRequest(message_id="msg-1", status="drafted", transaction_id=None)


def test_flagged_status_requires_a_non_empty_note() -> None:
    with pytest.raises(ValidationError, match="requires a non-empty note"):
        RecordEmailProcessedRequest(message_id="msg-1", status="flagged", note=None)


def test_flagged_status_rejects_a_blank_note() -> None:
    with pytest.raises(ValidationError, match="requires a non-empty note"):
        RecordEmailProcessedRequest(message_id="msg-1", status="flagged", note="   ")


def test_not_a_receipt_status_needs_neither_field() -> None:
    # Should not raise - not_a_receipt is the one status with no required companion.
    RecordEmailProcessedRequest(message_id="msg-1", status="not_a_receipt")


def test_claim_for_processing_succeeds_on_a_fresh_message_id() -> None:
    conn = FakeConn(claim_returns_row=True)

    response = EmailIngestionRepository(conn, USER_ID).claim_for_processing(
        ClaimEmailForProcessingRequest(message_id="msg-new")
    )

    assert response.message_id == "msg-new"
    assert response.claimed is True


def test_claim_for_processing_fails_when_another_attempt_already_holds_it() -> None:
    conn = FakeConn(claim_returns_row=False)

    response = EmailIngestionRepository(conn, USER_ID).claim_for_processing(
        ClaimEmailForProcessingRequest(message_id="msg-taken")
    )

    assert response.claimed is False


def test_claim_for_processing_scopes_the_claim_by_owner_and_message_id() -> None:
    conn = FakeConn(claim_returns_row=True)

    EmailIngestionRepository(conn, USER_ID).claim_for_processing(
        ClaimEmailForProcessingRequest(message_id="msg-scope")
    )

    _, params = next(call for call in conn.calls if "email_ingestion:claim" in call[0])
    assert params["user_id"] == USER_ID
    assert params["message_id"] == "msg-scope"


def test_claim_for_processing_reclaims_only_a_stale_claimed_row() -> None:
    conn = FakeConn(claim_returns_row=True)

    EmailIngestionRepository(conn, USER_ID).claim_for_processing(
        ClaimEmailForProcessingRequest(message_id="msg-stale")
    )

    sql, _ = next(call for call in conn.calls if "email_ingestion:claim" in call[0])
    assert "on conflict (owner_user_id, message_id) do update" in sql
    assert "where email_ingestion_log.status = 'claimed'" in sql
    assert "interval '1 hour'" in sql
