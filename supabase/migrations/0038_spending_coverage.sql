begin;

create table spending_coverage_declarations (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references profiles(id) on delete cascade,
    currency text not null check (currency ~ '^[A-Z]{3}$'),
    start_date date not null,
    end_date date,
    kind text not null check (kind in ('tracking', 'complete_import', 'gap')),
    reason text not null check (length(btrim(reason)) between 1 and 500),
    recorded_at timestamptz not null default clock_timestamp(),
    check (end_date >= start_date),
    check (kind = 'tracking' or end_date is not null)
);
create index spending_coverage_owner_dates on spending_coverage_declarations (user_id, currency, start_date);

create table spending_classification_reviews (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references profiles(id) on delete cascade,
    transaction_id uuid not null,
    transaction_revision timestamptz not null,
    classification text not null check (classification in ('ordinary', 'exceptional', 'unreviewed')),
    reason text not null check (length(btrim(reason)) between 1 and 500),
    recorded_at timestamptz not null default clock_timestamp(),
    foreign key (transaction_id, user_id) references transactions(id, user_id) on delete cascade
);
create index spending_reviews_owner_revision
    on spending_classification_reviews (user_id, transaction_id, transaction_revision, recorded_at desc, id desc);

alter table spending_coverage_declarations enable row level security;
alter table spending_coverage_declarations force row level security;
alter table spending_classification_reviews enable row level security;
alter table spending_classification_reviews force row level security;
create policy spending_coverage_own on spending_coverage_declarations
    using (user_id = app.current_user_id()) with check (user_id = app.current_user_id());
create policy spending_reviews_own on spending_classification_reviews
    using (user_id = app.current_user_id()) with check (user_id = app.current_user_id());

do $$
begin
    if exists (select 1 from pg_roles where rolname = 'expense_app') then
        grant select, insert, delete on spending_coverage_declarations to expense_app;
        grant select, insert on spending_classification_reviews to expense_app;
    end if;
end;
$$;

commit;
