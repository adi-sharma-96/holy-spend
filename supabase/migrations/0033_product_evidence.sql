-- Expanded product evidence. Existing non-null fields remain unverified: the
-- empty provenance object is intentional and must not be backfilled as observed.
alter table transaction_items
    add column product_identity_key text,
    add column product_type_key text,
    add column field_provenance jsonb not null default '{}'::jsonb,
    add column evidence_revision bigint not null default 1;

alter table transaction_items add constraint transaction_items_field_provenance_object
    check (jsonb_typeof(field_provenance) = 'object');

create function app.bump_item_evidence_revision() returns trigger
language plpgsql as $$
begin
    new.evidence_revision := old.evidence_revision + 1;
    return new;
end;
$$;

create trigger bump_item_evidence_revision before update on transaction_items
    for each row execute function app.bump_item_evidence_revision();

-- Review decisions are revision-bound. A later edit creates a new reviewable
-- issue; a rejected/deferred issue at the same revision stays suppressed.
create table product_review_decisions (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    -- Keep the reviewed item UUID even if a confirmed expense is later replaced.
    item_id uuid not null,
    issue_key text not null,
    evidence_revision bigint not null,
    decision text not null check (decision in ('confirmed', 'rejected', 'deferred')),
    reason text not null,
    operation_id uuid not null,
    request_hash text not null check (request_hash ~ '^[0-9a-f]{64}$'),
    created_at timestamptz not null default now(),
    unique (user_id, operation_id, item_id),
    unique (user_id, item_id, issue_key, evidence_revision)
);

create table product_correction_events (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    -- Correction history is append-only across later expense replacement.
    item_id uuid not null,
    operation_id uuid not null,
    request_hash text not null check (request_hash ~ '^[0-9a-f]{64}$'),
    before_value jsonb not null,
    after_value jsonb not null,
    applied_revision bigint not null,
    reason text not null,
    reverses_event_id uuid references product_correction_events(id),
    created_at timestamptz not null default now(),
    unique (user_id, operation_id, item_id)
);

create index product_review_decisions_item_idx on product_review_decisions(user_id, item_id);
create index product_correction_events_item_idx on product_correction_events(user_id, item_id, created_at);

alter table product_review_decisions enable row level security;
alter table product_review_decisions force row level security;
alter table product_correction_events enable row level security;
alter table product_correction_events force row level security;

create policy product_review_decisions_own on product_review_decisions
    for all using (user_id = app.current_user_id()) with check (user_id = app.current_user_id());
create policy product_correction_events_own on product_correction_events
    for all using (user_id = app.current_user_id()) with check (user_id = app.current_user_id());

revoke all on product_review_decisions, product_correction_events from public;
do $$ begin
    if exists (select 1 from pg_roles where rolname = 'expense_app') then
        grant select, insert, update, delete on product_review_decisions to expense_app;
        grant select, insert, update, delete on product_correction_events to expense_app;
    end if;
end $$;
