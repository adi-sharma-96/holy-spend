"""Read-only audit for exact-file and likely business-level receipt duplicates."""

import json

import psycopg
from psycopg.rows import dict_row

from app.config import Settings

EXACT_HASH_SQL = """
select
    request.source_file_sha256,
    count(*)::integer as record_count,
    jsonb_agg(
        jsonb_build_object(
            'transaction_id', transaction.id,
            'status', transaction.status,
            'merchant', coalesce(transaction.merchant_name_normalized, transaction.merchant_name_raw),
            'transaction_date', transaction.transaction_date,
            'currency', transaction.currency,
            'total_amount', transaction.total_amount,
            'completed_at', request.completed_at
        )
        order by (transaction.status = 'confirmed') desc, request.completed_at
    ) as records
from receipt_commit_requests request
join transactions transaction
  on transaction.id = request.transaction_id
 and transaction.user_id = request.user_id
where request.user_id = %(user_id)s
group by request.source_file_sha256
having count(*) > 1
order by count(*) desc, request.source_file_sha256
"""

BUSINESS_CANDIDATE_SQL = """
select
    lower(trim(coalesce(transaction.merchant_name_normalized, transaction.merchant_name_raw, ''))) as merchant_key,
    transaction.transaction_date,
    transaction.currency,
    transaction.total_amount,
    count(*)::integer as record_count,
    jsonb_agg(
        jsonb_build_object(
            'transaction_id', transaction.id,
            'status', transaction.status,
            'source_type', transaction.source_type,
            'item_count', (
                select count(*) from transaction_items item
                where item.user_id = transaction.user_id
                  and item.transaction_id = transaction.id
            ),
            'source_file_sha256', request.source_file_sha256,
            'updated_at', transaction.updated_at
        )
        order by (transaction.status = 'confirmed') desc, transaction.updated_at desc
    ) as records
from transactions transaction
left join receipt_commit_requests request
  on request.user_id = transaction.user_id
 and request.transaction_id = transaction.id
where transaction.user_id = %(user_id)s
  and transaction.source_type = 'receipt'
group by
    lower(trim(coalesce(transaction.merchant_name_normalized, transaction.merchant_name_raw, ''))),
    transaction.transaction_date,
    transaction.currency,
    transaction.total_amount
having count(*) > 1
order by count(*) desc, transaction.transaction_date desc
"""


def main() -> None:
    settings = Settings()
    if settings.database_url is None or settings.owner_user_id is None:
        raise SystemExit("DATABASE_URL and OWNER_USER_ID are required")

    with psycopg.connect(str(settings.database_url), row_factory=dict_row) as conn:
        conn.execute("set transaction read only")
        conn.execute(
            "select set_config('app.current_user_id', %s, true)",
            [str(settings.owner_user_id)],
        )
        exact = conn.execute(EXACT_HASH_SQL, {"user_id": settings.owner_user_id}).fetchall()
        candidates = conn.execute(
            BUSINESS_CANDIDATE_SQL,
            {"user_id": settings.owner_user_id},
        ).fetchall()
        migration_row = conn.execute(
            """
            select exists (
                select 1
                from pg_constraint
                where conname = 'receipt_commit_requests_owner_file_hash_unique'
            ) as applied
            """
        ).fetchone()
        if migration_row is None:
            raise RuntimeError("Migration status query returned no row")
        migration_0012_applied = migration_row["applied"]
        print(
            json.dumps(
                {
                    "owner_user_id": str(settings.owner_user_id),
                    "migration_0012_applied": migration_0012_applied,
                    "exact_hash_duplicates": exact,
                    "business_duplicate_candidates": candidates,
                    "recommended_cleanup": (
                        "Keep confirmed records; delete a matching draft only after explicit approval."
                    ),
                },
                indent=2,
                default=str,
            )
        )
        conn.rollback()


if __name__ == "__main__":
    main()
