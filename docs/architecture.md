# Architecture and contributing

This is the technical reference: how the pieces fit together, how to run
the project from source, and what a pull request is expected to pass. If
you just want to run your own copy, the [README](../README.md)'s walkthrough
is the faster path and doesn't require any of this.

## System overview

- FastAPI backend exposing both a REST/OpenAPI surface (`/v1/*`, PAT-authenticated) and an official MCP Python SDK Streamable HTTP server (`/mcp`);
- chat-native file-parameter receipt analysis with HTTPS/SSRF/redirect/timeout/size/MIME/magic-byte controls on the server side, and idempotent, atomic draft commits;
- a canonical, versioned Taxonomy v2 (six reporting levels, 300+ assignable leaves, facets, legacy mappings) compiled to deterministic SQL, JSON, and TypeScript artifacts;
- a React/TypeScript MCP Apps widget (single inlined bundle, no separate frontend deploy);
- private Supabase Postgres with row-level security and private Storage for original receipt files;
- an optional OAuth 2.1 gateway (`app/mcp_gateway.py` + `app/oauth_provider.py`) for chat hosts that need a public HTTPS endpoint instead of an outbound tunnel;
- a repository-owned Codex/ChatGPT plugin package under `plugins/holy-spend`, with an instance-local connection configurator that never publishes account-specific IDs into source control.

See [Self-hosting](self-hosting.md) for the full environment variable
reference and running from source, and [Deploy to Railway](railway-deployment.md)
for every deployment topology in detail.

## Running from source (for development, not deployment)

```powershell
Copy-Item .env.example .env
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"

Set-Location widget
npm install
npm run build
Set-Location ..

uvicorn app.main:app --reload
```

The bash-compatible equivalent:

```bash
cp .env.example .env
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'

(cd widget && npm install && npm run build)

uvicorn app.main:app --reload
```

The REST API is at `/v1/*`, OpenAPI at `/openapi.json`, and health at
`/health`. MCP mounts at `/mcp` only when `MCP_ENABLED=true`, see
[Self-hosting](self-hosting.md) for every required environment variable and
what each one does.

Preview the widget standalone, without a live MCP host:

```bash
cd widget && npm run dev -- --host 127.0.0.1
```

Then open `http://127.0.0.1:5173/?demo=1`. Demo mode is a development-only
UI fixture with fake data; production builds always use the real MCP Apps
bridge and server-authoritative data.

## Development checks

```bash
ruff check .
mypy app tests
pytest
python scripts/compile_taxonomy.py --check

cd widget
npm audit --omit=dev
npm test
npm run build
```

## Contributing

Issues and pull requests are welcome. Since this is architected as a
single-owner personal tool rather than a multi-tenant service, the most
useful contributions tend to be: bug fixes, taxonomy coverage gaps,
additional MCP/chat-host compatibility, and documentation improvements.
Run the full check list above before opening a PR.

## Design boundaries

This is a personal, single-owner tool by design. One deployment holds one
person's data, and `AUTH_MODE=single_user` resolves every MCP call to a
single configured owner. It is not built for public multi-tenant hosting or
a marketplace listing as-is; see the [roadmap](marketplace-roadmap.md) for
what that would take.
