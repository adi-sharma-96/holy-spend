-- External review: two overlapping scheduled-task runs (or a crash mid-processing) could
-- both act on the same message_id since check_email_processed only reflects a *finished*
-- outcome. Adds 'claimed' as an in-progress placeholder status, written atomically by
-- claim_email_for_processing via INSERT ... ON CONFLICT DO NOTHING/DO UPDATE, using the
-- existing unique (owner_user_id, message_id) constraint as the actual concurrency guard.
-- A claim older than an hour is treated as abandoned and eligible for re-claim - see
-- app/email_ingestion_repository.py's claim_for_processing.

alter table email_ingestion_log
    drop constraint email_ingestion_log_status_check,
    add constraint email_ingestion_log_status_check
        check (status in ('claimed', 'drafted', 'flagged', 'not_a_receipt'));
