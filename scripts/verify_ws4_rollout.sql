-- Read-only pre-merge check. Does not create roles or change passwords/grants.
\set ON_ERROR_STOP on
begin read only;

select c.relname as table_name, c.relrowsecurity as rls_on, c.relforcerowsecurity as rls_forced,
       has_table_privilege('expense_app', c.oid, 'SELECT')
       and has_table_privilege('expense_app', c.oid, 'INSERT')
       and (c.relname = 'spending_classification_reviews'
            or has_table_privilege('expense_app', c.oid, 'DELETE')) as grants_ok
from pg_class c join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public' and c.relname in (
    'spending_coverage_declarations', 'spending_classification_reviews',
    'tracker_launch_credentials', 'tracker_browser_sessions'
)
order by c.relname;

select has_column_privilege('expense_app', 'public.nutrition_lookups', 'protein_label', 'SELECT')
       and has_column_privilege('expense_app', 'public.nutrition_lookups', 'protein_label', 'UPDATE')
       as protein_label_ready;

do $$
declare ready integer;
begin
    select count(*) into ready from pg_class c join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public' and c.relname in (
        'spending_coverage_declarations', 'spending_classification_reviews',
        'tracker_launch_credentials', 'tracker_browser_sessions'
    ) and c.relrowsecurity and c.relforcerowsecurity
      and has_table_privilege('expense_app', c.oid, 'SELECT')
      and has_table_privilege('expense_app', c.oid, 'INSERT')
      and (c.relname = 'spending_classification_reviews'
           or has_table_privilege('expense_app', c.oid, 'DELETE'));
    if ready <> 4 then raise exception 'WS4 tables, RLS or runtime grants are incomplete'; end if;
    if not (has_column_privilege('expense_app', 'public.nutrition_lookups', 'protein_label', 'SELECT')
        and has_column_privilege('expense_app', 'public.nutrition_lookups', 'protein_label', 'UPDATE')) then
        raise exception 'WS4 protein_label runtime grants are incomplete';
    end if;
end;
$$;
commit;
