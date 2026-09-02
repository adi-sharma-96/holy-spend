import os
from collections.abc import Iterator
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.analytics import AnalyticsRepository
from app.errors import NotFoundError
from app.models import (
    AdjustmentType,
    AnalyticsQueryRequest,
    TransactionAdjustmentCreate,
    TransactionListFilters,
)
from app.receipt_files import ReceiptRepository
from app.repositories import TransactionRepository

TEST_ADMIN_DATABASE_URL = os.getenv("TEST_ADMIN_DATABASE_URL")
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_ADMIN_DATABASE_URL or not TEST_DATABASE_URL,
    reason="Set TEST_ADMIN_DATABASE_URL and TEST_DATABASE_URL to run database/RLS integration tests.",
)

USER_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
USER_B = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


@pytest.fixture
def admin_conn() -> Iterator[Any]:
    assert TEST_ADMIN_DATABASE_URL is not None
    with psycopg.connect(TEST_ADMIN_DATABASE_URL, row_factory=dict_row) as connection:
        yield connection


@pytest.fixture
def runtime_conn() -> Iterator[Any]:
    assert TEST_DATABASE_URL is not None
    with psycopg.connect(TEST_DATABASE_URL, row_factory=dict_row) as connection:
        yield connection


@pytest.fixture
def seeded_transactions(admin_conn: Any) -> Iterator[tuple[UUID, UUID]]:
    cleanup_test_data(admin_conn)
    seed_auth_user(admin_conn, USER_A, "a@example.test")
    seed_auth_user(admin_conn, USER_B, "b@example.test")
    tx_a = seed_transaction(admin_conn, USER_A, "11.00")
    tx_b = seed_transaction(admin_conn, USER_B, "22.00")
    admin_conn.commit()
    yield tx_a, tx_b
    cleanup_test_data(admin_conn)
    admin_conn.commit()


def cleanup_test_data(conn: Any) -> None:
    user_ids = [USER_A, USER_B]
    conn.execute("delete from audit_events where user_id = any(%(user_ids)s)", {"user_ids": user_ids})
    conn.execute("delete from user_corrections where user_id = any(%(user_ids)s)", {"user_ids": user_ids})
    conn.execute("delete from validation_issues where user_id = any(%(user_ids)s)", {"user_ids": user_ids})
    conn.execute("delete from user_product_aliases where user_id = any(%(user_ids)s)", {"user_ids": user_ids})
    conn.execute("delete from transaction_adjustments where user_id = any(%(user_ids)s)", {"user_ids": user_ids})
    conn.execute("delete from transaction_item_themes where user_id = any(%(user_ids)s)", {"user_ids": user_ids})
    conn.execute("delete from transaction_items where user_id = any(%(user_ids)s)", {"user_ids": user_ids})
    conn.execute("delete from receipt_files where user_id = any(%(user_ids)s)", {"user_ids": user_ids})
    conn.execute("delete from receipts where user_id = any(%(user_ids)s)", {"user_ids": user_ids})
    conn.execute("delete from transactions where user_id = any(%(user_ids)s)", {"user_ids": user_ids})
    conn.execute("delete from oauth_refresh_tokens where user_id = any(%(user_ids)s)", {"user_ids": user_ids})
    conn.execute("delete from personal_access_tokens where user_id = any(%(user_ids)s)", {"user_ids": user_ids})
    conn.execute("delete from profiles where id = any(%(user_ids)s)", {"user_ids": user_ids})
    conn.execute("delete from auth.users where id = any(%(user_ids)s)", {"user_ids": user_ids})


def seed_auth_user(conn: Any, user_id: UUID, email: str) -> None:
    conn.execute(
        """
        insert into auth.users (id, aud, role, email, created_at, updated_at)
        values (%(id)s, 'authenticated', 'authenticated', %(email)s, now(), now())
        on conflict (id) do nothing
        """,
        {"id": user_id, "email": email},
    )
    conn.execute(
        """
        insert into profiles (id, display_name, default_currency)
        values (%(id)s, %(display_name)s, 'CAD')
        on conflict (id) do nothing
        """,
        {"id": user_id, "display_name": email},
    )


def seed_transaction(conn: Any, user_id: UUID, total: str) -> UUID:
    row = conn.execute(
        """
        insert into transactions (
            user_id, transaction_type, source_type, transaction_date, currency, total_amount
        )
        values (%(user_id)s, 'expense', 'manual', current_date, 'CAD', %(total)s)
        returning id
        """,
        {"user_id": user_id, "total": total},
    ).fetchone()
    return cast(UUID, cast(dict[str, Any], row)["id"])


def set_local_user(conn: Any, user_id: UUID) -> None:
    conn.execute(
        "select set_config('app.current_user_id', %(user_id)s, true)",
        {"user_id": str(user_id)},
    )


def test_user_a_can_access_user_a_data(
    runtime_conn: Any,
    seeded_transactions: tuple[UUID, UUID],
) -> None:
    tx_a, _ = seeded_transactions
    with runtime_conn.transaction():
        set_local_user(runtime_conn, USER_A)
        rows = runtime_conn.execute(
            "select id from transactions where id = %(id)s",
            {"id": tx_a},
        ).fetchall()

    assert [row["id"] for row in rows] == [tx_a]


def test_user_a_cannot_access_user_b_data(
    runtime_conn: Any,
    seeded_transactions: tuple[UUID, UUID],
) -> None:
    _, tx_b = seeded_transactions
    with runtime_conn.transaction():
        set_local_user(runtime_conn, USER_A)
        rows = runtime_conn.execute(
            "select id from transactions where id = %(id)s",
            {"id": tx_b},
        ).fetchall()

    assert rows == []


def test_user_can_permanently_delete_only_an_owned_receipt_transaction(
    admin_conn: Any,
    runtime_conn: Any,
    seeded_transactions: tuple[UUID, UUID],
) -> None:
    tx_a, tx_b = seeded_transactions
    receipt_id = admin_conn.execute(
        "insert into receipts (user_id, transaction_id) values (%(user_id)s, %(tx_id)s) returning id",
        {"user_id": USER_A, "tx_id": tx_a},
    ).fetchone()["id"]
    admin_conn.execute(
        """
        insert into receipt_files (
            user_id, receipt_id, object_key, original_filename, mime_type
        )
        values (%(user_id)s, %(receipt_id)s, %(object_key)s, 'delete-test.png', 'image/png')
        """,
        {
            "user_id": USER_A,
            "receipt_id": receipt_id,
            "object_key": f"users/{USER_A}/receipts/{receipt_id}/delete-test.png",
        },
    )
    admin_conn.commit()

    with runtime_conn.transaction():
        set_local_user(runtime_conn, USER_A)
        repository = ReceiptRepository(runtime_conn, USER_A)
        with pytest.raises(NotFoundError, match="Transaction not found"):
            repository.delete_transaction(tx_b)
        repository.delete_transaction(tx_a)
        transaction_count = runtime_conn.execute(
            "select count(*) as count from transactions where id = %(id)s",
            {"id": tx_a},
        ).fetchone()["count"]
        receipt_count = runtime_conn.execute(
            "select count(*) as count from receipts where id = %(id)s",
            {"id": receipt_id},
        ).fetchone()["count"]

    assert transaction_count == 0
    assert receipt_count == 0


def test_transaction_listing_returns_only_current_user_data(
    runtime_conn: Any,
    seeded_transactions: tuple[UUID, UUID],
) -> None:
    tx_a, _ = seeded_transactions
    with runtime_conn.transaction():
        set_local_user(runtime_conn, USER_A)
        result = TransactionRepository(runtime_conn, USER_A).list_transactions(
            TransactionListFilters(limit=10)
        )

    assert [transaction.id for transaction in result.transactions] == [tx_a]
    assert result.total == 1


def test_confirmed_adjustment_removal_creates_correction_and_audit_records(
    admin_conn: Any,
    runtime_conn: Any,
    seeded_transactions: tuple[UUID, UUID],
) -> None:
    tx_a, _ = seeded_transactions
    admin_conn.execute(
        "update transactions set status = 'confirmed', confirmed_at = now() where id = %(id)s",
        {"id": tx_a},
    )
    admin_conn.commit()

    with runtime_conn.transaction():
        set_local_user(runtime_conn, USER_A)
        repository = TransactionRepository(runtime_conn, USER_A)
        adjustment = repository.add_adjustment(
            tx_a,
            TransactionAdjustmentCreate(
                type=AdjustmentType.DISCOUNT,
                amount=Decimal("0.58"),
                description="Duplicate promotion detail",
                correction_reason="Add receipt promotion detail",
            ),
        )
        repository.delete_adjustment(
            tx_a,
            adjustment.id,
            correction_reason="Remove duplicate promotion detail",
        )
        adjustment_count = runtime_conn.execute(
            "select count(*) as count from transaction_adjustments where transaction_id = %(id)s",
            {"id": tx_a},
        ).fetchone()["count"]
        correction_count = runtime_conn.execute(
            "select count(*) as count from user_corrections where transaction_id = %(id)s",
            {"id": tx_a},
        ).fetchone()["count"]
        audit_count = runtime_conn.execute(
            """
            select count(*) as count
            from audit_events
            where entity_type = 'transaction_adjustment'
              and entity_id = %(id)s
              and action in ('created', 'deleted')
            """,
            {"id": adjustment.id},
        ).fetchone()["count"]

    assert adjustment_count == 0
    assert correction_count == 2
    assert audit_count == 2


def test_analytics_excludes_drafts_and_other_users(
    admin_conn: Any,
    runtime_conn: Any,
    seeded_transactions: tuple[UUID, UUID],
) -> None:
    tx_a, tx_b = seeded_transactions
    admin_conn.execute(
        "update transactions set status = 'confirmed', confirmed_at = now() where id = any(%(ids)s)",
        {"ids": [tx_a, tx_b]},
    )
    seed_transaction(admin_conn, USER_A, "99.00")
    admin_conn.commit()

    with runtime_conn.transaction():
        set_local_user(runtime_conn, USER_A)
        result = AnalyticsRepository(runtime_conn, USER_A).query(
            AnalyticsQueryRequest(metrics=["total_spend", "purchase_count"])
        )

    assert result.rows[0].metrics["total_spend"] == 11
    assert result.rows[0].metrics["purchase_count"] == 1


def test_aliases_are_learned_on_confirmation_not_draft(
    admin_conn: Any,
    runtime_conn: Any,
    seeded_transactions: tuple[UUID, UUID],
) -> None:
    tx_a, _ = seeded_transactions
    category_id = admin_conn.execute(
        "select id from categories where slug = 'grocery.food.dairy_eggs_alternatives.milk'",
    ).fetchone()["id"]
    admin_conn.execute(
        """
        insert into transaction_items (
            user_id, transaction_id, raw_name, category_id, line_total_amount
        )
        values (%(user_id)s, %(transaction_id)s, 'TEST MILK', %(category_id)s, 11.00)
        """,
        {"user_id": USER_A, "transaction_id": tx_a, "category_id": category_id},
    )
    admin_conn.commit()

    with runtime_conn.transaction():
        set_local_user(runtime_conn, USER_A)
        before = runtime_conn.execute(
            "select count(*) as count from user_product_aliases where user_id = %(user_id)s",
            {"user_id": USER_A},
        ).fetchone()["count"]
        repo = TransactionRepository(runtime_conn, USER_A)
        repo.confirm_transaction(tx_a)
        repo.confirm_transaction(tx_a)
        after = runtime_conn.execute(
            """
            select confirmed_count
            from user_product_aliases
            where user_id = %(user_id)s and raw_name_normalized = 'test milk'
            """,
            {"user_id": USER_A},
        ).fetchone()

    assert before == 0
    assert after["confirmed_count"] == 1


def test_pooled_connections_do_not_retain_current_user_id() -> None:
    assert TEST_DATABASE_URL is not None
    with ConnectionPool(
        TEST_DATABASE_URL,
        min_size=1,
        max_size=1,
        kwargs={"row_factory": dict_row},
    ) as pool:
        with pool.connection() as conn, conn.transaction():
            set_local_user(conn, USER_A)
            current_row = conn.execute("select app.current_user_id() as user_id").fetchone()
            current = cast(dict[str, Any], current_row)["user_id"]
            assert current == USER_A

        with pool.connection() as conn, conn.transaction():
            current_row = conn.execute("select app.current_user_id() as user_id").fetchone()
            current = cast(dict[str, Any], current_row)["user_id"]
            assert current is None


def test_runtime_role_has_no_bypassrls(runtime_conn: Any) -> None:
    row = runtime_conn.execute(
        "select rolbypassrls from pg_roles where rolname = current_user"
    ).fetchone()

    assert row["rolbypassrls"] is False


def test_runtime_role_cannot_directly_read_personal_access_tokens(runtime_conn: Any) -> None:
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        runtime_conn.execute("select id from personal_access_tokens limit 1").fetchall()


def test_revoked_pat_cannot_authenticate(
    admin_conn: Any,
    runtime_conn: Any,
    seeded_transactions: tuple[UUID, UUID],
) -> None:
    del seeded_transactions
    token_hash = "a" * 64
    token_id = admin_conn.execute(
        """
        insert into personal_access_tokens (user_id, token_hash, name, scopes)
        values (%(user_id)s, %(token_hash)s, 'integration test', array['taxonomy:read'])
        returning id
        """,
        {"user_id": USER_A, "token_hash": token_hash},
    ).fetchone()["id"]
    admin_conn.commit()

    before = runtime_conn.execute(
        "select user_id from app.authenticate_pat(%(token_hash)s)",
        {"token_hash": token_hash},
    ).fetchone()
    assert before["user_id"] == USER_A
    runtime_conn.commit()

    admin_conn.execute(
        "update personal_access_tokens set revoked_at = now() where id = %(token_id)s",
        {"token_id": token_id},
    )
    admin_conn.commit()
    after = runtime_conn.execute(
        "select user_id from app.authenticate_pat(%(token_hash)s)",
        {"token_hash": token_hash},
    ).fetchone()

    assert after is None


def test_runtime_role_cannot_directly_read_oauth_refresh_tokens(runtime_conn: Any) -> None:
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        runtime_conn.execute("select id from oauth_refresh_tokens limit 1").fetchall()


def test_runtime_role_can_insert_own_oauth_refresh_token_but_not_for_another_user(
    admin_conn: Any,
    runtime_conn: Any,
    seeded_transactions: tuple[UUID, UUID],
) -> None:
    del seeded_transactions
    pat_id = admin_conn.execute(
        """
        insert into personal_access_tokens (user_id, token_hash, name, scopes)
        values (%(user_id)s, 'b' * 64, 'integration test oauth pat', array['taxonomy:read'])
        returning id
        """,
        {"user_id": USER_A},
    ).fetchone()["id"]
    admin_conn.commit()

    with runtime_conn.transaction():
        set_local_user(runtime_conn, USER_A)
        runtime_conn.execute(
            """
            insert into oauth_refresh_tokens (user_id, token_hash, pat_token_id, expires_at)
            values (%(user_id)s, 'c' * 64, %(pat_id)s, now() + interval '1 day')
            """,
            {"user_id": USER_A, "pat_id": pat_id},
        )

    with pytest.raises(psycopg.errors.InsufficientPrivilege), runtime_conn.transaction():
        set_local_user(runtime_conn, USER_A)
        runtime_conn.execute(
            """
            insert into oauth_refresh_tokens (user_id, token_hash, pat_token_id, expires_at)
            values (%(user_id)s, 'd' * 64, %(pat_id)s, now() + interval '1 day')
            """,
            {"user_id": USER_B, "pat_id": pat_id},
        )


def test_revoked_oauth_refresh_token_cannot_authenticate(
    admin_conn: Any,
    runtime_conn: Any,
    seeded_transactions: tuple[UUID, UUID],
) -> None:
    del seeded_transactions
    pat_id = admin_conn.execute(
        """
        insert into personal_access_tokens (user_id, token_hash, name, scopes)
        values (%(user_id)s, 'e' * 64, 'integration test oauth pat', array['taxonomy:read'])
        returning id
        """,
        {"user_id": USER_A},
    ).fetchone()["id"]
    refresh_token_hash = "f" * 64
    refresh_id = admin_conn.execute(
        """
        insert into oauth_refresh_tokens (user_id, token_hash, pat_token_id, expires_at)
        values (%(user_id)s, %(token_hash)s, %(pat_id)s, now() + interval '1 day')
        returning id
        """,
        {"user_id": USER_A, "token_hash": refresh_token_hash, "pat_id": pat_id},
    ).fetchone()["id"]
    admin_conn.commit()

    before = runtime_conn.execute(
        "select user_id from app.authenticate_oauth_refresh_token(%(token_hash)s)",
        {"token_hash": refresh_token_hash},
    ).fetchone()
    assert before["user_id"] == USER_A
    runtime_conn.commit()

    admin_conn.execute(
        "update oauth_refresh_tokens set revoked_at = now() where id = %(id)s",
        {"id": refresh_id},
    )
    admin_conn.commit()
    after = runtime_conn.execute(
        "select user_id from app.authenticate_oauth_refresh_token(%(token_hash)s)",
        {"token_hash": refresh_token_hash},
    ).fetchone()

    assert after is None


def test_receipt_file_rls_hides_other_users_files(
    admin_conn: Any,
    runtime_conn: Any,
    seeded_transactions: tuple[UUID, UUID],
) -> None:
    tx_a, tx_b = seeded_transactions
    receipt_a = admin_conn.execute(
        "insert into receipts (user_id, transaction_id) values (%(user_id)s, %(tx_id)s) returning id",
        {"user_id": USER_A, "tx_id": tx_a},
    ).fetchone()["id"]
    receipt_b = admin_conn.execute(
        "insert into receipts (user_id, transaction_id) values (%(user_id)s, %(tx_id)s) returning id",
        {"user_id": USER_B, "tx_id": tx_b},
    ).fetchone()["id"]
    file_a = admin_conn.execute(
        """
        insert into receipt_files (
            user_id, receipt_id, object_key, original_filename, mime_type
        )
        values (%(user_id)s, %(receipt_id)s, %(object_key)s, 'a.png', 'image/png')
        returning id
        """,
        {
            "user_id": USER_A,
            "receipt_id": receipt_a,
            "object_key": f"users/{USER_A}/receipts/{receipt_a}/a.png",
        },
    ).fetchone()["id"]
    file_b = admin_conn.execute(
        """
        insert into receipt_files (
            user_id, receipt_id, object_key, original_filename, mime_type
        )
        values (%(user_id)s, %(receipt_id)s, %(object_key)s, 'b.png', 'image/png')
        returning id
        """,
        {
            "user_id": USER_B,
            "receipt_id": receipt_b,
            "object_key": f"users/{USER_B}/receipts/{receipt_b}/b.png",
        },
    ).fetchone()["id"]
    admin_conn.commit()

    with runtime_conn.transaction():
        set_local_user(runtime_conn, USER_A)
        rows = runtime_conn.execute(
            "select id from receipt_files where id = any(%(ids)s) order by id",
            {"ids": [file_a, file_b]},
        ).fetchall()

    assert [row["id"] for row in rows] == [file_a]
