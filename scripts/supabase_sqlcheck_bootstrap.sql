-- Minimal Supabase Auth contract for disposable vanilla-Postgres migration tests.
-- This file is never applied to Supabase itself.

create schema if not exists auth;

do $$
begin
    if not exists (select 1 from pg_roles where rolname = 'authenticated') then
        create role authenticated nologin;
    end if;
end;
$$;

create table if not exists auth.users (
    id uuid primary key,
    email text,
    created_at timestamptz not null default now()
);

create or replace function auth.uid()
returns uuid
language sql
stable
as $$
    select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid
$$;
