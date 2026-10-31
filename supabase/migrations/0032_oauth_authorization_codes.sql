-- Short-lived OAuth codes are shared across gateway instances. The 32-byte
-- random code is represented only by its SHA-256 digest.
create table oauth_authorization_codes (
    code_hash text primary key check (code_hash ~ '^[0-9a-f]{64}$'),
    user_id uuid not null references auth.users(id) on delete cascade,
    client_id text not null,
    redirect_uri text not null,
    redirect_uri_provided_explicitly boolean not null,
    code_challenge text not null,
    scopes text[] not null,
    resource text,
    issued_at timestamptz not null default now(),
    expires_at timestamptz not null,
    constraint oauth_authorization_codes_expiry_check check (expires_at > issued_at)
);

create index oauth_authorization_codes_expires_at_idx on oauth_authorization_codes(expires_at);

alter table oauth_authorization_codes enable row level security;
alter table oauth_authorization_codes force row level security;

create policy oauth_authorization_codes_select_own on oauth_authorization_codes
    for select using (user_id = app.current_user_id());
create policy oauth_authorization_codes_insert_own on oauth_authorization_codes
    for insert with check (user_id = app.current_user_id());
create policy oauth_authorization_codes_delete_own on oauth_authorization_codes
    for delete using (user_id = app.current_user_id());

revoke all on table oauth_authorization_codes from public;
do $$
begin
    if exists (select 1 from pg_roles where rolname = 'expense_app') then
        grant select, insert, delete on table oauth_authorization_codes to expense_app;
    end if;
end;
$$;
