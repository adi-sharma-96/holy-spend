-- 0026 only constrained status to a valid value, not its relationship to the fields
-- that value implies - a 'drafted' row with no transaction_id, or a 'flagged' row with
-- no note, passed the check constraint silently. app/plugin_models.py's
-- RecordEmailProcessedRequest now enforces this on every real write path, but this
-- table has no other writer today and the same discipline as every other table in
-- this schema (nutrition_lookups, transactions) is to not rely on the API layer alone.

alter table email_ingestion_log
    add constraint email_ingestion_log_drafted_has_transaction
        check (status <> 'drafted' or transaction_id is not null),
    add constraint email_ingestion_log_flagged_has_note
        check (status <> 'flagged' or (note is not null and length(trim(note)) > 0));
