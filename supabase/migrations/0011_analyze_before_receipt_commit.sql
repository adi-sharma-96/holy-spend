-- Receipt extraction is intentionally non-persistent. This migration only
-- records completed commit idempotency and retryable storage cleanup work.

create table receipt_commit_requests (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references profiles(id) on delete cascade,
    client_request_id text not null,
    request_hash text not null,
    source_file_sha256 text not null,
    transaction_id uuid not null references transactions(id) on delete cascade,
    receipt_id uuid not null references receipts(id) on delete cascade,
    receipt_file_id uuid not null references receipt_files(id) on delete cascade,
    object_key text not null,
    result_version bigint not null default 1,
    completed_at timestamptz not null default now(),
    constraint receipt_commit_requests_client_id_not_blank
        check (length(trim(client_request_id)) between 8 and 96),
    constraint receipt_commit_requests_hash_shape
        check (request_hash ~ '^[a-f0-9]{64}$'),
    constraint receipt_commit_requests_file_hash_shape
        check (source_file_sha256 ~ '^[a-f0-9]{64}$'),
    constraint receipt_commit_requests_result_version_positive
        check (result_version > 0),
    unique (user_id, client_request_id),
    unique (user_id, object_key)
);

create index receipt_commit_requests_transaction_idx
    on receipt_commit_requests(user_id, transaction_id);
create index receipt_commit_requests_file_idx
    on receipt_commit_requests(user_id, source_file_sha256);

alter table receipt_commit_requests enable row level security;
alter table receipt_commit_requests force row level security;

create policy receipt_commit_requests_crud_own on receipt_commit_requests
    for all
    using (user_id = app.current_user_id())
    with check (user_id = app.current_user_id());

create type receipt_cleanup_status as enum ('pending', 'retrying', 'completed');

create table receipt_storage_cleanup_jobs (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references profiles(id) on delete cascade,
    bucket_name text not null,
    object_key text not null,
    reason text not null,
    status receipt_cleanup_status not null default 'pending',
    attempt_count integer not null default 0,
    last_error text,
    next_attempt_at timestamptz not null default now(),
    created_at timestamptz not null default now(),
    completed_at timestamptz,
    constraint receipt_storage_cleanup_jobs_bucket_not_blank
        check (length(trim(bucket_name)) > 0),
    constraint receipt_storage_cleanup_jobs_object_key_not_blank
        check (length(trim(object_key)) > 0),
    constraint receipt_storage_cleanup_jobs_reason_not_blank
        check (length(trim(reason)) > 0),
    constraint receipt_storage_cleanup_jobs_attempt_count_nonnegative
        check (attempt_count >= 0),
    constraint receipt_storage_cleanup_jobs_terminal_timestamp
        check (
            (status = 'completed' and completed_at is not null)
            or (status <> 'completed' and completed_at is null)
        ),
    unique (user_id, bucket_name, object_key)
);

create index receipt_storage_cleanup_jobs_due_idx
    on receipt_storage_cleanup_jobs(user_id, next_attempt_at)
    where status in ('pending', 'retrying');

alter table receipt_storage_cleanup_jobs enable row level security;
alter table receipt_storage_cleanup_jobs force row level security;

create policy receipt_storage_cleanup_jobs_crud_own on receipt_storage_cleanup_jobs
    for all
    using (user_id = app.current_user_id())
    with check (user_id = app.current_user_id());

do $$
begin
    if exists (select 1 from pg_roles where rolname = 'expense_app') then
        grant usage on type receipt_cleanup_status to expense_app;
        grant select, insert, update, delete on table receipt_commit_requests to expense_app;
        grant select, insert, update, delete on table receipt_storage_cleanup_jobs to expense_app;
    end if;
end;
$$;
