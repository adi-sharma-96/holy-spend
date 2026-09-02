\if :{?expense_app_password}
\else
\prompt 'expense_app password: ' expense_app_password
\endif

select case when length(:'expense_app_password') = 0 then 1 / 0 else 1 end;

select format(
    'create role expense_app login password %L nosuperuser nocreatedb nocreaterole noinherit nobypassrls',
    :'expense_app_password'
)
where not exists (
    select 1
    from pg_roles
    where rolname = 'expense_app'
)
\gexec

alter role expense_app
    with login password :'expense_app_password' noinherit;

do $$
declare
    role_attrs record;
begin
    select
        rolcanlogin,
        rolsuper,
        rolcreatedb,
        rolcreaterole,
        rolinherit,
        rolbypassrls
    into role_attrs
    from pg_roles
    where rolname = 'expense_app';

    if role_attrs is null then
        raise exception 'expense_app role was not created';
    end if;

    if role_attrs.rolcanlogin is not true then
        raise exception 'expense_app must have LOGIN';
    end if;

    if role_attrs.rolsuper
        or role_attrs.rolcreatedb
        or role_attrs.rolcreaterole
        or role_attrs.rolbypassrls
    then
        raise exception
            'expense_app has unsafe role attributes. Expected NOSUPERUSER, NOCREATEDB, NOCREATEROLE, NOBYPASSRLS.';
    end if;

    if role_attrs.rolinherit then
        raise exception 'expense_app must be NOINHERIT';
    end if;
end;
$$;

alter role expense_app set search_path = public, app;

grant usage on schema public to expense_app;

do $$
begin
    if exists (select 1 from pg_namespace where nspname = 'app') then
        grant usage on schema app to expense_app;
    end if;
end;
$$;

do $$
declare
    type_name text;
begin
    foreach type_name in array array[
        'transaction_status',
        'transaction_type',
        'source_type',
        'adjustment_type',
        'validation_severity',
        'alias_source',
        'receipt_file_upload_status',
        'receipt_cleanup_status',
        'taxonomy_version_status',
        'taxonomy_selection_mode',
        'taxonomy_classification_source',
        'taxonomy_review_status',
        'transaction_classification_mode',
        'transaction_item_role',
        'ingestion_method',
        'purchase_channel'
    ]
    loop
        if exists (
            select 1
            from pg_type t
            join pg_namespace n on n.oid = t.typnamespace
            where n.nspname = 'public'
              and t.typname = type_name
        ) then
            execute format('grant usage on type public.%I to expense_app', type_name);
        end if;
    end loop;
end;
$$;

do $$
declare
    table_name text;
begin
    foreach table_name in array array[
        'profiles',
        'merchants',
        'product_concepts',
        'product_variants',
        'transactions',
        'receipts',
        'receipt_files',
        'transaction_items',
        'transaction_item_themes',
        'transaction_adjustments',
        'user_product_aliases',
        'validation_issues',
        'user_corrections',
        'audit_events',
        'expense_mutation_requests',
        'receipt_ingestion_requests',
        'receipt_commit_requests',
        'receipt_storage_cleanup_jobs',
        'transaction_item_classification_history',
        'transaction_item_facets',
        'nutrition_lookups',
        'email_ingestion_log'
    ]
    loop
        if to_regclass(format('public.%I', table_name)) is not null then
            execute format('grant select, insert, update, delete on table public.%I to expense_app', table_name);
            execute format('alter table public.%I force row level security', table_name);
        end if;
    end loop;
end;
$$;

do $$
declare
    table_name text;
begin
    foreach table_name in array array[
        'categories',
        'themes',
        'product_concept_themes',
        'product_variant_themes',
        'taxonomy_versions',
        'taxonomy_nodes',
        'taxonomy_node_closure',
        'taxonomy_synonyms',
        'taxonomy_redirects',
        'taxonomy_facets',
        'taxonomy_facet_values',
        'legacy_category_taxonomy_map'
    ]
    loop
        if to_regclass(format('public.%I', table_name)) is not null then
            execute format('grant select on table public.%I to expense_app', table_name);
            execute format('alter table public.%I force row level security', table_name);
        end if;
    end loop;
end;
$$;

do $$
begin
    if to_regclass('public.personal_access_tokens') is not null then
        revoke all on table public.personal_access_tokens from expense_app;
        grant insert, update on table public.personal_access_tokens to expense_app;
        alter table public.personal_access_tokens force row level security;
    end if;

    if to_regclass('public.oauth_refresh_tokens') is not null then
        revoke all on table public.oauth_refresh_tokens from expense_app;
        grant insert, update on table public.oauth_refresh_tokens to expense_app;
        alter table public.oauth_refresh_tokens force row level security;
    end if;
end;
$$;

-- The current schema uses UUID defaults and does not require sequence privileges.

do $$
begin
    if to_regprocedure('app.current_user_id()') is not null then
        grant execute on function app.current_user_id() to expense_app;
    end if;

    if to_regprocedure('app.authenticate_pat(text)') is not null then
        grant execute on function app.authenticate_pat(text) to expense_app;
    end if;

    if to_regprocedure('app.authenticate_oauth_refresh_token(text)') is not null then
        grant execute on function app.authenticate_oauth_refresh_token(text) to expense_app;
    end if;
end;
$$;

revoke create on schema public from expense_app;

do $$
begin
    if exists (select 1 from pg_namespace where nspname = 'app') then
        revoke create on schema app from expense_app;
    end if;
end;
$$;
