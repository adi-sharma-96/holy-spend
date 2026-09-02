-- Reassign historical transaction_items into the new, more specific grocery
-- taxonomy leaves added this session (see taxonomy/v2/taxonomy.yaml, e.g.
-- alliums -> onions/garlic/leeks, nuts_seeds -> almonds/cashews/walnuts) so
-- historical Price Watch / My Inflation data is consistent with newly
-- confirmed purchases rather than stuck on the now-internal (non-assignable)
-- parent node. Deliberately data-driven via regex against
-- raw_name/interpreted_name/normalized_name using the Postgres \m/\M
-- word-boundary metacharacters, the same pattern already used in
-- 0014_repair_taxonomy_reporting.sql. Items matching no rule are left on the
-- parent node as-is: still readable, just outside Price Watch until a future
-- purchase or manual correction resolves it more specifically.

begin;

create temporary table taxonomy_v2_grocery_split_repairs (
    item_id uuid primary key,
    user_id uuid not null,
    concept_id uuid,
    alias_name text,
    current_node_id uuid not null,
    target_node_id uuid not null
) on commit drop;

insert into taxonomy_v2_grocery_split_repairs (
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
        when current_node.stable_key = 'food_dining.groceries.produce.fruit.apples_pears' then
            case
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mpear(s)?\M'
                    then 'food_dining.groceries.produce.fruit.apples_pears.pears'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mapple(s)?\M'
                    then 'food_dining.groceries.produce.fruit.apples_pears.apples'
                else null
            end
        when current_node.stable_key = 'food_dining.groceries.produce.fruit.bananas_plantains' then
            case
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mplantain(s)?\M'
                    then 'food_dining.groceries.produce.fruit.bananas_plantains.plantains'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mbanana(s)?\M'
                    then 'food_dining.groceries.produce.fruit.bananas_plantains.bananas'
                else null
            end
        when current_node.stable_key = 'food_dining.groceries.produce.fruit.berries' then
            case
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mstrawberr(y|ies)\M'
                    then 'food_dining.groceries.produce.fruit.berries.strawberries'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mblueberr(y|ies)\M'
                    then 'food_dining.groceries.produce.fruit.berries.blueberries'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mraspberr(y|ies)\M'
                    then 'food_dining.groceries.produce.fruit.berries.raspberries'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mblackberr(y|ies)\M'
                    then 'food_dining.groceries.produce.fruit.berries.blackberries'
                else null
            end
        when current_node.stable_key = 'food_dining.groceries.produce.fruit.citrus' then
            case
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\morange(s)?\M'
                    then 'food_dining.groceries.produce.fruit.citrus.oranges'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mlemon(s)?\M'
                    then 'food_dining.groceries.produce.fruit.citrus.lemons'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mlime(s)?\M'
                    then 'food_dining.groceries.produce.fruit.citrus.limes'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mgrapefruit(s)?\M'
                    then 'food_dining.groceries.produce.fruit.citrus.grapefruit'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mmandarin(s)?\M'
                    then 'food_dining.groceries.produce.fruit.citrus.mandarins'
                else null
            end
        when current_node.stable_key = 'food_dining.groceries.produce.fruit.melons' then
            case
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mwatermelon(s)?\M'
                    then 'food_dining.groceries.produce.fruit.melons.watermelon'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mcantaloupe(s)?\M'
                    then 'food_dining.groceries.produce.fruit.melons.cantaloupe'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mhoneydew(s)?\M'
                    then 'food_dining.groceries.produce.fruit.melons.honeydew'
                else null
            end
        when current_node.stable_key = 'food_dining.groceries.produce.fruit.stone_fruit' then
            case
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mpeach(es)?\M'
                    then 'food_dining.groceries.produce.fruit.stone_fruit.peaches'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mnectarine(s)?\M'
                    then 'food_dining.groceries.produce.fruit.stone_fruit.nectarines'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mplum(s)?\M'
                    then 'food_dining.groceries.produce.fruit.stone_fruit.plums'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mcherr(y|ies)\M'
                    then 'food_dining.groceries.produce.fruit.stone_fruit.cherries'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mapricot(s)?\M'
                    then 'food_dining.groceries.produce.fruit.stone_fruit.apricots'
                else null
            end
        when current_node.stable_key = 'food_dining.groceries.produce.fruit.tropical' then
            case
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mmango(e?s)?\M'
                    then 'food_dining.groceries.produce.fruit.tropical.mangoes'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mpineapple(s)?\M'
                    then 'food_dining.groceries.produce.fruit.tropical.pineapples'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mpapaya(s)?\M'
                    then 'food_dining.groceries.produce.fruit.tropical.papayas'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mcoconut(s)?\M'
                    then 'food_dining.groceries.produce.fruit.tropical.coconuts'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mguava(s)?\M'
                    then 'food_dining.groceries.produce.fruit.tropical.guavas'
                else null
            end
        when current_node.stable_key = 'food_dining.groceries.produce.vegetables.leafy_greens' then
            case
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mlettuce\M'
                    then 'food_dining.groceries.produce.vegetables.leafy_greens.lettuce'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mspinach\M'
                    then 'food_dining.groceries.produce.vegetables.leafy_greens.spinach'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mkale\M'
                    then 'food_dining.groceries.produce.vegetables.leafy_greens.kale'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mchard\M'
                    then 'food_dining.groceries.produce.vegetables.leafy_greens.chard'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\marugula\M'
                    then 'food_dining.groceries.produce.vegetables.leafy_greens.arugula'
                else null
            end
        when current_node.stable_key = 'food_dining.groceries.produce.vegetables.cruciferous' then
            case
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mbroccoli\M'
                    then 'food_dining.groceries.produce.vegetables.cruciferous.broccoli'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mcauliflower\M'
                    then 'food_dining.groceries.produce.vegetables.cruciferous.cauliflower'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mcabbage\M'
                    then 'food_dining.groceries.produce.vegetables.cruciferous.cabbage'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mbrussels?[[:space:]]+sprout(s)?\M'
                    then 'food_dining.groceries.produce.vegetables.cruciferous.brussels_sprouts'
                else null
            end
        when current_node.stable_key = 'food_dining.groceries.produce.vegetables.roots_tubers' then
            case
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mcarrot(s)?\M'
                    then 'food_dining.groceries.produce.vegetables.roots_tubers.carrots'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mbeet(s)?\M'
                    then 'food_dining.groceries.produce.vegetables.roots_tubers.beets'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mradish(es)?\M'
                    then 'food_dining.groceries.produce.vegetables.roots_tubers.radishes'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mturnip(s)?\M'
                    then 'food_dining.groceries.produce.vegetables.roots_tubers.turnips'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mcassava\M'
                    then 'food_dining.groceries.produce.vegetables.roots_tubers.cassava'
                else null
            end
        when current_node.stable_key = 'food_dining.groceries.produce.vegetables.potatoes' then
            case
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\m(sweet[[:space:]]+potato(es)?|yam(s)?)\M'
                    then 'food_dining.groceries.produce.vegetables.potatoes.sweet_potatoes'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mpotato(es)?\M'
                    then 'food_dining.groceries.produce.vegetables.potatoes.regular_potatoes'
                else null
            end
        when current_node.stable_key = 'food_dining.groceries.produce.vegetables.alliums' then
            case
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\monion(s)?\M'
                    then 'food_dining.groceries.produce.vegetables.alliums.onions'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mgarlic\M'
                    then 'food_dining.groceries.produce.vegetables.alliums.garlic'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mleek(s)?\M'
                    then 'food_dining.groceries.produce.vegetables.alliums.leeks'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mshallot(s)?\M'
                    then 'food_dining.groceries.produce.vegetables.alliums.shallots'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mscallion(s)?\M'
                    then 'food_dining.groceries.produce.vegetables.alliums.scallions'
                else null
            end
        when current_node.stable_key = 'food_dining.groceries.produce.vegetables.squash_gourds' then
            case
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mzucchini\M'
                    then 'food_dining.groceries.produce.vegetables.squash_gourds.zucchini'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mcucumber(s)?\M'
                    then 'food_dining.groceries.produce.vegetables.squash_gourds.cucumbers'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mpumpkin(s)?\M'
                    then 'food_dining.groceries.produce.vegetables.squash_gourds.pumpkin'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\m(squash|gourd(s)?)\M'
                    then 'food_dining.groceries.produce.vegetables.squash_gourds.squash'
                else null
            end
        when current_node.stable_key = 'food_dining.groceries.produce.vegetables.stalk_pod' then
            case
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mcelery\M'
                    then 'food_dining.groceries.produce.vegetables.stalk_pod.celery'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\masparagus\M'
                    then 'food_dining.groceries.produce.vegetables.stalk_pod.asparagus'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mgreen[[:space:]]+bean(s)?\M'
                    then 'food_dining.groceries.produce.vegetables.stalk_pod.green_beans'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mpea(s)?\M'
                    then 'food_dining.groceries.produce.vegetables.stalk_pod.peas'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\m(okra|bhindi)\M'
                    then 'food_dining.groceries.produce.vegetables.stalk_pod.okra'
                else null
            end
        when current_node.stable_key = 'food_dining.groceries.produce.herbs_aromatics' then
            case
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mginger\M'
                    then 'food_dining.groceries.produce.herbs_aromatics.ginger'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mcilantro\M'
                    then 'food_dining.groceries.produce.herbs_aromatics.cilantro'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mparsley\M'
                    then 'food_dining.groceries.produce.herbs_aromatics.parsley'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mbasil\M'
                    then 'food_dining.groceries.produce.herbs_aromatics.basil'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mmint\M'
                    then 'food_dining.groceries.produce.herbs_aromatics.mint'
                else null
            end
        when current_node.stable_key = 'food_dining.groceries.dairy_eggs.dairy_alternatives.plant_milk' then
            case
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\moat[[:space:]-]+milk\M'
                    then 'food_dining.groceries.dairy_eggs.dairy_alternatives.plant_milk.oat_milk'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\malmond[[:space:]-]+milk\M'
                    then 'food_dining.groceries.dairy_eggs.dairy_alternatives.plant_milk.almond_milk'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\msoy[[:space:]-]+milk\M'
                    then 'food_dining.groceries.dairy_eggs.dairy_alternatives.plant_milk.soy_milk'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mcoconut[[:space:]-]+milk\M'
                    then 'food_dining.groceries.dairy_eggs.dairy_alternatives.plant_milk.coconut_milk_beverage'
                else null
            end
        when current_node.stable_key = 'food_dining.groceries.dairy_eggs.cheese.fresh_soft' then
            case
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mpaneer\M'
                    then 'food_dining.groceries.dairy_eggs.cheese.fresh_soft.paneer'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mricotta\M'
                    then 'food_dining.groceries.dairy_eggs.cheese.fresh_soft.ricotta'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mcottage[[:space:]]+cheese\M'
                    then 'food_dining.groceries.dairy_eggs.cheese.fresh_soft.cottage_cheese'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mcream[[:space:]]+cheese\M'
                    then 'food_dining.groceries.dairy_eggs.cheese.fresh_soft.cream_cheese'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mmozzarella\M'
                    then 'food_dining.groceries.dairy_eggs.cheese.fresh_soft.mozzarella'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mfeta\M'
                    then 'food_dining.groceries.dairy_eggs.cheese.fresh_soft.feta'
                else null
            end
        when current_node.stable_key = 'food_dining.groceries.dairy_eggs.cheese.hard_aged' then
            case
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mcheddar\M'
                    then 'food_dining.groceries.dairy_eggs.cheese.hard_aged.cheddar'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mparmesan\M'
                    then 'food_dining.groceries.dairy_eggs.cheese.hard_aged.parmesan'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mgouda\M'
                    then 'food_dining.groceries.dairy_eggs.cheese.hard_aged.gouda'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mswiss[[:space:]]+cheese\M'
                    then 'food_dining.groceries.dairy_eggs.cheese.hard_aged.swiss_cheese'
                else null
            end
        when current_node.stable_key = 'food_dining.groceries.dairy_eggs.butter_fats' then
            case
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mghee\M'
                    then 'food_dining.groceries.dairy_eggs.butter_fats.ghee'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mbutter\M'
                    then 'food_dining.groceries.dairy_eggs.butter_fats.butter'
                else null
            end
        when current_node.stable_key = 'food_dining.groceries.meat_seafood_alternatives.seafood.fish' then
            case
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\msalmon\M'
                    then 'food_dining.groceries.meat_seafood_alternatives.seafood.fish.salmon'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mtuna\M'
                    then 'food_dining.groceries.meat_seafood_alternatives.seafood.fish.tuna'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mtilapia\M'
                    then 'food_dining.groceries.meat_seafood_alternatives.seafood.fish.tilapia'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mcod\M'
                    then 'food_dining.groceries.meat_seafood_alternatives.seafood.fish.cod'
                else null
            end
        when current_node.stable_key = 'food_dining.groceries.meat_seafood_alternatives.seafood.shellfish' then
            case
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\m(shrimp|prawn(s)?)\M'
                    then 'food_dining.groceries.meat_seafood_alternatives.seafood.shellfish.shrimp'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mcrab(s)?\M'
                    then 'food_dining.groceries.meat_seafood_alternatives.seafood.shellfish.crab'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mlobster(s)?\M'
                    then 'food_dining.groceries.meat_seafood_alternatives.seafood.shellfish.lobster'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mmussels?\M'
                    then 'food_dining.groceries.meat_seafood_alternatives.seafood.shellfish.mussels'
                else null
            end
        when current_node.stable_key = 'food_dining.groceries.meat_seafood_alternatives.plant_proteins.tofu_tempeh' then
            case
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mtempeh\M'
                    then 'food_dining.groceries.meat_seafood_alternatives.plant_proteins.tofu_tempeh.tempeh'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mtofu\M'
                    then 'food_dining.groceries.meat_seafood_alternatives.plant_proteins.tofu_tempeh.tofu'
                else null
            end
        when current_node.stable_key = 'food_dining.groceries.bread_bakery.flatbreads' then
            case
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mnaan\M'
                    then 'food_dining.groceries.bread_bakery.flatbreads.naan'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mroti\M'
                    then 'food_dining.groceries.bread_bakery.flatbreads.roti'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mpita\M'
                    then 'food_dining.groceries.bread_bakery.flatbreads.pita'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mtortilla(s)?\M'
                    then 'food_dining.groceries.bread_bakery.flatbreads.tortillas'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mphulka\M'
                    then 'food_dining.groceries.bread_bakery.flatbreads.phulka'
                else null
            end
        when current_node.stable_key = 'food_dining.groceries.bread_bakery.pastries' then
            case
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mcroissant(s)?\M'
                    then 'food_dining.groceries.bread_bakery.pastries.croissants'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mdanish(es)?\M'
                    then 'food_dining.groceries.bread_bakery.pastries.danishes'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mmuffin(s)?\M'
                    then 'food_dining.groceries.bread_bakery.pastries.muffins'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\m(doughnut|donut)(s)?\M'
                    then 'food_dining.groceries.bread_bakery.pastries.doughnuts'
                else null
            end
        when current_node.stable_key = 'food_dining.groceries.grains_pasta.noodles' then
            case
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mramen\M'
                    then 'food_dining.groceries.grains_pasta.noodles.ramen'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mrice[[:space:]]+noodle(s)?\M'
                    then 'food_dining.groceries.grains_pasta.noodles.rice_noodles'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\megg[[:space:]]+noodle(s)?\M'
                    then 'food_dining.groceries.grains_pasta.noodles.egg_noodles'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mudon\M'
                    then 'food_dining.groceries.grains_pasta.noodles.udon'
                else null
            end
        when current_node.stable_key = 'food_dining.groceries.grains_pasta.whole_grains' then
            case
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mquinoa\M'
                    then 'food_dining.groceries.grains_pasta.whole_grains.quinoa'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mbarley\M'
                    then 'food_dining.groceries.grains_pasta.whole_grains.barley'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mfarro\M'
                    then 'food_dining.groceries.grains_pasta.whole_grains.farro'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mmillet\M'
                    then 'food_dining.groceries.grains_pasta.whole_grains.millet'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mbulgur\M'
                    then 'food_dining.groceries.grains_pasta.whole_grains.bulgur'
                else null
            end
        when current_node.stable_key = 'food_dining.groceries.grains_pasta.flour' then
            case
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mchickpea[[:space:]]+flour\M'
                    then 'food_dining.groceries.grains_pasta.flour.chickpea_flour'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\matta\M'
                    then 'food_dining.groceries.grains_pasta.flour.atta'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mbread[[:space:]]+flour\M'
                    then 'food_dining.groceries.grains_pasta.flour.bread_flour'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mflour\M'
                    then 'food_dining.groceries.grains_pasta.flour.all_purpose_flour'
                else null
            end
        when current_node.stable_key = 'food_dining.groceries.pantry_cooking.pulses_legumes.beans' then
            case
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mblack[[:space:]]+bean(s)?\M'
                    then 'food_dining.groceries.pantry_cooking.pulses_legumes.beans.black_beans'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\m(kidney[[:space:]]+bean(s)?|rajma)\M'
                    then 'food_dining.groceries.pantry_cooking.pulses_legumes.beans.kidney_beans'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mnavy[[:space:]]+bean(s)?\M'
                    then 'food_dining.groceries.pantry_cooking.pulses_legumes.beans.navy_beans'
                else null
            end
        when current_node.stable_key = 'food_dining.groceries.pantry_cooking.oils_vinegars' then
            case
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\molive[[:space:]]+oil\M'
                    then 'food_dining.groceries.pantry_cooking.oils_vinegars.olive_oil'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mvinegar\M'
                    then 'food_dining.groceries.pantry_cooking.oils_vinegars.vinegar'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\m(cooking|vegetable|sunflower|canola)[[:space:]]+oil\M'
                    then 'food_dining.groceries.pantry_cooking.oils_vinegars.cooking_oil'
                else null
            end
        when current_node.stable_key = 'food_dining.groceries.pantry_cooking.cooking_bases' then
            case
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mginger[[:space:]]+garlic\M'
                    then 'food_dining.groceries.pantry_cooking.cooking_bases.ginger_garlic_paste'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mgarlic[[:space:]]+paste\M'
                    then 'food_dining.groceries.pantry_cooking.cooking_bases.garlic_paste'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mcurry[[:space:]]+paste\M'
                    then 'food_dining.groceries.pantry_cooking.cooking_bases.curry_paste'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\m(stock|broth)\M'
                    then 'food_dining.groceries.pantry_cooking.cooking_bases.stock_broth'
                else null
            end
        when current_node.stable_key = 'food_dining.groceries.pantry_cooking.spreads' then
            case
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mpeanut[[:space:]]+butter\M'
                    then 'food_dining.groceries.pantry_cooking.spreads.peanut_butter'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mchocolate[[:space:]]+spread\M'
                    then 'food_dining.groceries.pantry_cooking.spreads.chocolate_spread'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\m(jam|jelly|preserves?)\M'
                    then 'food_dining.groceries.pantry_cooking.spreads.jam'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mnut[[:space:]]+butter\M'
                    then 'food_dining.groceries.pantry_cooking.spreads.nut_butter'
                else null
            end
        when current_node.stable_key = 'food_dining.groceries.pantry_cooking.sweeteners' then
            case
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mhoney\M'
                    then 'food_dining.groceries.pantry_cooking.sweeteners.honey'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mmaple[[:space:]]+syrup\M'
                    then 'food_dining.groceries.pantry_cooking.sweeteners.maple_syrup'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\m(artificial[[:space:]]+sweetener|splenda|stevia|sucralose)\M'
                    then 'food_dining.groceries.pantry_cooking.sweeteners.artificial_sweetener'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\msugar\M'
                    then 'food_dining.groceries.pantry_cooking.sweeteners.sugar'
                else null
            end
        when current_node.stable_key = 'food_dining.groceries.pantry_cooking.sauces_condiments' then
            case
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mpasta[[:space:]]+sauce\M'
                    then 'food_dining.groceries.pantry_cooking.sauces_condiments.pasta_sauce'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mketchup\M'
                    then 'food_dining.groceries.pantry_cooking.sauces_condiments.ketchup'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mmustard\M'
                    then 'food_dining.groceries.pantry_cooking.sauces_condiments.mustard'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\m(mayonnaise|mayo)\M'
                    then 'food_dining.groceries.pantry_cooking.sauces_condiments.mayonnaise'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mhot[[:space:]]+sauce\M'
                    then 'food_dining.groceries.pantry_cooking.sauces_condiments.hot_sauce'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\msoy[[:space:]]+sauce\M'
                    then 'food_dining.groceries.pantry_cooking.sauces_condiments.soy_sauce'
                else null
            end
        when current_node.stable_key = 'food_dining.groceries.snacks_confectionery.nuts_seeds' then
            case
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mmixed[[:space:]-]+nuts?\M'
                    then 'food_dining.groceries.snacks_confectionery.nuts_seeds.mixed_nuts'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\malmond(s)?\M'
                    then 'food_dining.groceries.snacks_confectionery.nuts_seeds.almonds'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mcashew(s)?\M'
                    then 'food_dining.groceries.snacks_confectionery.nuts_seeds.cashews'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mwalnut(s)?\M'
                    then 'food_dining.groceries.snacks_confectionery.nuts_seeds.walnuts'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mpistachio(s)?\M'
                    then 'food_dining.groceries.snacks_confectionery.nuts_seeds.pistachios'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\mpeanut(s)?\M'
                    then 'food_dining.groceries.snacks_confectionery.nuts_seeds.peanuts'
                when lower(concat_ws(' ', item.raw_name, item.interpreted_name, item.normalized_name)) ~ '\msunflower[[:space:]]+seed(s)?\M'
                    then 'food_dining.groceries.snacks_confectionery.nuts_seeds.sunflower_seeds'
                else null
            end
        else null
    end as stable_key
) rule
join taxonomy_nodes target
  on target.version_id = current_node.version_id
 and target.stable_key = rule.stable_key
 and target.is_assignable = true
where current_node.stable_key = any(array[
    'food_dining.groceries.produce.fruit.apples_pears',
    'food_dining.groceries.produce.fruit.bananas_plantains',
    'food_dining.groceries.produce.fruit.berries',
    'food_dining.groceries.produce.fruit.citrus',
    'food_dining.groceries.produce.fruit.melons',
    'food_dining.groceries.produce.fruit.stone_fruit',
    'food_dining.groceries.produce.fruit.tropical',
    'food_dining.groceries.produce.vegetables.leafy_greens',
    'food_dining.groceries.produce.vegetables.cruciferous',
    'food_dining.groceries.produce.vegetables.roots_tubers',
    'food_dining.groceries.produce.vegetables.potatoes',
    'food_dining.groceries.produce.vegetables.alliums',
    'food_dining.groceries.produce.vegetables.squash_gourds',
    'food_dining.groceries.produce.vegetables.stalk_pod',
    'food_dining.groceries.produce.herbs_aromatics',
    'food_dining.groceries.dairy_eggs.dairy_alternatives.plant_milk',
    'food_dining.groceries.dairy_eggs.cheese.fresh_soft',
    'food_dining.groceries.dairy_eggs.cheese.hard_aged',
    'food_dining.groceries.dairy_eggs.butter_fats',
    'food_dining.groceries.meat_seafood_alternatives.seafood.fish',
    'food_dining.groceries.meat_seafood_alternatives.seafood.shellfish',
    'food_dining.groceries.meat_seafood_alternatives.plant_proteins.tofu_tempeh',
    'food_dining.groceries.bread_bakery.flatbreads',
    'food_dining.groceries.bread_bakery.pastries',
    'food_dining.groceries.grains_pasta.noodles',
    'food_dining.groceries.grains_pasta.whole_grains',
    'food_dining.groceries.grains_pasta.flour',
    'food_dining.groceries.pantry_cooking.pulses_legumes.beans',
    'food_dining.groceries.pantry_cooking.oils_vinegars',
    'food_dining.groceries.pantry_cooking.cooking_bases',
    'food_dining.groceries.pantry_cooking.spreads',
    'food_dining.groceries.pantry_cooking.sweeteners',
    'food_dining.groceries.pantry_cooking.sauces_condiments',
    'food_dining.groceries.snacks_confectionery.nuts_seeds'
])
  and rule.stable_key is not null;

update transaction_items item
set taxonomy_node_id = repair.target_node_id,
    classification_source = 'migration',
    classification_confidence = 1,
    classification_review_status = 'reviewed',
    classification_reviewed_at = now()
from taxonomy_v2_grocery_split_repairs repair
where item.id = repair.item_id
  and item.user_id = repair.user_id;

-- Confirmed-item aliases are authoritative on later receipts — repair them
-- the same way so a future purchase of the same raw text lands directly on
-- the new specific leaf instead of bouncing back to the old coarse one.
update user_product_aliases alias
set taxonomy_node_id = repair.target_node_id,
    updated_at = now()
from taxonomy_v2_grocery_split_repairs repair
where alias.user_id = repair.user_id
  and alias.raw_name_normalized = repair.alias_name
  and alias.taxonomy_node_id = repair.current_node_id;

-- A product concept can be repaired automatically only when every repaired
-- occurrence of that concept (under a given old parent) resolves to the
-- same new leaf.
with concept_repairs as (
    select
        repair.concept_id,
        repair.current_node_id,
        (array_agg(repair.target_node_id))[1] as target_node_id
    from taxonomy_v2_grocery_split_repairs repair
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
