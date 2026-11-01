-- The source catalog and generated fresh-install artifacts contain the same nodes.
-- This migration expands existing installations; old broad assignments remain reviewable.
begin;

update taxonomy_versions
set content_hash = '3dba3f1083b8bd3b3490864582a1f6cb4b7356a2dfe2bde264fc9679e9875642'
where id = 'c39450a8-ead7-53d3-821f-956df5f5eba5';

with additions(id, stable_key, parent_key, name, level, sort_order, synonyms) as (
    values
    ('44aa706a-a65c-5e0c-b5b8-b7d2c3a1b2db'::uuid, 'food_dining.groceries.grains_pasta.flour.corn_flour', 'food_dining.groceries.grains_pasta.flour', 'Corn Flour', 5, 20, array['yellow corn flour', 'maize flour']),
    ('47bd82b0-c12c-5fe4-8665-af8215a6044e'::uuid, 'food_dining.groceries.grains_pasta.flour.ragi_flour', 'food_dining.groceries.grains_pasta.flour', 'Ragi Flour', 5, 30, array['finger millet flour']),
    ('ec1aa920-8946-5047-817f-7856ba88314d'::uuid, 'food_dining.groceries.grains_pasta.flour.sooji', 'food_dining.groceries.grains_pasta.flour', 'Sooji', 5, 40, array['semolina', 'rava']),
    ('e21fe112-86ab-5905-8091-a663b38afc62'::uuid, 'food_dining.groceries.pantry_cooking.pulses_legumes.lentils.urad', 'food_dining.groceries.pantry_cooking.pulses_legumes.lentils', 'Urad Dal', 6, 10, array['urad gota', 'black gram']),
    ('b987e29a-9eb6-557c-9e58-fc4fb11b300d'::uuid, 'food_dining.groceries.pantry_cooking.pulses_legumes.lentils.moong', 'food_dining.groceries.pantry_cooking.pulses_legumes.lentils', 'Moong Dal', 6, 20, array['mung beans', 'green gram']),
    ('043ef2e6-a3e7-5f5f-a95f-3a1db74a7771'::uuid, 'food_dining.groceries.frozen_food.frozen_produce.frozen_berries', 'food_dining.groceries.frozen_food.frozen_produce', 'Frozen Berries', 5, 10, array['frozen berry blend', 'frozen mixed berries']),
    ('420df155-1ea6-575e-962e-a85096a50070'::uuid, 'food_dining.groceries.frozen_food.frozen_produce.frozen_peas', 'food_dining.groceries.frozen_food.frozen_produce', 'Frozen Peas', 5, 20, array['frozen green peas']),
    ('b1250cbf-ae97-5aa6-a525-56230bbeb4dc'::uuid, 'food_dining.groceries.frozen_food.frozen_produce.frozen_coconut', 'food_dining.groceries.frozen_food.frozen_produce', 'Frozen Coconut', 5, 30, array['frozen shredded coconut'])
)
insert into taxonomy_nodes (id, version_id, stable_key, parent_id, level, name, description,
                            sort_order, is_assignable, allowed_transaction_types, metadata)
select a.id, p.version_id, a.stable_key, p.id, a.level, a.name, a.name,
       a.sort_order, true, array['expense', 'refund']::transaction_type[], '{}'::jsonb
from additions a join taxonomy_nodes p on p.stable_key = a.parent_key
where p.version_id = 'c39450a8-ead7-53d3-821f-956df5f5eba5'
on conflict (version_id, stable_key) do nothing;

update taxonomy_nodes set is_assignable = false
where version_id = 'c39450a8-ead7-53d3-821f-956df5f5eba5'
  and stable_key in (
      'food_dining.groceries.pantry_cooking.pulses_legumes.lentils',
      'food_dining.groceries.frozen_food.frozen_produce'
  );

insert into taxonomy_node_closure (version_id, ancestor_id, descendant_id, distance)
select node.version_id, node.id, node.id, 0
from taxonomy_nodes node
where node.version_id = 'c39450a8-ead7-53d3-821f-956df5f5eba5'
  and node.stable_key in (
      'food_dining.groceries.grains_pasta.flour.corn_flour',
      'food_dining.groceries.grains_pasta.flour.ragi_flour',
      'food_dining.groceries.grains_pasta.flour.sooji',
      'food_dining.groceries.pantry_cooking.pulses_legumes.lentils.urad',
      'food_dining.groceries.pantry_cooking.pulses_legumes.lentils.moong',
      'food_dining.groceries.frozen_food.frozen_produce.frozen_berries',
      'food_dining.groceries.frozen_food.frozen_produce.frozen_peas',
      'food_dining.groceries.frozen_food.frozen_produce.frozen_coconut'
  )
on conflict do nothing;

insert into taxonomy_node_closure (version_id, ancestor_id, descendant_id, distance)
select node.version_id, path.ancestor_id, node.id, path.distance + 1
from taxonomy_nodes node
join taxonomy_node_closure path on path.descendant_id = node.parent_id
    and path.version_id = node.version_id
where node.version_id = 'c39450a8-ead7-53d3-821f-956df5f5eba5'
  and node.stable_key in (
      'food_dining.groceries.grains_pasta.flour.corn_flour',
      'food_dining.groceries.grains_pasta.flour.ragi_flour',
      'food_dining.groceries.grains_pasta.flour.sooji',
      'food_dining.groceries.pantry_cooking.pulses_legumes.lentils.urad',
      'food_dining.groceries.pantry_cooking.pulses_legumes.lentils.moong',
      'food_dining.groceries.frozen_food.frozen_produce.frozen_berries',
      'food_dining.groceries.frozen_food.frozen_produce.frozen_peas',
      'food_dining.groceries.frozen_food.frozen_produce.frozen_coconut'
  )
on conflict do nothing;

insert into taxonomy_synonyms (version_id, node_id, term, locale)
select node.version_id, node.id, terms.term, 'en'
from taxonomy_nodes node
cross join lateral unnest(case node.stable_key
    when 'food_dining.groceries.grains_pasta.flour.corn_flour' then array['yellow corn flour', 'maize flour']
    when 'food_dining.groceries.grains_pasta.flour.ragi_flour' then array['finger millet flour']
    when 'food_dining.groceries.grains_pasta.flour.sooji' then array['semolina', 'rava']
    when 'food_dining.groceries.pantry_cooking.pulses_legumes.lentils.urad' then array['urad gota', 'black gram']
    when 'food_dining.groceries.pantry_cooking.pulses_legumes.lentils.moong' then array['mung beans', 'green gram']
    when 'food_dining.groceries.frozen_food.frozen_produce.frozen_berries' then array['frozen berry blend', 'frozen mixed berries']
    when 'food_dining.groceries.frozen_food.frozen_produce.frozen_peas' then array['frozen green peas']
    when 'food_dining.groceries.frozen_food.frozen_produce.frozen_coconut' then array['frozen shredded coconut']
    else array[]::text[] end) as terms(term)
where node.version_id = 'c39450a8-ead7-53d3-821f-956df5f5eba5'
on conflict do nothing;

commit;
