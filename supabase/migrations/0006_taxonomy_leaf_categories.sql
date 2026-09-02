begin;

alter table categories
    add column if not exists is_assignable boolean not null default true;

comment on column categories.is_assignable is
    'True for leaf categories that may be assigned to products or transaction items.';

-- Add a compact set of useful leaves where the original food taxonomy was too broad.
with parents as (
    select id, slug from categories
),
seed(slug, parent_slug, name, depth, sort_order) as (
    values
        ('grocery.food.meat_seafood_alternatives.meat_poultry', 'grocery.food.meat_seafood_alternatives', 'Meat & Poultry', 3, 10),
        ('grocery.food.meat_seafood_alternatives.seafood', 'grocery.food.meat_seafood_alternatives', 'Seafood', 3, 20),
        ('grocery.food.meat_seafood_alternatives.plant_based', 'grocery.food.meat_seafood_alternatives', 'Plant-Based Alternatives', 3, 30),
        ('grocery.food.bakery.bread_buns', 'grocery.food.bakery', 'Bread & Buns', 3, 10),
        ('grocery.food.bakery.cakes_pastries', 'grocery.food.bakery', 'Cakes & Pastries', 3, 20),
        ('grocery.food.grains_rice_pasta.whole_grains', 'grocery.food.grains_rice_pasta', 'Whole Grains', 3, 30),
        ('grocery.food.grains_rice_pasta.noodles', 'grocery.food.grains_rice_pasta', 'Noodles', 3, 40),
        ('grocery.food.flour_baking.flour', 'grocery.food.flour_baking', 'Flour', 3, 10),
        ('grocery.food.flour_baking.baking_ingredients', 'grocery.food.flour_baking', 'Baking Ingredients', 3, 20),
        ('grocery.food.breakfast.cereal_granola', 'grocery.food.breakfast', 'Cereal & Granola', 3, 10),
        ('grocery.food.breakfast.oats_hot_cereal', 'grocery.food.breakfast', 'Oats & Hot Cereal', 3, 20),
        ('grocery.food.pantry_cooking.oils_vinegars', 'grocery.food.pantry_cooking', 'Oils & Vinegars', 3, 20),
        ('grocery.food.pantry_cooking.canned_jarred', 'grocery.food.pantry_cooking', 'Canned & Jarred Ingredients', 3, 30),
        ('grocery.food.pantry_cooking.cooking_bases', 'grocery.food.pantry_cooking', 'Cooking Bases & Stocks', 3, 40),
        ('grocery.food.condiments_spreads.sauces_condiments', 'grocery.food.condiments_spreads', 'Sauces & Condiments', 3, 10),
        ('grocery.food.condiments_spreads.spreads', 'grocery.food.condiments_spreads', 'Spreads', 3, 20),
        ('grocery.food.snacks.chips_crackers', 'grocery.food.snacks', 'Chips & Crackers', 3, 40),
        ('grocery.food.snacks.popcorn', 'grocery.food.snacks', 'Popcorn', 3, 50),
        ('grocery.food.snacks.snack_mixes', 'grocery.food.snacks', 'Snack Mixes', 3, 60),
        ('grocery.food.sweets_desserts.cookies_biscuits_wafers', 'grocery.food.sweets_desserts', 'Cookies, Biscuits & Wafers', 3, 20),
        ('grocery.food.sweets_desserts.candy_confectionery', 'grocery.food.sweets_desserts', 'Candy & Confectionery', 3, 30),
        ('grocery.food.sweets_desserts.frozen_desserts', 'grocery.food.sweets_desserts', 'Ice Cream & Frozen Desserts', 3, 40),
        ('grocery.food.prepared.ready_meals', 'grocery.food.prepared', 'Ready Meals', 3, 10),
        ('grocery.food.prepared.deli_prepared', 'grocery.food.prepared', 'Deli & Prepared Foods', 3, 20),
        ('grocery.food.beverages.water', 'grocery.food.beverages', 'Water', 3, 10),
        ('grocery.food.beverages.soft_drinks', 'grocery.food.beverages', 'Soft Drinks', 3, 20),
        ('grocery.food.beverages.juice', 'grocery.food.beverages', 'Juice', 3, 30),
        ('grocery.food.beverages.coffee_tea', 'grocery.food.beverages', 'Coffee & Tea', 3, 40),
        ('grocery.food.beverages.alcoholic', 'grocery.food.beverages', 'Alcoholic Beverages', 3, 50),
        ('grocery.food.nutrition_sports.protein_supplements', 'grocery.food.nutrition_sports', 'Protein Supplements', 3, 10),
        ('grocery.food.nutrition_sports.energy_sports_foods', 'grocery.food.nutrition_sports', 'Energy & Sports Foods', 3, 20),
        ('grocery.food.nutrition_sports.meal_replacements', 'grocery.food.nutrition_sports', 'Meal Replacements', 3, 30)
)
insert into categories (slug, parent_id, name, depth, path_slug, sort_order, is_active, is_assignable)
select seed.slug, parents.id, seed.name, seed.depth, seed.slug, seed.sort_order, true, true
from seed
join parents on parents.slug = seed.parent_slug
on conflict (slug) do update
set parent_id = excluded.parent_id,
    name = excluded.name,
    depth = excluded.depth,
    path_slug = excluded.path_slug,
    sort_order = excluded.sort_order,
    is_active = true;

-- Every active internal node gets one explicit fallback leaf, including non-grocery branches.
insert into categories (slug, parent_id, name, depth, path_slug, sort_order, is_active, is_assignable)
select
    parent.slug || '.other',
    parent.id,
    'Other ' || parent.name,
    parent.depth + 1,
    parent.path_slug || '.other',
    999,
    true,
    true
from categories parent
where parent.is_active = true
  and exists (
      select 1
      from categories child
      where child.parent_id = parent.id
        and child.is_active = true
  )
  and not exists (
      select 1
      from categories fallback
      where fallback.slug = parent.slug || '.other'
  )
on conflict (slug) do update
set parent_id = excluded.parent_id,
    name = excluded.name,
    depth = excluded.depth,
    path_slug = excluded.path_slug,
    sort_order = excluded.sort_order,
    is_active = true,
    is_assignable = true;

-- Product form belongs in the category tree; chocolate content is a cross-cutting theme.
insert into themes (slug, name, description, is_active)
values (
    'chocolate',
    'Chocolate',
    'Contains or is primarily flavoured with chocolate, cocoa, or cacao.',
    true
)
on conflict (slug) do update
set name = excluded.name,
    description = excluded.description,
    is_active = true;

create or replace function app.taxonomy_leaf_slug(parent_slug text, item_name text)
returns text
language sql
immutable
set search_path = pg_catalog, public
as $$
    select case
        when parent_slug = 'grocery.food.sweets_desserts'
             and lower(coalesce(item_name, '')) ~ '(cookie|biscuit|wafer)'
            then parent_slug || '.cookies_biscuits_wafers'
        when parent_slug = 'grocery.food.sweets_desserts'
             and lower(coalesce(item_name, '')) ~ '(chocolate|cocoa|m&m|m & m|reese|bounty|nestl)'
            then parent_slug || '.chocolate'
        when parent_slug = 'grocery.food.sweets_desserts'
             and lower(coalesce(item_name, '')) ~ '(ice[ -]?cream|gelato|sorbet|frozen dessert)'
            then parent_slug || '.frozen_desserts'
        when parent_slug = 'grocery.food.sweets_desserts'
             and lower(coalesce(item_name, '')) ~ '(candy|gumm|toffee|caramel|licorice|lollipop|confection)'
            then parent_slug || '.candy_confectionery'
        when parent_slug = 'grocery.food.snacks'
             and lower(coalesce(item_name, '')) ~ '(chip|crisp|cracker|tortilla)'
            then parent_slug || '.chips_crackers'
        when parent_slug = 'grocery.food.snacks'
             and lower(coalesce(item_name, '')) ~ 'popcorn'
            then parent_slug || '.popcorn'
        when parent_slug = 'grocery.food.snacks'
             and lower(coalesce(item_name, '')) ~ '(trail mix|snack mix|party mix)'
            then parent_slug || '.snack_mixes'
        when parent_slug = 'grocery.food.bakery'
             and lower(coalesce(item_name, '')) ~ '(bread|bun|bagel|roll)'
            then parent_slug || '.bread_buns'
        when parent_slug = 'grocery.food.bakery'
             and lower(coalesce(item_name, '')) ~ '(cake|pastr|croissant|donut|doughnut|muffin|tart)'
            then parent_slug || '.cakes_pastries'
        when parent_slug = 'grocery.food.meat_seafood_alternatives'
             and lower(coalesce(item_name, '')) ~ '(fish|salmon|tuna|shrimp|prawn|seafood)'
            then parent_slug || '.seafood'
        when parent_slug = 'grocery.food.meat_seafood_alternatives'
             and lower(coalesce(item_name, '')) ~ '(tofu|tempeh|plant[ -]?based|meatless)'
            then parent_slug || '.plant_based'
        when parent_slug = 'grocery.food.meat_seafood_alternatives'
             and lower(coalesce(item_name, '')) ~ '(beef|chicken|pork|turkey|lamb|meat|poultry)'
            then parent_slug || '.meat_poultry'
        when parent_slug = 'grocery.food.grains_rice_pasta'
             and lower(coalesce(item_name, '')) ~ '(noodle|ramen|vermicelli)'
            then parent_slug || '.noodles'
        when parent_slug = 'grocery.food.grains_rice_pasta'
             and lower(coalesce(item_name, '')) ~ '(quinoa|barley|millet|couscous|grain)'
            then parent_slug || '.whole_grains'
        when parent_slug = 'grocery.food.flour_baking'
             and lower(coalesce(item_name, '')) ~ 'flour'
            then parent_slug || '.flour'
        when parent_slug = 'grocery.food.flour_baking'
             and lower(coalesce(item_name, '')) ~ '(yeast|baking powder|baking soda|cornstarch|cocoa)'
            then parent_slug || '.baking_ingredients'
        when parent_slug = 'grocery.food.breakfast'
             and lower(coalesce(item_name, '')) ~ '(cereal|granola|muesli)'
            then parent_slug || '.cereal_granola'
        when parent_slug = 'grocery.food.breakfast'
             and lower(coalesce(item_name, '')) ~ '(oat|porridge|hot cereal)'
            then parent_slug || '.oats_hot_cereal'
        when parent_slug = 'grocery.food.pantry_cooking'
             and lower(coalesce(item_name, '')) ~ '(oil|vinegar)'
            then parent_slug || '.oils_vinegars'
        when parent_slug = 'grocery.food.pantry_cooking'
             and lower(coalesce(item_name, '')) ~ '(canned|jarred|tin)'
            then parent_slug || '.canned_jarred'
        when parent_slug = 'grocery.food.pantry_cooking'
             and lower(coalesce(item_name, '')) ~ '(stock|broth|bouillon|cooking base)'
            then parent_slug || '.cooking_bases'
        when parent_slug = 'grocery.food.condiments_spreads'
             and lower(coalesce(item_name, '')) ~ '(spread|jam|jelly|peanut butter|nut butter)'
            then parent_slug || '.spreads'
        when parent_slug = 'grocery.food.condiments_spreads'
            then parent_slug || '.sauces_condiments'
        when parent_slug = 'grocery.food.prepared'
             and lower(coalesce(item_name, '')) ~ '(deli|salad|rotisserie)'
            then parent_slug || '.deli_prepared'
        when parent_slug = 'grocery.food.prepared'
             and lower(coalesce(item_name, '')) ~ '(meal|dinner|entree|pizza)'
            then parent_slug || '.ready_meals'
        when parent_slug = 'grocery.food.beverages'
             and lower(coalesce(item_name, '')) ~ '(water|sparkling water)'
            then parent_slug || '.water'
        when parent_slug = 'grocery.food.beverages'
             and lower(coalesce(item_name, '')) ~ '(soda|soft drink|cola|pop)'
            then parent_slug || '.soft_drinks'
        when parent_slug = 'grocery.food.beverages'
             and lower(coalesce(item_name, '')) ~ 'juice'
            then parent_slug || '.juice'
        when parent_slug = 'grocery.food.beverages'
             and lower(coalesce(item_name, '')) ~ '(coffee|tea)'
            then parent_slug || '.coffee_tea'
        when parent_slug = 'grocery.food.beverages'
             and lower(coalesce(item_name, '')) ~ '(beer|wine|cider|vodka|whisky|whiskey|rum|alcohol)'
            then parent_slug || '.alcoholic'
        when parent_slug = 'grocery.food.nutrition_sports'
             and lower(coalesce(item_name, '')) ~ '(protein powder|protein supplement|whey|casein)'
            then parent_slug || '.protein_supplements'
        when parent_slug = 'grocery.food.nutrition_sports'
             and lower(coalesce(item_name, '')) ~ '(energy bar|sports bar|energy gel|sports food)'
            then parent_slug || '.energy_sports_foods'
        when parent_slug = 'grocery.food.nutrition_sports'
             and lower(coalesce(item_name, '')) ~ '(meal replacement|nutrition shake)'
            then parent_slug || '.meal_replacements'
        else parent_slug || '.other'
    end
$$;

create temporary table taxonomy_item_reclassifications on commit drop as
select
    item.id as item_id,
    item.user_id,
    item.transaction_id,
    transaction.status,
    current_category.id as old_category_id,
    current_category.slug as old_category_slug,
    replacement.id as new_category_id,
    replacement.slug as new_category_slug
from transaction_items item
join transactions transaction
  on transaction.id = item.transaction_id
 and transaction.user_id = item.user_id
join categories current_category on current_category.id = item.category_id
join categories replacement
  on replacement.slug = app.taxonomy_leaf_slug(
      current_category.slug,
      concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)
  )
where exists (
    select 1 from categories child
    where child.parent_id = current_category.id and child.is_active = true
)
and replacement.id <> current_category.id;

insert into user_corrections (
    user_id, transaction_id, item_id, field_name, old_value, new_value
)
select
    change.user_id,
    change.transaction_id,
    change.item_id,
    'category_id',
    jsonb_build_object(
        'value', change.old_category_slug,
        'reason', 'Taxonomy migration 0006 moved an internal category assignment to an assignable leaf.'
    ),
    jsonb_build_object('value', change.new_category_slug)
from taxonomy_item_reclassifications change
where change.status = 'confirmed';

insert into audit_events (user_id, entity_type, entity_id, action, metadata)
select
    change.user_id,
    'transaction',
    change.transaction_id,
    'taxonomy_reclassified',
    jsonb_build_object(
        'item_id', change.item_id,
        'old_category_slug', change.old_category_slug,
        'new_category_slug', change.new_category_slug,
        'migration', '0006_taxonomy_leaf_categories',
        'validation_effect', 'category-only change; monetary reconciliation inputs unchanged'
    )
from taxonomy_item_reclassifications change;

update transaction_items item
set category_id = change.new_category_id,
    updated_at = now()
from taxonomy_item_reclassifications change
where item.id = change.item_id;

create temporary table taxonomy_chocolate_theme_backfills on commit drop as
select
    item.id as item_id,
    item.user_id,
    item.transaction_id,
    transaction.status,
    theme.id as theme_id
from transaction_items item
join transactions transaction
  on transaction.id = item.transaction_id
 and transaction.user_id = item.user_id
join categories category on category.id = item.category_id
join themes theme on theme.slug = 'chocolate'
where category.path_slug like 'grocery.food.%'
  and lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name))
      ~ '(choc|cocoa|cacao|m&m|m & m|reese)'
  and not exists (
      select 1
      from transaction_item_themes existing
      where existing.item_id = item.id
        and existing.theme_id = theme.id
  );

insert into user_corrections (
    user_id, transaction_id, item_id, field_name, old_value, new_value
)
select
    change.user_id,
    change.transaction_id,
    change.item_id,
    'theme_slugs',
    jsonb_build_object(
        'value', '[]'::jsonb,
        'reason', 'Taxonomy migration 0006 added the chocolate attribute independently of product form.'
    ),
    jsonb_build_object('value', jsonb_build_array('chocolate'))
from taxonomy_chocolate_theme_backfills change
where change.status = 'confirmed';

insert into audit_events (user_id, entity_type, entity_id, action, metadata)
select
    change.user_id,
    'transaction',
    change.transaction_id,
    'taxonomy_theme_backfilled',
    jsonb_build_object(
        'item_id', change.item_id,
        'theme_slug', 'chocolate',
        'migration', '0006_taxonomy_leaf_categories',
        'validation_effect', 'theme-only change; monetary reconciliation inputs unchanged'
    )
from taxonomy_chocolate_theme_backfills change;

insert into transaction_item_themes (user_id, item_id, theme_id)
select change.user_id, change.item_id, change.theme_id
from taxonomy_chocolate_theme_backfills change
on conflict (item_id, theme_id) do nothing;

create temporary table taxonomy_alias_reclassifications on commit drop as
select
    alias.id as alias_id,
    alias.user_id,
    current_category.slug as old_category_slug,
    replacement.id as new_category_id,
    replacement.slug as new_category_slug
from user_product_aliases alias
join categories current_category on current_category.id = alias.category_id
join categories replacement
  on replacement.slug = app.taxonomy_leaf_slug(current_category.slug, alias.raw_name_normalized)
where exists (
    select 1 from categories child
    where child.parent_id = current_category.id and child.is_active = true
)
and replacement.id <> current_category.id;

insert into audit_events (user_id, entity_type, entity_id, action, metadata)
select
    change.user_id,
    'user_product_alias',
    change.alias_id,
    'taxonomy_reclassified',
    jsonb_build_object(
        'old_category_slug', change.old_category_slug,
        'new_category_slug', change.new_category_slug,
        'migration', '0006_taxonomy_leaf_categories'
    )
from taxonomy_alias_reclassifications change;

update user_product_aliases alias
set category_id = change.new_category_id,
    updated_at = now()
from taxonomy_alias_reclassifications change
where alias.id = change.alias_id;

create temporary table taxonomy_concept_reclassifications on commit drop as
select
    concept.id as concept_id,
    concept.owner_user_id,
    current_category.slug as old_category_slug,
    replacement.id as new_category_id,
    replacement.slug as new_category_slug
from product_concepts concept
join categories current_category on current_category.id = concept.primary_category_id
join categories replacement
  on replacement.slug = app.taxonomy_leaf_slug(current_category.slug, concept.canonical_name)
where exists (
    select 1 from categories child
    where child.parent_id = current_category.id and child.is_active = true
)
and replacement.id <> current_category.id;

insert into audit_events (user_id, entity_type, entity_id, action, metadata)
select
    change.owner_user_id,
    'product_concept',
    change.concept_id,
    'taxonomy_reclassified',
    jsonb_build_object(
        'old_category_slug', change.old_category_slug,
        'new_category_slug', change.new_category_slug,
        'migration', '0006_taxonomy_leaf_categories'
    )
from taxonomy_concept_reclassifications change
where change.owner_user_id is not null;

update product_concepts concept
set primary_category_id = change.new_category_id,
    updated_at = now()
from taxonomy_concept_reclassifications change
where concept.id = change.concept_id;

update categories category
set is_assignable = not exists (
    select 1
    from categories child
    where child.parent_id = category.id
      and child.is_active = true
);

create index if not exists categories_active_assignable_path_idx
    on categories(path_slug)
    where is_active = true and is_assignable = true;

create or replace function app.enforce_assignable_category()
returns trigger
language plpgsql
set search_path = pg_catalog, public
as $$
declare
    category_value uuid;
    category_active boolean;
    category_assignable boolean;
begin
    category_value := nullif(to_jsonb(new) ->> tg_argv[0], '')::uuid;
    if category_value is null then
        return new;
    end if;

    select
        category.is_active,
        not exists (
            select 1
            from public.categories child
            where child.parent_id = category.id
              and child.is_active = true
        )
    into category_active, category_assignable
    from public.categories category
    where category.id = category_value;

    if not found or category_active is not true or category_assignable is not true then
        raise exception using
            errcode = '23514',
            message = format('Category %s must be an active assignable leaf category.', category_value);
    end if;

    return new;
end;
$$;

drop trigger if exists transaction_items_assignable_category on transaction_items;
create trigger transaction_items_assignable_category
before insert or update of category_id on transaction_items
for each row execute function app.enforce_assignable_category('category_id');

drop trigger if exists user_product_aliases_assignable_category on user_product_aliases;
create trigger user_product_aliases_assignable_category
before insert or update of category_id on user_product_aliases
for each row execute function app.enforce_assignable_category('category_id');

drop trigger if exists product_concepts_assignable_category on product_concepts;
create trigger product_concepts_assignable_category
before insert or update of primary_category_id on product_concepts
for each row execute function app.enforce_assignable_category('primary_category_id');

drop function app.taxonomy_leaf_slug(text, text);

commit;
