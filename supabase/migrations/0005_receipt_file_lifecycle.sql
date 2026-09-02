create type receipt_file_upload_status as enum ('pending', 'uploaded', 'failed', 'deleted');

alter table receipt_files
    rename column filename to original_filename;

alter table receipt_files
    add column storage_provider text not null default 'supabase',
    add column bucket_name text not null default 'receipt-originals',
    add column upload_status receipt_file_upload_status not null default 'pending',
    add column created_at timestamptz not null default now(),
    add column deleted_at timestamptz;

update receipt_files
set upload_status = 'uploaded'
where uploaded_at is not null;

alter table receipt_files
    alter column uploaded_at drop not null,
    alter column uploaded_at drop default,
    add constraint receipt_files_storage_provider_check
        check (storage_provider = 'supabase'),
    add constraint receipt_files_bucket_name_not_blank
        check (length(trim(bucket_name)) > 0),
    add constraint receipt_files_object_key_not_blank
        check (length(trim(object_key)) > 0),
    add constraint receipt_files_upload_status_timestamps
        check (
            (upload_status = 'pending' and uploaded_at is null and deleted_at is null)
            or (upload_status = 'uploaded' and uploaded_at is not null and deleted_at is null)
            or (upload_status = 'failed' and uploaded_at is null and deleted_at is null)
            or (upload_status = 'deleted' and deleted_at is not null)
        );

create index receipt_files_active_receipt_idx
    on receipt_files(user_id, receipt_id, created_at)
    where deleted_at is null;

create function assert_receipt_file_object_key_shape()
returns trigger
language plpgsql
as $$
declare
    expected_prefix text;
begin
    expected_prefix := format(
        'users/%s/receipts/%s/',
        new.user_id::text,
        new.receipt_id::text
    );

    if new.object_key not like expected_prefix || '%' then
        raise exception 'Receipt file object_key must match its user and receipt path';
    end if;

    if new.object_key like '%/../%'
        or new.object_key like '../%'
        or new.object_key like '%/..'
        or new.object_key like '%\\%'
    then
        raise exception 'Receipt file object_key contains an invalid path segment';
    end if;

    return new;
end;
$$;

create trigger receipt_files_assert_object_key_shape
    before insert or update of user_id, receipt_id, object_key on receipt_files
    for each row execute function assert_receipt_file_object_key_shape();

alter table transactions
    drop constraint transactions_merchant_present;

alter table transactions
    add constraint transactions_merchant_present check (
        merchant_id is not null
        or merchant_name_raw is not null
        or source_type in ('manual', 'receipt')
    );

alter table receipt_files force row level security;
