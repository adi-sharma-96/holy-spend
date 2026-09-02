-- Data-quality overhaul: distinguish pending vs. no-match in the UI, let the scheduled
-- task estimate NOVA from ingredients when unstated (flagged, not silently guessed),
-- and compute Nutri-Score deterministically server-side from macros instead of trusting
-- an AI-reported grade. category_slug is captured once at enqueue time (mirrors the
-- taxonomy join _enqueue_new already does) so save_result can classify beverage-skip /
-- produce-FVL-default without an extra join back through transaction_items later.
-- New nutrient fields (trans fat, added sugars, cholesterol, potassium, calcium, iron)
-- need no column - they're new optional keys in the existing nutriments jsonb blob.

alter table nutrition_lookups
    add column category_slug text,
    add column nova_group_estimated boolean not null default false,
    add column nutriscore_source text
        check (nutriscore_source in ('computed', 'source_stated')),
    add column fvl_percent numeric;

comment on column nutrition_lookups.category_slug is
    'Leaf grocery taxonomy stable_key captured at enqueue time; used to skip Nutri-Score '
    'computation for beverages and to default fruit/veg/legume/nut % for produce.';
comment on column nutrition_lookups.nova_group_estimated is
    'true when nova_group was modeled from an ingredient list rather than stated by the '
    'source; the UI must badge these distinctly from source-stated NOVA groups.';
comment on column nutrition_lookups.nutriscore_source is
    'computed = deterministically derived server-side from macros at save time (preferred); '
    'source_stated = an AI-reported grade, used only as a fallback when required macros for '
    'computation are missing. Null when nutriscore_grade is null.';
comment on column nutrition_lookups.fvl_percent is
    'Fruit/veg/legume/nut percent used in the Nutri-Score positive-points calc. Explicit '
    'source-stated value when given, otherwise a taxonomy-derived default applied at save '
    'time (see app/nutrition_score.py). Null means not applicable (e.g. beverages) or the '
    'grade was left source_stated instead of computed.';

-- Backfill category_slug for rows enqueued before this column existed, using the same
-- normalized-name/brand identity expression _enqueue_new already uses to match rows.
update nutrition_lookups nl
set category_slug = matched.stable_key
from (
    select distinct on (item.user_id, identity.identity_key)
        item.user_id,
        identity.identity_key,
        node.stable_key
    from transaction_items item
    join taxonomy_nodes node on node.id = item.taxonomy_node_id
    cross join lateral (
        select
            trim(both '-' from regexp_replace(lower(item.normalized_name), '[^a-z0-9]+', '-', 'g'))
                || '::' ||
                trim(both '-' from regexp_replace(lower(coalesce(item.brand, '')), '[^a-z0-9]+', '-', 'g'))
            as identity_key
    ) identity
    order by item.user_id, identity.identity_key, item.created_at desc
) matched
where nl.owner_user_id = matched.user_id
  and nl.identity_key = matched.identity_key
  and nl.category_slug is null;
