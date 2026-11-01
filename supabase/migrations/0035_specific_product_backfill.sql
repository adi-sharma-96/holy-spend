-- Only receipt text that states a product type can repair an unreviewed
-- classification. Confirmed/user reviewed history remains for the queue.
begin;

with rules(source_key, target_key, pattern, excluded) as (
    values
    ('food_dining.groceries.grains_pasta.flour.all_purpose_flour', 'food_dining.groceries.grains_pasta.flour.corn_flour', '\mcorn flour\M', '\m(cornstarch|maize starch|ragi|sooji|semolina|rava|mix|blend)\M'),
    ('food_dining.groceries.grains_pasta.flour.all_purpose_flour', 'food_dining.groceries.grains_pasta.flour.ragi_flour', '\mragi flour\M', '\m(corn|sooji|semolina|rava|mix|blend)\M'),
    ('food_dining.groceries.grains_pasta.flour.all_purpose_flour', 'food_dining.groceries.grains_pasta.flour.sooji', '\m(sooji|semolina|rava)\M', '\m(corn|ragi|mix|blend)\M'),
    ('food_dining.groceries.pantry_cooking.pulses_legumes.lentils', 'food_dining.groceries.pantry_cooking.pulses_legumes.lentils.urad', '\murad\M', '\m(mix|blend)\M'),
    ('food_dining.groceries.pantry_cooking.pulses_legumes.lentils', 'food_dining.groceries.pantry_cooking.pulses_legumes.lentils.moong', '\m(moong|mung)\M', '\m(mix|blend)\M'),
    ('food_dining.groceries.frozen_food.frozen_produce', 'food_dining.groceries.frozen_food.frozen_produce.frozen_peas', '\mpeas?\M', '\m(mix|blend)\M'),
    ('food_dining.groceries.frozen_food.frozen_produce', 'food_dining.groceries.frozen_food.frozen_produce.frozen_coconut', '\mcoconut\M', '\m(mix|blend)\M'),
    ('food_dining.groceries.frozen_food.frozen_produce', 'food_dining.groceries.frozen_food.frozen_produce.frozen_berries', '\m(berry|berries)\M', '\m(peas?|coconut)\M')
), candidates as (
    select i.id, i.user_id, target.id as target_id
    from transaction_items i
    join taxonomy_nodes source on source.id = i.taxonomy_node_id
    join rules r on r.source_key = source.stable_key
    join taxonomy_nodes target on target.version_id = source.version_id
        and target.stable_key = r.target_key
    where i.classification_source <> 'user'
      and i.classification_review_status = 'suggested'
      and i.classification_reviewed_at is null
      and lower(i.raw_name) ~ r.pattern
      and lower(i.raw_name) !~ r.excluded
), unambiguous as (
    select id, user_id, (array_agg(target_id))[1] as target_id
    from candidates group by id, user_id having count(distinct target_id) = 1
)
update transaction_items i
set taxonomy_node_id = u.target_id, classification_source = 'migration',
    classification_confidence = null, classification_review_status = 'suggested',
    classification_reviewed_at = null
from unambiguous u
where i.id = u.id and i.user_id = u.user_id;

commit;
