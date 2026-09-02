alter table transactions
    add column notes text,
    add constraint transactions_notes_length
        check (notes is null or length(notes) <= 4000);

create table expense_mutation_requests (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references profiles(id) on delete cascade,
    client_request_id text not null,
    request_hash text not null,
    transaction_id uuid not null references transactions(id) on delete cascade,
    created_at timestamptz not null default now(),
    constraint expense_mutation_requests_client_request_id_not_blank
        check (length(trim(client_request_id)) between 8 and 128),
    constraint expense_mutation_requests_request_hash_shape
        check (request_hash ~ '^[a-f0-9]{64}$'),
    unique (user_id, client_request_id)
);

create index expense_mutation_requests_transaction_idx
    on expense_mutation_requests(user_id, transaction_id);

alter table expense_mutation_requests enable row level security;
alter table expense_mutation_requests force row level security;

create policy expense_mutation_requests_crud_own on expense_mutation_requests
    for all
    using (user_id = app.current_user_id())
    with check (user_id = app.current_user_id());

do $$
begin
    if exists (select 1 from pg_roles where rolname = 'expense_app') then
        grant select, insert, update, delete on table expense_mutation_requests to expense_app;
    end if;
end;
$$;
