-- Exact receipt bytes are the durable idempotency key. Run
-- `python -m scripts.audit_receipt_duplicates` and resolve every exact_hash
-- duplicate before applying this migration.

do $$
begin
    if exists (
        select 1
        from receipt_commit_requests
        group by user_id, source_file_sha256
        having count(*) > 1
    ) then
        raise exception using
            message = 'receipt_commit_requests contains owner/hash duplicates',
            hint = 'Run scripts.audit_receipt_duplicates and clean approved duplicate drafts first.';
    end if;
end;
$$;

drop index if exists receipt_commit_requests_file_idx;

create unique index receipt_commit_requests_owner_file_hash_uidx
    on receipt_commit_requests(user_id, source_file_sha256);

alter table receipt_commit_requests
    add constraint receipt_commit_requests_owner_file_hash_unique
    unique using index receipt_commit_requests_owner_file_hash_uidx;

comment on constraint receipt_commit_requests_owner_file_hash_unique
    on receipt_commit_requests is
    'Prevents retries or re-uploads of identical receipt bytes from creating another transaction for one owner.';
