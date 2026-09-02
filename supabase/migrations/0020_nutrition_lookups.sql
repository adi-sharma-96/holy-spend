-- Nightly Open Food Facts nutrition sync. One lifecycle table serves as both the
-- queue (status = 'pending' rows, ordered by next_attempt_at) and the result cache
-- (status = 'matched' rows). Identity is brand + product name only (app.nutrition_
-- identity), not product_concepts/product_variants, since nothing populates those
-- on ingestion today (see 0017_transaction_item_brand.sql).

create table nutrition_lookups (
    id uuid primary key default gen_random_uuid(),
    owner_user_id uuid not null references auth.users(id) on delete cascade,
    identity_key text not null,
    product_name text not null,
    brand text,
    status text not null default 'pending'
        check (status in ('pending', 'matched', 'no_match', 'error')),
    attempts int not null default 0,
    next_attempt_at timestamptz not null default now(),
    off_code text,
    off_product_name text,
    nutriments jsonb,
    nutriscore_grade text,
    nova_group int,
    match_confidence numeric,
    last_error text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (owner_user_id, identity_key)
);

create index nutrition_lookups_pending_idx on nutrition_lookups (owner_user_id, next_attempt_at)
    where status = 'pending';

alter table nutrition_lookups enable row level security;

create policy nutrition_lookups_select_own on nutrition_lookups
    for select using (owner_user_id = auth.uid());

create policy nutrition_lookups_insert_own on nutrition_lookups
    for insert with check (owner_user_id = auth.uid());

create policy nutrition_lookups_update_own on nutrition_lookups
    for update using (owner_user_id = auth.uid()) with check (owner_user_id = auth.uid());

create trigger nutrition_lookups_set_updated_at
    before update on nutrition_lookups
    for each row execute function set_updated_at();
