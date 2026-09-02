-- The OFF-specific batch job was scrapped in favor of a scheduled chat task that can
-- look anywhere (Open Food Facts, USDA FoodData Central, brand sites, general web
-- search), not just OFF. Rename the OFF-specific columns and record provenance so a
-- result's source stays traceable regardless of where it came from. Also add the
-- delete policy that was missing since 0020 (needed to clear stale queue rows).

alter table nutrition_lookups rename column off_code to source_ref;
alter table nutrition_lookups rename column off_product_name to matched_product_name;
alter table nutrition_lookups add column source text;

create policy nutrition_lookups_delete_own on nutrition_lookups
    for delete using (owner_user_id = app.current_user_id());
