-- Tracking table for the scheduled email-receipt-ingestion task (see project memory
-- email-receipt-ingestion-design.md). One row per Gmail message this account's owner
-- has ever had processed, keyed by Gmail's own immutable message id - lets the
-- scheduled task ask "have I already looked at this email" without relying on Gmail
-- labels (unverified whether the connector can even write those) or Cursor's own
-- automation memory (already proven unreliable elsewhere this project).

create table email_ingestion_log (
    id uuid primary key default gen_random_uuid(),
    owner_user_id uuid not null references auth.users(id) on delete cascade,
    message_id text not null,
    status text not null check (status in ('drafted', 'flagged', 'not_a_receipt')),
    transaction_id uuid references transactions(id) on delete set null,
    note text,
    processed_at timestamptz not null default now(),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (owner_user_id, message_id)
);

comment on column email_ingestion_log.message_id is
    'Gmail''s own immutable message id, not the forwarded email''s subject or a derived key.';
comment on column email_ingestion_log.status is
    'drafted: a transaction was saved for this email. flagged: a real receipt needing '
    'itemization the email could not provide - noted for manual upload, no draft created. '
    'not_a_receipt: not a purchase confirmation at all (marketing, a shipping-status update '
    'with no new pricing, etc).';
comment on column email_ingestion_log.transaction_id is
    'Set only when status = drafted. Nullable and ON DELETE SET NULL since deleting the '
    'transaction later should not be blocked by this log row.';

alter table email_ingestion_log enable row level security;

create policy email_ingestion_log_select_own on email_ingestion_log
    for select using (owner_user_id = app.current_user_id());

create policy email_ingestion_log_insert_own on email_ingestion_log
    for insert with check (owner_user_id = app.current_user_id());

create policy email_ingestion_log_update_own on email_ingestion_log
    for update using (owner_user_id = app.current_user_id())
    with check (owner_user_id = app.current_user_id());

create trigger email_ingestion_log_set_updated_at
    before update on email_ingestion_log
    for each row execute function set_updated_at();
