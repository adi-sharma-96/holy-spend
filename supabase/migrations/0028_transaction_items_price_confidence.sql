-- External review: the price normalizer's bare-quantity fallback ("no unit captured,
-- treat quantity as N each") can't tell a genuinely single item apart from a multi-count
-- package whose package_value/package_unit was never captured (the eggs/avocado bug -
-- see the 2026-08-15 correction on transaction 6d191cea-5b5b-503d-9322-d34506a2017f).
-- app/measurements.py now flags that specific fallback path so Price Watch and My
-- Inflation can exclude it from confident price-change comparisons instead of treating
-- an ungrounded per-carton price as a per-egg one.

alter table transaction_items
    add column normalized_price_is_estimated boolean not null default false;

comment on column transaction_items.normalized_price_is_estimated is
    'True when normalized_unit_price_amount came from the bare quantity/"each" fallback '
    '(no printed basis, measured_value, or package_value) - too uncertain to trust for '
    'automated price-change comparisons.';
