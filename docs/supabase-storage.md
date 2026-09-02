# Supabase receipt storage

Receipt originals live in the private `receipt-originals` bucket. Object keys are
server-owned:

```text
users/{owner_id}/receipts/{receipt_id}/{sha256-prefix}-{request-hash}.{ext}
```

The client never chooses a bucket, object key, or owner ID. Browser upload
targets, multipart receipt upload, and empty receipt-envelope endpoints have been
removed.

## Configuration

```dotenv
SUPABASE_URL=https://project.supabase.co
SUPABASE_SECRET_KEY=...
STORAGE_BUCKET=receipt-originals
STORAGE_SIGNED_URL_TTL_SECONDS=300
MAX_RECEIPT_FILE_BYTES=12582912
RECEIPT_DOWNLOAD_TIMEOUT_SECONDS=20
RECEIPT_DOWNLOAD_CONNECT_TIMEOUT_SECONDS=5
RECEIPT_DOWNLOAD_READ_TIMEOUT_SECONDS=20
RECEIPT_DOWNLOAD_WRITE_TIMEOUT_SECONDS=10
RECEIPT_DOWNLOAD_POOL_TIMEOUT_SECONDS=5
RECEIPT_DOWNLOAD_MAX_REDIRECTS=3
RUN_LIVE_STORAGE_TESTS=0
```

Keep the secret key server-side. The bucket must remain private.

## Chat receipt flow

`create_receipt_draft_from_file` accepts the official OpenAI file object and the
draft extracted by ChatGPT. It:

1. downloads a bounded authorized URL once;
2. verifies extension, MIME magic, size, and SHA-256;
3. normalizes savings/discount arithmetic;
4. acquires the owner/file-hash lock;
5. persists the populated draft and uploads the original using a deterministic
   server-owned key;
6. records the commit result, or compensates the object on failure.

The backend performs no OCR or PDF text extraction.

Exact hash replays return the linked expense and file. Migration 0012 adds a
unique `(user_id, source_file_sha256)` constraint after approved duplicate
cleanup.

## Viewing and deletion

`get_receipt_download_url` returns a short-lived URL only in tool `_meta`, keeping
it out of model-visible structured content. `delete_receipt_file` removes the
object before marking metadata deleted. Transaction deletion removes all owned
receipt objects before deleting the database record; storage cleanup failures are
queued.

For adapter verification:

```powershell
$env:RUN_LIVE_STORAGE_TESTS="1"
.venv\Scripts\python.exe -m pytest tests/test_storage_live.py -v
$env:RUN_LIVE_STORAGE_TESTS="0"
```
