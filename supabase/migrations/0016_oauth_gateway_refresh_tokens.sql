-- Storage for the MCP gateway's OAuth 2.1 authorization server (app/oauth_provider.py).
-- Access tokens issued by the flow are real personal_access_tokens rows (no new
-- concept there); this table only tracks the refresh token half of each pair so
-- the running app can rotate both at request time under RLS, mirroring the
-- select-none/insert-own/update-own shape already used for personal_access_tokens.

create table oauth_refresh_tokens (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    token_hash text not null unique,
    pat_token_id uuid not null references personal_access_tokens(id) on delete cascade,
    expires_at timestamptz not null,
    revoked_at timestamptz,
    created_at timestamptz not null default now()
);

create index oauth_refresh_tokens_user_idx on oauth_refresh_tokens(user_id);
create index oauth_refresh_tokens_pat_token_idx on oauth_refresh_tokens(pat_token_id);

alter table oauth_refresh_tokens enable row level security;

create policy oauth_refresh_tokens_select_none on oauth_refresh_tokens
    for select using (false);

create policy oauth_refresh_tokens_insert_own on oauth_refresh_tokens
    for insert with check (user_id = app.current_user_id());

create policy oauth_refresh_tokens_update_own on oauth_refresh_tokens
    for update using (user_id = app.current_user_id()) with check (user_id = app.current_user_id());

-- Mirrors app.authenticate_pat: security definer so the restricted runtime role
-- (blocked from select by oauth_refresh_tokens_select_none) can still look a
-- presented refresh token up by hash without a broader read grant.
create function app.authenticate_oauth_refresh_token(p_token_hash text)
returns table (
    refresh_token_id uuid,
    user_id uuid,
    pat_token_id uuid
)
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
    return query
    select rt.id, rt.user_id, rt.pat_token_id
    from oauth_refresh_tokens rt
    where rt.token_hash = p_token_hash
      and rt.revoked_at is null
      and rt.expires_at > now();
end;
$$;

revoke all on function app.authenticate_oauth_refresh_token(text) from public;
