-- Direct brand capture for transaction items. product_variants.brand exists but is
-- never populated (nothing assigns concept_id/variant_id today), so My Inflation's
-- exact-identity matching (app/personal_basket.py) needs a real, directly-writable
-- column instead of relying on that dead join.

alter table transaction_items add column brand text;
