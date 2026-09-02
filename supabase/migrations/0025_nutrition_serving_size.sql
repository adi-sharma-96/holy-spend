-- Persist the source's serving-size breakdown alongside the per-100g nutriments blob, so
-- the nutrition drawer can offer a per-serving display toggle. NutrimentsInput already
-- receives serving_size_g as a conversion-factor input at save time (see to_per_100g() in
-- app/plugin_models.py), but it was discarded after conversion instead of stored. This is
-- display-only: compute_nutriscore() keeps receiving per-100g values exactly as before,
-- these columns are never read by app/nutrition_score.py.

alter table nutrition_lookups
    add column serving_size_g numeric,
    add column serving_label text;

comment on column nutrition_lookups.serving_size_g is
    'Serving size in grams, as reported by the source at save time (NutrimentsInput.serving_size_g). '
    'Null when the source reported per-100g directly, or didn''t state a serving breakdown at all. '
    'Existing rows are null until re-matched - no backfill.';
comment on column nutrition_lookups.serving_label is
    'Human-readable serving description exactly as the source states it (e.g. "2 tbsp (30 mL)"), '
    'shown as the "per ___" subtitle when the per-serving display toggle is on. Null under the same '
    'conditions as serving_size_g - the two are always saved together.';
