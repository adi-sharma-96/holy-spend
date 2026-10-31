-- Conservative classification repair. No prices, quantities, or totals change.
-- Only explicit, unambiguous product text is eligible; brand alone is not evidence.
-- Only raw receipt text is evidence; interpreted names may contain earlier guesses.
-- Preserve user-authored and reviewed classifications.
-- Old aliases/concepts are intentionally not rewritten from a single occurrence.
begin;

create temporary table specific_product_rules (
    source_key text not null,
    target_key text not null,
    type_pattern text not null,
    detail_pattern text not null default '.',
    excluded_pattern text not null default '\m(mixed|mix|blend|juice|smoothie|drink|lassi|kefir)\M'
) on commit drop;

insert into specific_product_rules (source_key, target_key, type_pattern)
values
('produce.fruit.tropical.tropical_other', 'produce.fruit.tropical.kiwis', '\m(kiwi|kiwis|kiwifruit)\M'),
('produce.fruit.tropical.tropical_other', 'produce.fruit.tropical.lychees', '\m(lychee|lychees|litchi|litchis)\M'),
('produce.fruit.tropical.tropical_other', 'produce.fruit.tropical.rambutans', '\m(rambutan|rambutans)\M'),
('produce.fruit.tropical.tropical_other', 'produce.fruit.tropical.dragon_fruit', '\m(dragon fruit|pitaya|pitahaya)\M'),
('produce.fruit.tropical.tropical_other', 'produce.fruit.tropical.passion_fruit', '\mpassion fruit\M'),
('dairy_eggs.yogurt_fermented.yogurt', 'dairy_eggs.yogurt_fermented.dahi', '\mdahi\M'),
('dairy_eggs.yogurt_fermented.yogurt', 'dairy_eggs.yogurt_fermented.skyr', '\mskyr\M');

insert into specific_product_rules (source_key, target_key, type_pattern, detail_pattern)
values
('dairy_eggs.yogurt_fermented.yogurt', 'dairy_eggs.yogurt_fermented.greek_yogurt.plain', '\mgreek\M', '\mplain\M'),
('dairy_eggs.yogurt_fermented.yogurt', 'dairy_eggs.yogurt_fermented.greek_yogurt.flavoured', '\mgreek\M', '\m(flavou?red|strawberry|vanilla|blueberry|raspberry|peach)\M'),
('dairy_eggs.yogurt_fermented.yogurt', 'dairy_eggs.yogurt_fermented.regular_yogurt.plain', '\mregular\M', '\mplain\M'),
('dairy_eggs.yogurt_fermented.yogurt', 'dairy_eggs.yogurt_fermented.regular_yogurt.flavoured', '\mregular\M', '\m(flavou?red|strawberry|vanilla|blueberry|raspberry|peach)\M');

-- Matching multiple types/flavours is ambiguous and must not select an arbitrary rule.
-- Conflicting type words are unsafe even if the other type lacks flavour evidence.
update specific_product_rules
set excluded_pattern = excluded_pattern || '|\m(' || case
    when target_key like '%.greek_yogurt.%' then 'regular|dahi|skyr'
    when target_key like '%.regular_yogurt.%' then 'greek|dahi|skyr'
    when target_key like '%.dahi' then 'greek|regular|skyr'
    when target_key like '%.skyr' then 'greek|regular|dahi'
end || ')\M'
where source_key = 'dairy_eggs.yogurt_fermented.yogurt';

with candidates as (
    select item.id, item.user_id, target.id as target_id
    from transaction_items item
    join taxonomy_nodes source on source.id = item.taxonomy_node_id
    join taxonomy_versions version on version.id = source.version_id and version.status = 'active'
    join specific_product_rules rule on source.stable_key = 'food_dining.groceries.' || rule.source_key
    join taxonomy_nodes target on target.version_id = source.version_id
        and target.stable_key = 'food_dining.groceries.' || rule.target_key
        and target.is_assignable
    cross join lateral (
        select lower(item.raw_name) as name
    ) evidence
    where item.classification_source <> 'user'
      and item.classification_review_status = 'suggested'
      and item.classification_reviewed_at is null
      and evidence.name ~ rule.type_pattern
      and evidence.name ~ rule.detail_pattern
      and evidence.name !~ rule.excluded_pattern
), unambiguous as (
    select id, user_id, (array_agg(target_id))[1] as target_id
    from candidates
    group by id, user_id
    having count(distinct target_id) = 1
)
update transaction_items item
set taxonomy_node_id = repair.target_id,
    classification_source = 'migration',
    classification_confidence = null,
    classification_review_status = 'suggested',
    classification_reviewed_at = null
from unambiguous repair
where item.id = repair.id and item.user_id = repair.user_id;

commit;
