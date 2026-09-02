# Analyze before commit

The extraction engine is ChatGPT. The app never performs OCR.

1. The user attaches a receipt to the chat.
2. ChatGPT extracts merchant, date, currency, total, items, and adjustments.
3. ChatGPT calls `create_receipt_draft_from_file` once with the official file
   parameter and the complete candidate.
4. The backend downloads and verifies the file, normalizes reconciliation, locks
   the owner/file-hash identity, and atomically commits the populated draft and
   private original.
5. The data-only tool returns the expense and validation projection in chat
   without mounting an app.
6. If the user explicitly asks for interactive review, ChatGPT calls
   `open_expense_tracker` with `/expenses/{transaction_id}/review`.
7. Exact file retries return the existing result.

There is no empty receipt envelope, preparation token, temporary staging
directory, browser upload, follow-up chat message, status tool, or duplicate
editor render.
