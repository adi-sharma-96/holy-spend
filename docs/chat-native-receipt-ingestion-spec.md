# Chat-native receipt ingestion

Receipt ingestion has one supported entry point:
`create_receipt_draft_from_file(file, draft)`.

## Ownership boundary

- The user attaches the original image or PDF in ChatGPT.
- ChatGPT reads the receipt and produces the structured expense draft.
- The backend performs no OCR, PDF extraction, or receipt interpretation.
- The backend downloads the authorized OpenAI file once, verifies its bytes and
  SHA-256, normalizes arithmetic semantics, and commits the populated draft plus
  private original as one compensated operation.
- The widget has no file input, upload target, polling, or follow-up-message
  extraction workflow.

## Idempotency

The backend serializes commits on `(owner_id, source_file_sha256)`. An exact file
replay returns the existing expense and receipt instead of creating another
record, even when the replay carries a different client request ID or filename.
Migration `0012_owner_scoped_receipt_hash_idempotency.sql` adds the database
constraint after a read-only duplicate audit and approved cleanup.

## Result and review lifecycle

The receipt tool is data-only: it returns the saved expense and validation
projection without mounting an app. Saving, validation, and confirmation stay in
chat unless the user explicitly asks for an interactive view. In that case,
`open_expense_tracker` opens `/expenses/{transaction_id}/review` in the single
`ui://holy-spend/app-v40-<content-hash>.html` resource. The active
expense is refreshed on focus, visibility restoration,
back navigation, and a bounded visible-only interval so chat-side confirmation
appears without reopening a second widget.

## Reconciliation

Displayed, already-discounted line totals are authoritative. A receipt-level
“savings” number is informational (`affects_total=false`) when subtotal, charged
adjustments, and tax already reconcile to the receipt total. A true charged
discount remains arithmetic. Confirmation eligibility is always calculated from
the normalized persisted draft.

## Cleanup rollout

1. Run `python -m scripts.audit_receipt_duplicates` in a read-only transaction.
2. Review exact file-hash groups and likely merchant/date/total/item-count groups.
3. Export a backup of candidate IDs.
4. Keep the confirmed/most complete record and delete only explicitly approved
   duplicates.
5. Apply migration 0012.
6. Re-run the audit and the idempotency smoke test.

Never combine steps 4 or 5 with an application deploy.
