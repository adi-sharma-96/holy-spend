-- Reassign historical transaction_items sitting on the now-non-assignable
-- dairy_eggs.milk.cows_milk parent into its two new children (see
-- taxonomy/v2/taxonomy.yaml). Unlike the 0018 splits, this one has a safe
-- default: fresh milk is overwhelmingly the typical purchase and
-- shelf-stable condensed/evaporated milk is the narrow exception, so every
-- item is reassigned (fresh_milk as the fallback) rather than leaving
-- unmatched items stuck on the parent. The two products have genuinely
-- different prices per volume; a can of condensed milk was blending into a
-- misleading "Milk down 58.6%" Deals insight against a jug of fresh milk
-- before this fix. Same regex/backfill pattern as 0014 and 0018.

begin;

create temporary table taxonomy_v2_cows_milk_split_repairs (
    item_id uuid primary key,
    user_id uuid not null,
    concept_id uuid,
    alias_name text,
    current_node_id uuid not null,
    target_node_id uuid not null
) on commit drop;

insert into taxonomy_v2_cows_milk_split_repairs (
    item_id, user_id, concept_id, alias_name, current_node_id, target_node_id
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
    current_node.id,
    target.id
from transaction_items item
join taxonomy_nodes current_node on current_node.id = item.taxonomy_node_id
join taxonomy_versions current_version
  on current_version.id = current_node.version_id
 and current_version.status = 'active'
cross join lateral (
    select case
        when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name))
            ~ '\m(condensed|evaporated)\M'
            then 'food_dining.groceries.dairy_eggs.milk.cows_milk.condensed_evaporated_milk'
        else 'food_dining.groceries.dairy_eggs.milk.cows_milk.fresh_milk'
    end as stable_key
) rule
join taxonomy_nodes target
  on target.version_id = current_node.version_id
 and target.stable_key = rule.stable_key
 and target.is_assignable = true
where current_node.stable_key = 'food_dining.groceries.dairy_eggs.milk.cows_milk';

update transaction_items item
set taxonomy_node_id = repair.target_node_id,
    classification_source = 'migration',
    classification_confidence = 1,
    classification_review_status = 'reviewed',
    classification_reviewed_at = now()
from taxonomy_v2_cows_milk_split_repairs repair
where item.id = repair.item_id
  and item.user_id = repair.user_id;

update user_product_aliases alias
set taxonomy_node_id = repair.target_node_id,
    updated_at = now()
from taxonomy_v2_cows_milk_split_repairs repair
where alias.user_id = repair.user_id
  and alias.raw_name_normalized = repair.alias_name
  and alias.taxonomy_node_id = repair.current_node_id;

with concept_repairs as (
    select
        repair.concept_id,
        repair.current_node_id,
        (array_agg(repair.target_node_id))[1] as target_node_id
    from taxonomy_v2_cows_milk_split_repairs repair
    where repair.concept_id is not null
    group by repair.concept_id, repair.current_node_id
    having count(distinct repair.target_node_id) = 1
)
update product_concepts concept
set primary_taxonomy_node_id = repair.target_node_id
from concept_repairs repair
where concept.id = repair.concept_id
  and concept.primary_taxonomy_node_id = repair.current_node_id;

commit;
