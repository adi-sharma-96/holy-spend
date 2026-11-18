begin;

-- Preserve original label units and matching evidence for newly saved results.
-- Existing normalized facts have no verified original protein basis.
alter table nutrition_lookups add column protein_label jsonb;

commit;
