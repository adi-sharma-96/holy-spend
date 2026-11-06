-- WS3: client-driven, owner-scoped receipt workflow ledger.
alter table receipt_storage_cleanup_jobs
    add column source_sha256 text,
    add column active_attempt_ids uuid[] not null default '{}'::uuid[],
    add constraint receipt_cleanup_source_hash_shape
        check (source_sha256 is null or source_sha256 ~ '^[a-f0-9]{64}$');

-- The original generic trigger used now(), which is fixed for the whole
-- transaction. Child edits in one transaction could therefore reuse a preview
-- revision. Make transaction revisions strictly advance on every update.
create function set_transaction_revision() returns trigger language plpgsql as $$
begin
    new.updated_at := greatest(clock_timestamp(), old.updated_at + interval '1 microsecond');
    return new;
end $$;
drop trigger transactions_set_updated_at on transactions;
create trigger transactions_set_updated_at before update on transactions
    for each row execute function set_transaction_revision();

create table receipt_batches (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references profiles(id) on delete cascade,
    client_batch_id text not null,
    authorization_source text not null,
    confirm_authorized boolean not null default false,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (user_id, client_batch_id),
    check (length(client_batch_id) between 8 and 96),
    check (length(authorization_source) between 3 and 200)
);
alter table receipt_batches add constraint receipt_batches_id_owner_unique unique (id, user_id);
alter table transactions add constraint transactions_id_owner_unique unique (id, user_id);
alter table receipt_files add constraint receipt_files_id_owner_unique unique (id, user_id);

create table receipt_batch_attachments (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references profiles(id) on delete cascade,
    batch_id uuid not null references receipt_batches(id) on delete cascade,
    client_attachment_id text not null,
    operation_id text not null,
    ordinal integer not null,
    payload_fingerprint text,
    content_sha256 text,
    provider_key text,
    order_key text,
    status text not null default 'extraction_pending',
    attempt_count integer not null default 0,
    retry_reason text,
    distinct_decision_source text,
    transaction_id uuid references transactions(id) on delete set null,
    candidate_transaction_id uuid references transactions(id) on delete set null,
    receipt_file_id uuid references receipt_files(id) on delete set null,
    unresolved_issues jsonb not null default '[]'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (user_id, batch_id, client_attachment_id),
    unique (user_id, operation_id),
    foreign key (batch_id, user_id) references receipt_batches(id, user_id) on delete cascade,
    foreign key (transaction_id, user_id) references transactions(id, user_id),
    foreign key (candidate_transaction_id, user_id) references transactions(id, user_id),
    foreign key (receipt_file_id, user_id) references receipt_files(id, user_id),
    check (length(client_attachment_id) between 8 and 96),
    check (length(operation_id) between 8 and 96),
    check (payload_fingerprint is null or payload_fingerprint ~ '^[a-f0-9]{64}$'),
    check (content_sha256 is null or content_sha256 ~ '^[a-f0-9]{64}$'),
    check (attempt_count between 0 and 5),
    check (ordinal between 0 and 19),
    check (status in ('extraction_pending', 'extracting', 'clarification_needed',
        'draft_saved', 'confirmed', 'exact_duplicate', 'possible_duplicate',
        'retryable_failure', 'terminal_failure'))
);
create index receipt_batch_attachments_batch_idx on receipt_batch_attachments(user_id, batch_id, created_at);
create index receipt_batch_attachments_hash_idx on receipt_batch_attachments(user_id, content_sha256);
create index receipt_batch_attachments_order_idx on receipt_batch_attachments(user_id, provider_key, order_key)
    where order_key is not null;

create table receipt_document_versions (
    receipt_file_id uuid primary key references receipt_files(id) on delete cascade,
    user_id uuid not null references profiles(id) on delete cascade,
    transaction_id uuid not null references transactions(id) on delete cascade,
    document_kind text not null,
    provider_order_key text,
    occurred_at timestamptz,
    supersedes_file_id uuid references receipt_files(id) on delete set null,
    extracted_facts jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    foreign key (transaction_id, user_id) references transactions(id, user_id) on delete cascade,
    foreign key (receipt_file_id, user_id) references receipt_files(id, user_id) on delete cascade,
    check (document_kind in ('original', 'revision', 'adjustment', 'refund', 'other'))
);
create index receipt_document_versions_order_idx on receipt_document_versions(user_id, transaction_id, occurred_at, created_at);

insert into receipt_document_versions (receipt_file_id, user_id, transaction_id, document_kind)
select f.id, f.user_id, r.transaction_id, 'original'
from receipt_files f join receipts r on r.id=f.receipt_id
where f.upload_status='uploaded';

-- A document event is evidence on a purchase, never another purchase amount.
create table receipt_document_events (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references profiles(id) on delete cascade,
    transaction_id uuid not null references transactions(id) on delete cascade,
    receipt_file_id uuid references receipt_files(id) on delete set null,
    source_key text not null,
    event_kind text not null,
    amount numeric(12,2),
    currency char(3) not null,
    occurred_at timestamptz,
    item_id uuid references transaction_items(id) on delete set null,
    source_item_id uuid,
    item_disposition text not null default 'unknown',
    attribution_status text not null default 'unknown',
    source_facts jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    unique (user_id, transaction_id, source_key),
    foreign key (transaction_id, user_id) references transactions(id, user_id) on delete cascade,
    foreign key (receipt_file_id, user_id) references receipt_files(id, user_id),
    check (event_kind in ('original_charge', 'order_adjustment', 'tip',
        'purchase_refund', 'wallet_top_up', 'wallet_refund', 'wallet_use', 'transfer')),
    check (item_disposition in ('kept', 'returned', 'unknown')),
    check (attribution_status in ('known', 'unknown')),
    check (currency = upper(currency))
);
create index receipt_document_events_transaction_idx on receipt_document_events(user_id, transaction_id, occurred_at, id);

alter table receipt_batches enable row level security;
alter table receipt_batches force row level security;
create policy receipt_batches_own on receipt_batches for all
    using (user_id = app.current_user_id()) with check (user_id = app.current_user_id());
alter table receipt_batch_attachments enable row level security;
alter table receipt_batch_attachments force row level security;
create policy receipt_batch_attachments_own on receipt_batch_attachments for all
    using (user_id = app.current_user_id()) with check (user_id = app.current_user_id());
alter table receipt_document_events enable row level security;
alter table receipt_document_events force row level security;
create policy receipt_document_events_own on receipt_document_events for all
    using (user_id = app.current_user_id()) with check (user_id = app.current_user_id());
alter table receipt_document_versions enable row level security;
alter table receipt_document_versions force row level security;
create policy receipt_document_versions_own on receipt_document_versions for all
    using (user_id = app.current_user_id()) with check (user_id = app.current_user_id());

create function assert_receipt_document_owner() returns trigger language plpgsql as $$
begin
    if new.receipt_file_id is not null and not exists (
        select 1 from receipt_files f join receipts r on r.id=f.receipt_id
        where f.id=new.receipt_file_id and f.user_id=new.user_id
          and r.transaction_id=new.transaction_id and r.user_id=new.user_id
    ) then
        raise exception 'Document file must belong to its purchase';
    end if;
    if tg_table_name='receipt_document_events' then
        if new.item_id is not null and not exists (
            select 1 from transaction_items i where i.id=new.item_id
              and i.transaction_id=new.transaction_id and i.user_id=new.user_id
        ) then
            raise exception 'Document item must belong to its purchase';
        end if;
    end if;
    return new;
end $$;
create trigger ws3_version_owner before insert or update on receipt_document_versions
    for each row execute function assert_receipt_document_owner();
create trigger ws3_event_owner before insert or update on receipt_document_events
    for each row execute function assert_receipt_document_owner();

-- Every child mutation invalidates an old reviewed revision, including direct
-- item/adjustment/document/file edits outside the application service.
-- Serialize item and adjustment writes with confirmation. Application paths
-- acquire this parent lock first; the trigger also rejects unapproved direct
-- SQL writes after a concurrent confirmation has committed.
create function guard_receipt_workflow_child_edit() returns trigger language plpgsql as $$
declare parent_status text;
begin
    select status into parent_status from transactions
    where id = case when tg_op = 'DELETE' then old.transaction_id else new.transaction_id end
      and user_id = case when tg_op = 'DELETE' then old.user_id else new.user_id end
    for update;
    if current_user = 'expense_app' and parent_status = 'confirmed'
       and nullif(btrim(current_setting('app.confirmed_child_edit_reason', true)), '') is null then
        raise exception 'Editing a confirmed purchase requires an approved correction';
    end if;
    if tg_op = 'DELETE' then return old; end if;
    return new;
end $$;
create trigger ws3_item_edit_guard before insert or update or delete on transaction_items
    for each row execute function guard_receipt_workflow_child_edit();
create trigger ws3_adjustment_edit_guard before insert or update or delete on transaction_adjustments
    for each row execute function guard_receipt_workflow_child_edit();

create function touch_receipt_workflow_transaction() returns trigger language plpgsql as $$
declare target_id uuid;
begin
    if tg_table_name = 'receipt_files' then
        if tg_op = 'DELETE' then
            select transaction_id into target_id from receipts where id = old.receipt_id;
        else
            select transaction_id into target_id from receipts where id = new.receipt_id;
        end if;
    else
        if tg_op = 'DELETE' then
            target_id := old.transaction_id;
        else
            target_id := new.transaction_id;
        end if;
    end if;
    if tg_op = 'DELETE' then
        update transactions set updated_at = clock_timestamp()
        where id = target_id and user_id = old.user_id;
        return old;
    end if;
    update transactions set updated_at = clock_timestamp()
    where id = target_id and user_id = new.user_id;
    return new;
end $$;
create trigger ws3_item_revision after insert or update or delete on transaction_items
    for each row execute function touch_receipt_workflow_transaction();
create trigger ws3_adjustment_revision after insert or update or delete on transaction_adjustments
    for each row execute function touch_receipt_workflow_transaction();
create trigger ws3_file_revision after insert or update or delete on receipt_files
    for each row execute function touch_receipt_workflow_transaction();
create trigger ws3_document_revision after insert or update or delete on receipt_document_events
    for each row execute function touch_receipt_workflow_transaction();
create trigger ws3_version_revision after insert or update or delete on receipt_document_versions
    for each row execute function touch_receipt_workflow_transaction();

do $$ begin
    if exists (select 1 from pg_roles where rolname = 'expense_app') then
        grant select, insert, update, delete on receipt_batches, receipt_batch_attachments,
            receipt_document_events, receipt_document_versions to expense_app;
    end if;
end $$;
