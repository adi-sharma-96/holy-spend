# Plugin development

The plugin is an interactive, decoupled ChatGPT app: data tools return private
structured projections and one render tool opens one resource.

## Architecture

| Layer | Location | Responsibility |
|---|---|---|
| MCP transport | `app/mcp_server.py` | 31 tool registrations and one resource |
| Canonical taxonomy | `taxonomy/v2/taxonomy.yaml` | Versioned semantic tree, facets, and legacy mappings |
| Taxonomy compiler | `scripts/compile_taxonomy.py` | Validated SQL, JSON, and TypeScript artifacts |
| Receipt extraction contract | `app/receipt_extraction.py` | ChatGPT candidate and verified-file contract |
| Receipt normalization | `app/receipt_normalization.py` | Savings/discount arithmetic semantics |
| Atomic commit | `app/receipt_commit.py` | Hash lock, idempotency, persistence, compensation |
| Application service | `app/application.py` | Saves, validation, confirmation, corrections |
| Domain repositories | `app/repositories.py`, `app/receipt_files.py` | Owner-scoped SQL and receipt lifecycle |
| Widget | `widget/src/App.tsx` | Route-driven single mounted application |

The only resource URI is `ui://holy-spend/app-v40-<content-hash>.html`.
`open_expense_tracker(route, transactionId)` is the only render tool.

## Receipt contract

`create_receipt_draft_from_file` declares
`_meta["openai/fileParams"] == ["file"]`. ChatGPT reads the receipt and supplies
the structured draft. The server downloads the file once, verifies it, normalizes
reconciliation, and commits the populated draft and original together. There is
no UI metadata on this data tool, so receipt saving never mounts an iframe.
`open_expense_tracker` is the only UI-linked tool and opens receipt review only
when the user explicitly asks for it. There is no widget upload, temporary
staging, status polling tool, or duplicate editor renderer.

## Widget routes

- `/overview`
- `/transactions`
- `/prices`
- `/expenses/new`
- `/expenses/:id`
- `/expenses/:id/review`

Navigation uses the History API. `widgetState` stores preferences only
(`route`, `period`, and activity filter), never a competing expense snapshot.
The active expense is refreshed after mutations, on focus/visibility restoration,
when returning from detail, and through a bounded review interval.

## Local checks

```powershell
.venv\Scripts\python.exe -m ruff check app scripts tests
.venv\Scripts\python.exe -m mypy app
.venv\Scripts\python.exe -m pytest --basetemp .pytest-temp
.venv\Scripts\python.exe scripts\compile_taxonomy.py --check
cd widget
npx.cmd tsc --noEmit
npm.cmd test
npm.cmd run build
```
