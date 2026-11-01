-- Decisions remain append-only; a later explicit review may supersede a defer
-- or rejection at the same item revision. Operation IDs still provide retry
-- idempotency and each decision remains owner-scoped.
do $$
declare
    old_constraint text;
begin
    select conname into old_constraint
    from pg_constraint
    where conrelid = 'product_review_decisions'::regclass
      and contype = 'u'
      and pg_get_constraintdef(oid) like '%(user_id, item_id, issue_key, evidence_revision)%';
    if old_constraint is not null then
        execute format('alter table product_review_decisions drop constraint %I', old_constraint);
    end if;
end $$;

create index product_review_decisions_latest_idx
    on product_review_decisions(user_id, item_id, issue_key, evidence_revision, created_at desc, id desc);
