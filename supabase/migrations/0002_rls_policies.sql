alter table profiles enable row level security;
alter table merchants enable row level security;
alter table product_concepts enable row level security;
alter table product_variants enable row level security;
alter table product_concept_themes enable row level security;
alter table product_variant_themes enable row level security;
alter table transactions enable row level security;
alter table receipts enable row level security;
alter table receipt_files enable row level security;
alter table transaction_items enable row level security;
alter table transaction_item_themes enable row level security;
alter table transaction_adjustments enable row level security;
alter table user_product_aliases enable row level security;
alter table validation_issues enable row level security;
alter table user_corrections enable row level security;
alter table audit_events enable row level security;
alter table personal_access_tokens enable row level security;
alter table categories enable row level security;
alter table themes enable row level security;

create policy profiles_select_own on profiles
    for select using (id = auth.uid());

create policy profiles_update_own on profiles
    for update using (id = auth.uid()) with check (id = auth.uid());

create policy categories_read_authenticated on categories
    for select to authenticated using (is_active = true);

create policy themes_read_authenticated on themes
    for select to authenticated using (is_active = true);

create policy merchants_select_visible on merchants
    for select using (owner_user_id is null or owner_user_id = auth.uid());

create policy merchants_insert_own on merchants
    for insert with check (owner_user_id = auth.uid());

create policy merchants_update_own on merchants
    for update using (owner_user_id = auth.uid()) with check (owner_user_id = auth.uid());

create policy product_concepts_select_visible on product_concepts
    for select using (owner_user_id is null or owner_user_id = auth.uid());

create policy product_concepts_insert_own on product_concepts
    for insert with check (owner_user_id = auth.uid());

create policy product_concepts_update_own on product_concepts
    for update using (owner_user_id = auth.uid()) with check (owner_user_id = auth.uid());

create policy product_variants_select_visible on product_variants
    for select using (owner_user_id is null or owner_user_id = auth.uid());

create policy product_variants_insert_own on product_variants
    for insert with check (owner_user_id = auth.uid());

create policy product_variants_update_own on product_variants
    for update using (owner_user_id = auth.uid()) with check (owner_user_id = auth.uid());

create policy product_concept_themes_read_authenticated on product_concept_themes
    for select to authenticated using (true);

create policy product_variant_themes_read_authenticated on product_variant_themes
    for select to authenticated using (true);

create policy transactions_crud_own on transactions
    for all using (user_id = auth.uid()) with check (user_id = auth.uid());

create policy receipts_crud_own on receipts
    for all using (user_id = auth.uid()) with check (user_id = auth.uid());

create policy receipt_files_crud_own on receipt_files
    for all using (user_id = auth.uid()) with check (user_id = auth.uid());

create policy transaction_items_crud_own on transaction_items
    for all using (user_id = auth.uid()) with check (user_id = auth.uid());

create policy transaction_item_themes_crud_own on transaction_item_themes
    for all using (user_id = auth.uid()) with check (user_id = auth.uid());

create policy transaction_adjustments_crud_own on transaction_adjustments
    for all using (user_id = auth.uid()) with check (user_id = auth.uid());

create policy user_product_aliases_crud_own on user_product_aliases
    for all using (user_id = auth.uid()) with check (user_id = auth.uid());

create policy validation_issues_crud_own on validation_issues
    for all using (user_id = auth.uid()) with check (user_id = auth.uid());

create policy user_corrections_crud_own on user_corrections
    for all using (user_id = auth.uid()) with check (user_id = auth.uid());

create policy audit_events_crud_own on audit_events
    for all using (user_id = auth.uid()) with check (user_id = auth.uid());

create policy personal_access_tokens_crud_own on personal_access_tokens
    for all using (user_id = auth.uid()) with check (user_id = auth.uid());
