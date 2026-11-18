\if :{?expense_tracker_reader_password}
\else
\prompt 'expense_tracker_reader password: ' expense_tracker_reader_password
\endif

select case when length(:'expense_tracker_reader_password') = 0 then 1 / 0 else 1 end;

begin;

select format(
    'create role expense_tracker_reader login password %L nosuperuser nocreatedb nocreaterole noinherit nobypassrls',
    :'expense_tracker_reader_password'
)
where not exists (select 1 from pg_roles where rolname = 'expense_tracker_reader')
\gexec

do $$
begin
    if exists (
        select from pg_roles where rolname = 'expense_tracker_reader'
        and (rolsuper or rolcreatedb or rolcreaterole or rolbypassrls or rolinherit or rolreplication or not rolcanlogin)
    ) or exists (
        select from pg_auth_members where member = 'expense_tracker_reader'::regrole
    ) then
        raise exception 'expense_tracker_reader requires restricted attributes and no role memberships';
    end if;
end;
$$;

alter role expense_tracker_reader set default_transaction_read_only = on;
alter role expense_tracker_reader set search_path = pg_catalog, public, app;

grant usage on schema public, app to expense_tracker_reader;
grant execute on function app.current_user_id() to expense_tracker_reader;
grant select on
    profiles, transactions, transaction_items, transaction_adjustments, validation_issues,
    categories, themes, transaction_item_themes, taxonomy_versions, taxonomy_nodes, taxonomy_node_closure,
    taxonomy_facets, taxonomy_facet_values, transaction_item_facets,
    product_concepts, product_variants, nutrition_lookups, receipt_document_events,
    spending_coverage_declarations, spending_classification_reviews, tracker_browser_sessions
to expense_tracker_reader;

commit;
