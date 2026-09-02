-- 0020 copied the pre-0004 auth.uid() RLS pattern, but every table since
-- 0004_security_context.sql uses app.current_user_id() instead (this app sets a
-- Postgres session variable, not real Supabase JWT claims, so auth.uid() resolves to
-- null here and every write silently violated RLS).

drop policy nutrition_lookups_select_own on nutrition_lookups;
drop policy nutrition_lookups_insert_own on nutrition_lookups;
drop policy nutrition_lookups_update_own on nutrition_lookups;

create policy nutrition_lookups_select_own on nutrition_lookups
    for select using (owner_user_id = app.current_user_id());

create policy nutrition_lookups_insert_own on nutrition_lookups
    for insert with check (owner_user_id = app.current_user_id());

create policy nutrition_lookups_update_own on nutrition_lookups
    for update using (owner_user_id = app.current_user_id())
    with check (owner_user_id = app.current_user_id());
