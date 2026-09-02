"""Read-only aggregate audit for headless drafts and receipt-linkage anomalies."""

import json
from collections import Counter

import psycopg

from app.config import Settings

AUDIT_SQL = """
select
    t.id,
    t.status,
    t.source_type,
    t.transaction_date,
    t.total_amount,
    r.id as receipt_id,
    count(distinct ti.id)::integer as item_count,
    count(distinct rf.id)::integer as file_count,
    array_remove(
        array[
            case
                when t.status = 'draft'
                 and coalesce(t.total_amount, 0) = 0
                 and nullif(
                    trim(coalesce(t.merchant_name_raw, t.merchant_name_normalized, '')),
                    ''
                 ) is null
                 and count(distinct ti.id) = 0
                    then 'headless_zero_draft'
            end,
            case
                when t.source_type = 'receipt' and r.id is null
                    then 'receipt_source_without_receipt'
            end,
            case
                when r.id is not null and count(distinct rf.id) = 0
                    then 'receipt_without_file'
            end
        ],
        null
    ) as reasons
from transactions t
left join receipts r
    on r.transaction_id = t.id
   and r.user_id = t.user_id
left join transaction_items ti
    on ti.transaction_id = t.id
   and ti.user_id = t.user_id
left join receipt_files rf
    on rf.receipt_id = r.id
   and rf.user_id = t.user_id
   and rf.deleted_at is null
where t.user_id = %(user_id)s
group by
    t.id,
    t.status,
    t.source_type,
    t.transaction_date,
    t.total_amount,
    r.id
having (
    t.status = 'draft'
    and coalesce(t.total_amount, 0) = 0
    and nullif(trim(coalesce(t.merchant_name_raw, t.merchant_name_normalized, '')), '') is null
    and count(distinct ti.id) = 0
) or (
    t.source_type = 'receipt' and r.id is null
) or (
    r.id is not null and count(distinct rf.id) = 0
)
order by t.transaction_date, t.id
"""


def main() -> None:
    settings = Settings()
    if settings.database_url is None or settings.owner_user_id is None:
        raise SystemExit("DATABASE_URL and OWNER_USER_ID are required")

    with psycopg.connect(str(settings.database_url)) as conn:
        conn.execute("set transaction read only")
        conn.execute(
            "select set_config('app.current_user_id', %s, true)",
            [str(settings.owner_user_id)],
        )
        rows = conn.execute(AUDIT_SQL, {"user_id": settings.owner_user_id}).fetchall()
        reasons = Counter(reason for row in rows for reason in row[8])
        print(json.dumps({"record_count": len(rows), "by_reason": reasons}, indent=2))
        conn.rollback()


if __name__ == "__main__":
    main()
