# Self-hosting

## Architecture

One FastAPI process exposes two transports over the same application and domain services:

- REST/OpenAPI under `/v1/*` for scripts and other integrations;
- MCP Streamable HTTP at `/mcp` for ChatGPT and Codex.

The MCP transport does not accept a caller-supplied user ID. `AUTH_MODE=single_user` resolves every call to `OWNER_USER_ID`, then opens the same transaction-local RLS context used by REST.

## Prerequisites

- Python 3.12+
- Node.js 22+ to build the widget
- PostgreSQL/Supabase with the existing schema
- a private Supabase Storage bucket
- Docker, optionally

## Database

Apply every file in `supabase/migrations` in filename order, including
`0008_mcp_idempotency.sql` and
`0009_item_measurements_and_price_history.sql`, and
`0010_chat_native_receipt_ingestion.sql`, and
`0011_analyze_before_receipt_commit.sql`,
`0012_owner_scoped_receipt_hash_idempotency.sql`, and
`0013_taxonomy_v2.sql`. Migration 0008 adds transaction
notes plus owner-scoped idempotency records for atomic draft saves. Migration
0009 adds paired receipt-measurement fields and indexed normalized unit prices
for comparable price history, and safely backfills existing items that already
have an unambiguous quantity/unit basis.
Migration 0010 adds detailed adjustment fields plus owner-scoped,
retry-safe receipt-ingestion records.
Migration 0011 adds the owner-scoped completed-commit ledger and retryable
Storage cleanup queue. Receipt preparation itself is deliberately ephemeral.
Migration 0012 makes exact-file receipt replay owner scoped. Migration 0013
installs the canonical six-level semantic taxonomy, facets, classification
history, origin dimensions, legacy backfill, RLS, and database enforcement.
See [Taxonomy v2](taxonomy-v2.md) before changing or extending the catalog.

Run `supabase/bootstrap/001_runtime_role.sql` with a privileged database role to create or update the restricted `expense_app` runtime role. The application `DATABASE_URL` must use this non-owner, non-`BYPASSRLS` role. Admin and migration URLs must never be supplied to the running API.

`OWNER_USER_ID` must be the UUID of an existing row in `profiles`, and `profiles.id` references `auth.users(id)`. On a brand-new project, create that user and profile once before deploying:

1. Supabase dashboard → **Authentication → Users → Add user**. Any email/password works; this is never used for login, it just needs to exist. Copy the generated **User UID**.
2. In the SQL Editor, insert the matching profile row (use the SQL Editor for this, not any admin/session-pooler URL from your own machine):
   ```sql
   insert into profiles (id, display_name, default_currency)
   values ('paste-the-user-uid-here', 'Your Name', 'USD');
   ```
3. Use that same UUID as `OWNER_USER_ID`.

On an existing deployment, reuse the profile that already owns your transactions and receipt objects instead of creating a new one.

## Environment

Copy `.env.example` to `.env` and change every placeholder.

Required private-v1 values:

```dotenv
AUTH_MODE="single_user"
OWNER_USER_ID="your-existing-profile-uuid"
DATABASE_URL="postgresql://expense_app:.../postgres"
SUPABASE_URL="https://your-project-ref.supabase.co"
SUPABASE_SECRET_KEY="backend-only-secret"
STORAGE_BUCKET="receipt-originals"
MAX_RECEIPT_FILE_BYTES=10485760
RECEIPT_DOWNLOAD_CONNECT_TIMEOUT_SECONDS=5
RECEIPT_DOWNLOAD_READ_TIMEOUT_SECONDS=20
RECEIPT_DOWNLOAD_WRITE_TIMEOUT_SECONDS=5
RECEIPT_DOWNLOAD_POOL_TIMEOUT_SECONDS=5
RECEIPT_DOWNLOAD_MAX_REDIRECTS=3
```

Keep `SUPABASE_SECRET_KEY`, `PAT_PEPPER`, the database password, and any tunnel runtime key in server-only secret storage.

MCP DNS-rebinding protection defaults to loopback:

```dotenv
MCP_ALLOWED_HOSTS="127.0.0.1:*,localhost:*"
MCP_ALLOWED_ORIGINS=""
```

When a reverse proxy or private service changes the `Host` header, add only that exact host. Do not replace the allowlist with `*`.

The widget CSP automatically includes the origin from `SUPABASE_URL` for signed direct uploads. Add another origin only when the widget genuinely needs it:

```dotenv
MCP_WIDGET_CONNECT_DOMAINS=""
MCP_WIDGET_RESOURCE_DOMAINS=""
```

## Build and run

Local:

```powershell
pip install -e ".[dev]"
Set-Location widget
npm ci
npm run build
Set-Location ..
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

The bash-compatible equivalent is:

```bash
python -m pip install -e '.[dev]'
(cd widget && npm ci && npm run build)
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Docker:

```powershell
docker compose up --build
```

The Dockerfile uses a Node build stage to produce one inlined `widget/dist/index.html`, then copies only that artifact into the Python image.

## Verify

```powershell
curl.exe http://127.0.0.1:8000/health
```

Launch the current MCP Inspector and connect it to the Streamable HTTP endpoint:

```powershell
npx.cmd @modelcontextprotocol/inspector
```

```bash
npx @modelcontextprotocol/inspector
```

In Inspector, choose **Streamable HTTP**, enter
`http://127.0.0.1:8000/mcp`, initialize the session, inspect all 27 tools and
the single `ui://holy-spend/app-v40-<content-hash>.html` resource, and call only read-only tools unless the configured
database is safe for testing. Tool calls that touch data require a valid owner
profile and applied migrations.

Run the full local checks:

```powershell
ruff check .
mypy app tests
pytest
Set-Location widget
npm audit --omit=dev
npm test
npm run build
```

The bash-compatible check sequence is:

```bash
ruff check .
mypy app tests
pytest
(cd widget && npm audit --omit=dev && npm test && npm run build)
```

## Storage

Follow [Supabase Storage setup](supabase-storage.md). The chat-native MCP and
widget receipt flow is:

1. ChatGPT supplies and reads the attachment through the declared file parameter;
2. ChatGPT constructs the complete candidate;
3. `create_receipt_draft_from_file` verifies the bytes and atomically creates the
   populated draft and private original with hash idempotency and compensation;
4. the one app resource opens its review route and refreshes authoritative state;
5. validation and explicit confirmation remain separate.

## Nutrition

`nutrition_lookups` (migrations `0020`-`0025`) is a source-agnostic
queue/cache table for grocery product nutrition data. An earlier
in-process Railway cron job approach (calling Open Food Facts directly)
was scrapped after hitting real coverage and reliability limits in
practice, in favor of a scheduled Claude/ChatGPT chat task instead.

Six MCP tools support it, all using the existing Holy Spend connector, not
a separate Supabase connector or raw SQL: `get_nutrition_queue` and
`save_nutrition_result` drive the lookup loop; `search_nutrition_lookups`
finds an already-matched item by name/brand to correct it, since the queue
tool only ever returns pending/no_match rows; `get_nutrition_summary`
powers the Nutrition tab and inline card; `nutrition_lookup_usda` /
`nutrition_lookup_usda_detail` and `nutrition_lookup_off` proxy USDA
FoodData Central and Open Food Facts server-side, so the scheduled task
never needs its own API key: only this server does. Set
`USDA_FDC_API_KEY` (falls back to the rate-limited `DEMO_KEY` if unset; a
free personal key from
[fdc.nal.usda.gov/api-key-signup.html](https://fdc.nal.usda.gov/api-key-signup.html)
removes that ceiling).

`save_nutrition_result` enforces real data-quality gates, not just schema
shape: a "matched" write needs `product_name`/`source`, and either a
source-stated `nutriscore_grade` or all 6 of the core Nutri-Score macros
(energy, sugars, saturated fat, sodium, fiber, protein). A partial subset
is rejected outright, since a match that can never be scored is worse than
an honest no-match. Reported macros that are physically inconsistent
(sugars exceeding carbs, saturated fat exceeding total fat) are rejected
too.

Setting up the actual scheduled task (which platform, what cadence, the
exact prompt) is a platform-side configuration step, not app code. See
[Nutrition automation](nutrition-automation.md) for a full walkthrough,
including a ready-to-use prompt and the two gotchas that apply regardless
of platform: cron is evaluated in UTC, and the prompt needs to prefer the
lookup tools above over general web search.

## Backups and upgrades

Back up Postgres and the private Storage bucket together. Apply new migrations before deploying application code that depends on them. Preserve `.env`, tunnel credentials, generated plugin bundles, and local marketplace files outside source control.

### Optional read-only hosted tracker

The public authenticated API gateway can serve the same compiled tracker as
a standalone HTTPS page. The authenticated MCP action issues a one-use link
that expires after two minutes. The cookie expires after 30 minutes. Ask the
connected chat to open the hosted tracker again when either expires.

1. Apply migrations 0038, 0039 and 0040 in order, after 0037.
2. Run `supabase/bootstrap/002_hosted_tracker_reader.sql` as the database
   administrator. Supply its reader password through the prompt or your secret
   management tooling. The script creates the login once and reapplies the
   read grants. Manage password rotation separately.
3. Set `OWNER_USER_ID` and the same bare HTTPS `HOSTED_TRACKER_ORIGIN` on the
   authenticated gateway and private MCP server. Configure
   `HOSTED_TRACKER_READ_DATABASE_URL` only on the gateway using the restricted
   `expense_tracker_reader` login. Both services keep their existing runtime
   database connection for launch/session writes.
4. Keep the MCP service private behind the gateway and keep the exact HTTPS
   host and scheme when forwarding requests. Serve the widget build from the
   same image. Disable access to request bodies and cookie headers in your
   proxy, error reporting, and observability tools. The gateway emits the
   launch credential in the tool response for the connecting host to present.
   Verify that the host preserves the URL fragment and makes the link clickable.
5. In a connected owner chat, ask to open the hosted tracker and click **Open
   tracker** in the browser. Check expiration and sign-out before sharing the
   entry point with your own clients.

Coverage is per currency and reflects the owner's declaration for the entire
ledger. Confirmed receipts alone provide recorded amounts. In chat use
`declare_spending_coverage` to record tracking starts, completed import
intervals, and gaps, and `get_spending_transactions` to inspect the comparison's
members. Spending classification changes use `review_spending_classification`
with the transaction revision and latest review ID.

The protein metric uses confirmed grocery lines and documented purchased mass
or volume. A source reference and original `protein_label` are required.
Existing nutrition facts remain available for the basket grade and need a
source recheck before they can enter this metric. Receipt-level discounts and
refunds without the necessary allocation are excluded.
