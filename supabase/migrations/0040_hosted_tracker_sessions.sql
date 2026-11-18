begin;

create table tracker_launch_credentials (
    digest bytea primary key check (octet_length(digest) = 32),
    user_id uuid not null references profiles(id) on delete cascade,
    audience text not null,
    scope text not null check (scope = 'tracker:read'),
    expires_at timestamptz not null
);
create index tracker_launch_owner_expiry on tracker_launch_credentials (user_id, expires_at);

create table tracker_browser_sessions (
    digest bytea primary key check (octet_length(digest) = 32),
    user_id uuid not null references profiles(id) on delete cascade,
    audience text not null,
    scope text not null check (scope = 'tracker:read'),
    expires_at timestamptz not null
);
create index tracker_session_owner_expiry on tracker_browser_sessions (user_id, expires_at);

alter table tracker_launch_credentials enable row level security;
alter table tracker_launch_credentials force row level security;
alter table tracker_browser_sessions enable row level security;
alter table tracker_browser_sessions force row level security;
create policy tracker_launch_own on tracker_launch_credentials
    using (user_id = app.current_user_id()) with check (user_id = app.current_user_id());
create policy tracker_session_own on tracker_browser_sessions
    using (user_id = app.current_user_id()) with check (user_id = app.current_user_id());

do $$
begin
    if exists (select 1 from pg_roles where rolname = 'expense_app') then
        grant select, insert, delete on tracker_launch_credentials, tracker_browser_sessions to expense_app;
    end if;
end;
$$;

commit;
