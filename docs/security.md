# Security model

## Trust boundaries

ChatGPT, Codex, the model, the widget, and REST clients are untrusted callers. FastAPI and its database transaction are the authorization boundary. Supabase Postgres and private Storage are the data boundary.

Private v1 assumes one server owner:

- `AUTH_MODE=single_user`
- `OWNER_USER_ID=<existing profile UUID>`

MCP inputs contain no user ID. The resolver supplies the owner on the server, `user_transaction` sets `app.current_user_id`, and forced RLS limits SQL to that owner.

## Secrets

Server-only:

- database credentials;
- `SUPABASE_SECRET_KEY`;
- `PAT_PEPPER`;
- PAT admin database URL;
- OpenAI tunnel runtime key.

Never place these in MCP results, widget code, plugin manifests, `.app.json`, screenshots, or logs. `.env`, generated instance manifests, build output, and local MCP configuration are ignored.

## Receipt binaries and signed URLs

ChatGPT supplies receipt bytes through the official host file contract and calls
`create_receipt_draft_from_file` with its extracted candidate. The widget has no
file picker or upload API. The server verifies the bounded download and its
SHA-256 but performs no OCR or interpretation; temporary URLs never appear in
model-visible results.

The tool accepts only a meaningful populated draft and writes the database and
private object as one compensated product operation. Completed commits are
idempotent by owner and
client request ID. Failed database commits delete the uploaded object; a failed
compensation is recorded in `receipt_storage_cleanup_jobs`.

Download URLs follow the same rule. They are short-lived and hidden. Treat browser developer tools and the widget iframe as capable of seeing signed targets; expiration, single-object scope, private bucket policy, file validation, and RLS remain necessary.

Accepted types are JPEG, PNG, WebP, and PDF. The server validates filename shape, MIME/extension agreement, declared/stored size, object-key ownership, and optional SHA-256. The default limit is 10 MB.

## Mutation safety

- Draft saves and receipt commits are atomic, idempotent, and revision-checked.
- Validation persists reconciliation issues.
- Chat-native receipt downloads require HTTPS, reject credentials and
  non-standard ports, pin DNS to public addresses, revalidate redirects, apply
  bounded timeouts and sizes, and reconcile filename/MIME/magic bytes before
  private storage.
- Temporary ChatGPT download URLs stay in request memory only. Errors and
  model-visible results never include their query strings, receipt bytes,
  storage object keys, or signed Supabase URLs.
- Confirmation requires `explicit_approval=true` and no blocking issue.
- Permanent deletes require `explicit_confirmation=true`.
- Confirmed records require an explicit, revision-checked correction reason;
  the replacement is revalidated atomically and audit logged.
- Audit events record lifecycle changes.

Tool annotations help hosts make safer decisions but are not authorization. Backend checks remain mandatory.

## Network

Prefer Secure MCP Tunnel so the service remains private and no inbound firewall port is opened. Keep DNS-rebinding protection enabled and allowlist exact hosts/origins.

Widget CSP is deny-by-default. Direct upload adds only the Supabase project origin to `connectDomains`; the single-file bundle requires no external script or stylesheet domain.

If the service is ever exposed publicly:

1. terminate TLS at a maintained reverse proxy;
2. add rate limits and request-size limits;
3. replace single-owner MCP authorization with OAuth 2.1;
4. validate issuer, audience, expiry, scopes, and resource indicators;
5. keep PostgreSQL RLS and server ownership checks as defense in depth.

The official public MCP guidance requires authorization-code OAuth with PKCE and protected-resource metadata. A tunnel authenticates transport but does not turn a single-owner application into a safe multi-user service.

## REST compatibility

Legacy REST uses scoped PATs. PATs remain backend credentials and must not be passed to the widget or model. Revoke unused tokens, use narrowly scoped tokens, and rotate `PAT_PEPPER` only with a deliberate token reissuance plan.

## Analytics

Analytics reads confirmed transactions only. When no currency filter/group is requested, the compiler adds a currency dimension automatically so CAD, USD, or any future supported currency is never summed into a misleading value.

## Operational checklist

- Apply every migration and bootstrap the restricted runtime role.
- Verify `expense_app` is not owner, superuser, or `BYPASSRLS`.
- Confirm the Storage bucket is private.
- Keep signed URL TTL short.
- Back up database and Storage together.
- Run Python tests, widget tests/build, production dependency audit, plugin validation, and skill validation before release.
- Review logs for sensitive values before enabling external aggregation.
- Do not publish `.app.json`, `.mcp.json`, `.env`, or tunnel profiles.
