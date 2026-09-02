-- Keep review-state sentinels out of spend categories and repair the small set
-- of deterministic grocery classifications that taxonomy v2 inherited from
-- coarse legacy categories. This migration is deliberately data-driven and
-- owner-scoped through the existing rows; it contains no installation-specific
-- user IDs.

begin;

create temporary table taxonomy_v2_item_repairs (
    item_id uuid primary key,
    user_id uuid not null,
    concept_id uuid,
    alias_name text,
    target_node_id uuid not null,
    target_category_id uuid
) on commit drop;

insert into taxonomy_v2_item_repairs (
    item_id,
    user_id,
    concept_id,
    alias_name,
    target_node_id,
    target_category_id
)
select
    item.id,
    item.user_id,
    item.concept_id,
    trim(
        regexp_replace(
            regexp_replace(
                lower(coalesce(item.raw_name, item.interpreted_name, item.normalized_name, '')),
                '[^a-z0-9 ]+',
                ' ',
                'g'
            ),
            '\s+',
            ' ',
            'g'
        )
    ) as alias_name,
    target.id,
    legacy.category_id
from transaction_items item
join taxonomy_nodes current_node on current_node.id = item.taxonomy_node_id
join taxonomy_versions current_version
  on current_version.id = current_node.version_id
 and current_version.status = 'active'
cross join lateral (
    select case
        when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name))
            ~ '\mtofu\M'
            then 'food_dining.groceries.meat_seafood_alternatives.plant_proteins.tofu_tempeh'
        when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name))
            ~ '\mcucumber(s)?\M'
            then 'food_dining.groceries.produce.vegetables.squash_gourds'
        when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name))
            ~ '\m(bell[[:space:]]+)?pepper(s)?\M'
            then 'food_dining.groceries.produce.vegetables.nightshades.peppers'
        when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name))
            ~ '\mice[[:space:]-]+cream\M'
            then 'food_dining.groceries.frozen_food.ice_cream_desserts'
        when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name))
            ~ '\mmozzarella\M'
            then 'food_dining.groceries.dairy_eggs.cheese.fresh_soft'
        when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name))
            ~ '\mpizza\M'
            then 'food_dining.groceries.frozen_food.frozen_meals'
        when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name))
            ~ '\mcoconut[[:space:]-]+milk\M'
            then 'food_dining.groceries.pantry_cooking.canned_jarred'
        when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name))
            ~ '\m(sabudana|sago|tapioca)\M'
            then 'food_dining.groceries.pantry_cooking.baking_ingredients'
        else null
    end as stable_key
) rule
join taxonomy_nodes target
  on target.version_id = current_node.version_id
 and target.stable_key = rule.stable_key
 and target.is_assignable = true
left join lateral (
    select mapping.category_id
    from legacy_category_taxonomy_map mapping
    join categories category on category.id = mapping.category_id
    where mapping.taxonomy_node_id = target.id
    order by category.depth desc, category.id
    limit 1
) legacy on true
where current_node.stable_key = 'unclassified.needs_review'
  and rule.stable_key is not null;

update transaction_items item
set taxonomy_node_id = repair.target_node_id,
    category_id = coalesce(repair.target_category_id, item.category_id),
    classification_source = 'migration',
    classification_confidence = 1,
    classification_review_status = 'reviewed',
    classification_reviewed_at = now()
from taxonomy_v2_item_repairs repair
where item.id = repair.item_id
  and item.user_id = repair.user_id;

-- Confirmed-item aliases are authoritative on later receipts. Repair both the
-- merchant-specific and global aliases learned from the affected rows.
update user_product_aliases alias
set taxonomy_node_id = repair.target_node_id,
    category_id = coalesce(repair.target_category_id, alias.category_id),
    updated_at = now()
from taxonomy_v2_item_repairs repair
where alias.user_id = repair.user_id
  and alias.raw_name_normalized = repair.alias_name
  and alias.taxonomy_node_id = (
      select node.id
      from taxonomy_nodes node
      join taxonomy_versions version on version.id = node.version_id
      where version.status = 'active'
        and node.stable_key = 'unclassified.needs_review'
  );

-- A product concept can be repaired automatically only when every repaired
-- occurrence of that concept resolves to the same canonical leaf.
with concept_repairs as (
    select
        repair.concept_id,
        (array_agg(repair.target_node_id))[1] as target_node_id,
        (array_agg(repair.target_category_id)
            filter (where repair.target_category_id is not null))[1] as target_category_id
    from taxonomy_v2_item_repairs repair
    where repair.concept_id is not null
    group by repair.concept_id
    having count(distinct repair.target_node_id) = 1
)
update product_concepts concept
set primary_taxonomy_node_id = repair.target_node_id,
    primary_category_id = coalesce(repair.target_category_id, concept.primary_category_id)
from concept_repairs repair
where concept.id = repair.concept_id
  and concept.primary_taxonomy_node_id = (
      select node.id
      from taxonomy_nodes node
      join taxonomy_versions version on version.id = node.version_id
      where version.status = 'active'
        and node.stable_key = 'unclassified.needs_review'
  );

update validation_issues issue
set resolved_at = coalesce(issue.resolved_at, now())
from taxonomy_v2_item_repairs repair
where issue.item_id = repair.item_id
  and issue.user_id = repair.user_id
  and issue.code in ('taxonomy_needs_review', 'taxonomy_review_required')
  and issue.resolved_at is null;

comment on table transaction_item_classification_history is
    'Append-only audit history for canonical taxonomy classification changes, including deterministic migration repairs.';

commit;
