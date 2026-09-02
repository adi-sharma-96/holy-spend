# Connect ChatGPT

ChatGPT reaches your server through OpenAI's Secure MCP Tunnel: an
outbound-only connection, so your server never needs a public domain for
this. If you deployed the `tunnel` service from the [Railway
guide](railway-deployment.md), it's already running this for you and you
can skip to [Create the connection](#create-the-connection).

Official references: [Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels), [Connect and test a plugin](https://developers.openai.com/plugins/deploy/connect-chatgpt).

## Get a tunnel ID and API key

Do this once, from OpenAI's Platform tunnel settings: create a tunnel and
copy its `tunnel_id`, then generate a runtime API key with tunnel-use
permission. These are the two values `railway.tunnel.json`'s
`CONTROL_PLANE_TUNNEL_ID` and `CONTROL_PLANE_API_KEY` need if you're
deploying the Railway `tunnel` service. Never put the API key in
`.env.example`, a screenshot, or source control.

## Running the tunnel yourself instead (local development)

Skip this if the Railway `tunnel` service is already running. Only needed
if you're running the backend from source on your own machine:

```powershell
$env:CONTROL_PLANE_API_KEY = "your-runtime-key"

tunnel-client init `
  --sample sample_mcp_remote_no_auth `
  --profile expense-http `
  --tunnel-id tunnel_your_id `
  --mcp-server-url http://127.0.0.1:8000/mcp

tunnel-client run --profile expense-http
```

bash equivalent:

```bash
export CONTROL_PLANE_API_KEY="your-runtime-key"

tunnel-client init \
  --sample sample_mcp_remote_no_auth \
  --profile expense-http \
  --tunnel-id tunnel_your_id \
  --mcp-server-url http://127.0.0.1:8000/mcp

tunnel-client run --profile expense-http
```

Keep it running while you use ChatGPT. Don't pass the API key as a
command-line argument, it can end up in shell history or process listings.

## Create the connection

1. Enable developer mode in ChatGPT: Settings → Security and login (if your
   plan/workspace allows it).
2. Settings → Plugins → the plus button → create a developer-mode plugin.
3. Connection type: **Tunnel**, then select your tunnel.
4. Confirm the tools list loads and the server title shows "Holy Spend."

## Try it

- "Open my expense tracker"
- "I spent $12.50 at Starbucks today, add it"
- Attach a receipt photo and say "add this"

## Optional: name and icon in ChatGPT's plugin list

The connection above works fine as-is. To give it a proper name/icon
instead of the default, copy the connection's technical ID
(`asdk_app_*` or `plugin_asdk_app_*`, shown on its details page) and run:

```powershell
python plugins\holy-spend\scripts\configure_instance.py `
  --app-id plugin_asdk_app_your_connection_id
```

This builds a bundle at `build/plugin/holy-spend` (git-ignored, contains
your connection ID). Add it to your marketplace with `$plugin-creator`,
then install it in a new ChatGPT/Codex task.

## Troubleshooting

**MCP returns HTTP 421 or won't initialize.** The incoming `Host` header
isn't in `MCP_ALLOWED_HOSTS`. Add the exact host/port, restart, rerun
`tunnel-client doctor --profile expense-http --explain` if running locally.

**A receipt attachment gets rejected.** Attach the original image or PDF
directly in the ChatGPT composer.

**Tools report a missing owner or authorization failure.** Check
`AUTH_MODE=single_user` and `OWNER_USER_ID` point at a real `profiles.id`,
and that the database role is the restricted one from
[self-hosting](self-hosting.md), not an admin role.

**ChatGPT shows stale tools or an old widget.** Rebuild and restart the
backend, refresh the plugin connection in ChatGPT, start a new
conversation. Existing conversations can hold onto old tool metadata.

## For maintainers: manual end-to-end test

Run this against a non-production instance only.

1. Start the backend and initialize `http://127.0.0.1:8000/mcp`.
2. Inspect all tools and the widget resource with MCP Inspector.
3. Build the widget and open the widget resource URI it serves.
4. Connect through the tunnel, register/refresh the ChatGPT plugin.
5. Add and save a manual expense draft.
6. Attach a receipt and confirm `create_receipt_draft_from_file` runs
   exactly once without rendering UI, and the file descriptor only
   requires `download_url` and `file_id`.
7. Confirm extraction only populates values actually visible on the
   receipt, including fee/discount labels and informational savings.
8. Ask for interactive review, confirm `open_expense_tracker` opens the
   saved expense's review route.
9. Edit fields, run validation, confirm the original file exists in the
   private Supabase bucket.
10. Approve and confirm the expense.
11. Retrieve it and download the original via a fresh short-lived URL.
12. Run an analytics query, confirm confirmed-only and currency-safe
    results.

This repo's automated tests cover the local/mock contracts. The live
tunnel, ChatGPT host, and Supabase steps need real credentials and aren't
run by the test suite.
