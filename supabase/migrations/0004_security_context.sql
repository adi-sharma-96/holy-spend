create schema if not exists app;

create function app.current_user_id()
returns uuid
language sql
stable
as $$
    select nullif(current_setting('app.current_user_id', true), '')::uuid
$$;

create function app.authenticate_pat(p_token_hash text)
returns table (
    token_id uuid,
    user_id uuid,
    scopes text[]
)
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
    return query
    update personal_access_tokens pat
    set last_used_at = now()
    where pat.token_hash = p_token_hash
      and pat.revoked_at is null
      and (pat.expires_at is null or pat.expires_at > now())
    returning pat.id, pat.user_id, pat.scopes;
end;
$$;

revoke all on function app.authenticate_pat(text) from public;
revoke all on function app.current_user_id() from public;

-- Runtime DATABASE_URL must use a non-owner app role without BYPASSRLS.
-- Migrations/admin jobs should use a separate privileged role.
-- Deployment should grant execute on these functions to the runtime app role.

drop policy if exists profiles_select_own on profiles;
drop policy if exists profiles_update_own on profiles;
drop policy if exists categories_read_authenticated on categories;
drop policy if exists themes_read_authenticated on themes;
drop policy if exists merchants_select_visible on merchants;
drop policy if exists merchants_insert_own on merchants;
drop policy if exists merchants_update_own on merchants;
drop policy if exists product_concepts_select_visible on product_concepts;
drop policy if exists product_concepts_insert_own on product_concepts;
drop policy if exists product_concepts_update_own on product_concepts;
drop policy if exists product_variants_select_visible on product_variants;
drop policy if exists product_variants_insert_own on product_variants;
drop policy if exists product_variants_update_own on product_variants;
drop policy if exists product_concept_themes_read_authenticated on product_concept_themes;
drop policy if exists product_variant_themes_read_authenticated on product_variant_themes;
drop policy if exists transactions_crud_own on transactions;
drop policy if exists receipts_crud_own on receipts;
drop policy if exists receipt_files_crud_own on receipt_files;
drop policy if exists transaction_items_crud_own on transaction_items;
drop policy if exists transaction_item_themes_crud_own on transaction_item_themes;
drop policy if exists transaction_adjustments_crud_own on transaction_adjustments;
drop policy if exists user_product_aliases_crud_own on user_product_aliases;
drop policy if exists validation_issues_crud_own on validation_issues;
drop policy if exists user_corrections_crud_own on user_corrections;
drop policy if exists audit_events_crud_own on audit_events;
drop policy if exists personal_access_tokens_crud_own on personal_access_tokens;

create policy profiles_select_own on profiles
    for select using (id = app.current_user_id());

create policy profiles_update_own on profiles
    for update using (id = app.current_user_id()) with check (id = app.current_user_id());

create policy categories_read_with_app_context on categories
    for select using (app.current_user_id() is not null and is_active = true);

create policy themes_read_with_app_context on themes
    for select using (app.current_user_id() is not null and is_active = true);

create policy merchants_select_visible on merchants
    for select using (owner_user_id is null or owner_user_id = app.current_user_id());

create policy merchants_insert_own on merchants
    for insert with check (owner_user_id = app.current_user_id());

create policy merchants_update_own on merchants
    for update using (owner_user_id = app.current_user_id())
    with check (owner_user_id = app.current_user_id());

create policy product_concepts_select_visible on product_concepts
    for select using (owner_user_id is null or owner_user_id = app.current_user_id());

create policy product_concepts_insert_own on product_concepts
    for insert with check (owner_user_id = app.current_user_id());

create policy product_concepts_update_own on product_concepts
    for update using (owner_user_id = app.current_user_id())
    with check (owner_user_id = app.current_user_id());

create policy product_variants_select_visible on product_variants
    for select using (owner_user_id is null or owner_user_id = app.current_user_id());

create policy product_variants_insert_own on product_variants
    for insert with check (owner_user_id = app.current_user_id());

create policy product_variants_update_own on product_variants
    for update using (owner_user_id = app.current_user_id())
    with check (owner_user_id = app.current_user_id());

create policy product_concept_themes_read_visible on product_concept_themes
    for select using (
        exists (
            select 1
            from product_concepts pc
            where pc.id = product_concept_themes.concept_id
              and (pc.owner_user_id is null or pc.owner_user_id = app.current_user_id())
        )
    );

create policy product_variant_themes_read_visible on product_variant_themes
    for select using (
        exists (
            select 1
            from product_variants pv
            where pv.id = product_variant_themes.variant_id
              and (pv.owner_user_id is null or pv.owner_user_id = app.current_user_id())
        )
    );

create policy transactions_crud_own on transactions
    for all using (user_id = app.current_user_id()) with check (user_id = app.current_user_id());

create policy receipts_crud_own on receipts
    for all using (user_id = app.current_user_id()) with check (user_id = app.current_user_id());

create policy receipt_files_crud_own on receipt_files
    for all using (user_id = app.current_user_id()) with check (user_id = app.current_user_id());

create policy transaction_items_crud_own on transaction_items
    for all using (user_id = app.current_user_id()) with check (user_id = app.current_user_id());

create policy transaction_item_themes_crud_own on transaction_item_themes
    for all using (user_id = app.current_user_id()) with check (user_id = app.current_user_id());

create policy transaction_adjustments_crud_own on transaction_adjustments
    for all using (user_id = app.current_user_id()) with check (user_id = app.current_user_id());

create policy user_product_aliases_crud_own on user_product_aliases
    for all using (user_id = app.current_user_id()) with check (user_id = app.current_user_id());

create policy validation_issues_crud_own on validation_issues
    for all using (user_id = app.current_user_id()) with check (user_id = app.current_user_id());

create policy user_corrections_crud_own on user_corrections
    for all using (user_id = app.current_user_id()) with check (user_id = app.current_user_id());

create policy audit_events_crud_own on audit_events
    for all using (user_id = app.current_user_id()) with check (user_id = app.current_user_id());

create policy personal_access_tokens_select_none on personal_access_tokens
    for select using (false);

create policy personal_access_tokens_insert_own on personal_access_tokens
    for insert with check (user_id = app.current_user_id());

create policy personal_access_tokens_update_own on personal_access_tokens
    for update using (user_id = app.current_user_id()) with check (user_id = app.current_user_id());
