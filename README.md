<p align="center">
  <img src="docs/screenshots/overview.png" width="340" alt="Holy Spend's Overview card, inline in a chat">
</p>

<h1 align="center">Holy Spend</h1>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-2ea043.svg" alt="MIT license"></a>
  <img src="https://img.shields.io/badge/hosting-self--hosted-2ea043.svg" alt="Self-hosted">
  <img src="https://img.shields.io/badge/works%20with-any%20MCP%20client-2ea043.svg" alt="Works with any MCP client">
  <a href="https://adi-sharma-96.github.io/holy-spend/"><img src="https://img.shields.io/badge/site-adi--sharma--96.github.io%2Fholy--spend-2ea043.svg" alt="Live site"></a>
</p>

<p align="center">
You already have Claude, ChatGPT, Cursor, or something else that speaks
MCP open all day. Now it also knows what you spent at the grocery store
this month, whether that "deal" on olive oil is actually cheaper than
what you paid last time, and whether your own basket is getting better
or worse for you.
</p>

> No new app. No dashboard to remember to check. You just ask.

<p align="center"><a href="https://adi-sharma-96.github.io/holy-spend/"><strong>→ See it as a page</strong></a></p>

---

## The actual point of it

Most expense trackers make you do the work: type in every purchase, pick
a category, remember to open the app. This one flips that. Forward a
bill and it's logged, full stop, that part works for anything. Itemize
a grocery receipt instead and it goes further: per-unit pricing, price
alerts, your own inflation number, a nutrition grade.

Full pitch, with screens: **[→ See it as a page](https://adi-sharma-96.github.io/holy-spend/)**.
Real examples of all of it in use: **[docs/use-cases.md](docs/use-cases.md)**.

All of it lives inside a chat you already have open. That's the whole
idea.

It's built for one person per deployment, on purpose. No sign-up page,
no multi-user login. Your data sits in a database only you control.
Nothing about your spending goes anywhere except the model you're
already talking to.

It also doesn't run its own OCR or call out to a separate AI API to
read a receipt. It uses the model you're already talking to, the one
in the subscription you already pay for. No metered API bill stacking
on top.

---

Everything below is just how to get it running.

## Is this for you?

No coding required, but you'll need:

- a free [Supabase](https://supabase.com) account, for the database
- somewhere to host the backend (a free option, covered in Step 2)
- a chat client with custom MCP connector support, Claude, ChatGPT,
  Cursor, or similar
- about 30-45 minutes

## Step 1: Set up the database

1. Create a project at [supabase.com](https://supabase.com). Pick a name
   and password, you'll need the password again shortly.
2. Open the SQL Editor and run:
   ```sql
   create role expense_app login password 'pick-a-password-here' nosuperuser nocreatedb nocreaterole noinherit nobypassrls;
   ```
   Then open
   [`supabase/bootstrap/001_runtime_role.sql`](supabase/bootstrap/001_runtime_role.sql),
   copy everything from the `alter role expense_app...` line to the end of
   the file, paste it into a new query, and run it.
3. Open [`supabase/migrations`](supabase/migrations). Run each `.sql` file
   in numeric order in the SQL Editor, one at a time.

   Have `psql` and a terminal? Steps 2 and 3 both collapse into this. Go
   to Project Settings → Database and copy the connection string shown
   there as-is (it already has a `postgres` user and the password you set
   in step 1, don't touch it):
   ```bash
   psql "<paste the connection string here>" -f supabase/bootstrap/001_runtime_role.sql
   for f in supabase/migrations/*.sql; do psql "<same connection string>" -f "$f"; done
   ```
   The bootstrap script asks you to type an `expense_app` password when it
   runs. That's a new password you're creating for the app, different from
   your project password above.
4. **Authentication → Users → Add user.** Any email/password works, it's
   never used to log in. Copy the User UID.
5. Back in the SQL Editor:
   ```sql
   insert into profiles (id, display_name, default_currency)
   values ('paste-the-user-uid-here', 'Your Name', 'USD');
   ```
   Save that UID, it's your `OWNER_USER_ID`.
6. **Storage → New bucket**, name it exactly `receipt-originals`, leave it
   private.
7. Grab three values for the next step, from Project Settings: your
   **Project URL**, your backend-only **secret key** (called `service_role`
   on older Supabase projects), and your **connection string** from the
   Database page (URI tab). Edit the connection string's username/password
   to `expense_app:<the password from step 2>`.

## Step 2: Deploy the backend

Two services from the same Docker image: one private (does the work), one
public (what your chat client connects to).

- **[Cloud Run](docs/gcp-cloud-run-deployment.md)**, genuinely free at
  this app's scale, no trial to run out later. A few more setup steps (a
  GCP project, a Docker image registry, IAM permissions).

Prefer another host? It's the same Docker image and the same env vars,
so anywhere that runs containers works, you're just on your own for the
setup steps. The guide uses the values from Step 1 (`OWNER_USER_ID`, the
connection string, `SUPABASE_URL`/`SUPABASE_SECRET_KEY`) and ends with a
working `api` URL, that's what Step 3 below needs. Come back here once
you have it.

## Step 3: Connect it

This works with any client that supports custom MCP connectors. Claude's
the fastest to walk through, so that's below.

1. Claude: **Settings → Connectors → Add custom connector.**
2. URL: your `api` domain plus `/mcp`.
3. Authentication: OAuth. Advanced settings: paste in the
   `OAUTH_CLIENT_ID`/`OAUTH_CLIENT_SECRET` you set in Step 2.
4. Connect. Claude handles the approval redirect on its own.

Using ChatGPT? See [docs/chatgpt-connection.md](docs/chatgpt-connection.md).
Cursor or anything else that speaks MCP: same shape, add a custom
connector pointing at your `api` domain plus `/mcp`, OAuth, same client
ID/secret from Step 2.

## Step 4: Try it

- "Open my expense tracker"
- "I spent $12.50 at Starbucks today, add it"
- Attach a receipt photo and say "add this"
- "What did I spend on groceries this month?"

---

## Extending it

The whole thing is a normal FastAPI + React repo. If you use Claude Code
or Codex, point it at this repo and it can walk you through setup, debug a
deployment, or build on top of it (new categories, a different chat host,
whatever you want).

## Want more?

**Deployment**
- Cloud Run in detail, including the actual free-tier cost breakdown: [docs/gcp-cloud-run-deployment.md](docs/gcp-cloud-run-deployment.md)
- Connecting ChatGPT specifically (Developer Mode, the Secure MCP Tunnel): [docs/chatgpt-connection.md](docs/chatgpt-connection.md)
- Every environment variable, running from source, Docker: [docs/self-hosting.md](docs/self-hosting.md)

**Automate it further**, both optional, both work by giving a scheduled
chat task (Claude or ChatGPT, running on a timer) a prompt to follow, no
app code changes either way.
- Nutrition scoring stays current on its own, pulls from USDA/Open Food Facts automatically: [docs/nutrition-automation.md](docs/nutrition-automation.md)
- Forward receipt emails (Amazon, Uber Eats, Instacart, and more) and have them added on their own: [docs/email-receipt-ingestion.md](docs/email-receipt-ingestion.md)

**Building on it**, for contributing, or if you're pointing Claude Code
or Codex at this repo per "Extending it" above.
- Architecture and how the pieces fit together: [docs/architecture.md](docs/architecture.md)
- Security model: [docs/security.md](docs/security.md)
- Taxonomy v2, the classification system behind Price Watch, Nutrition, and every category: [docs/taxonomy-v2.md](docs/taxonomy-v2.md)
- Receipt storage and lifecycle: [docs/supabase-storage.md](docs/supabase-storage.md), [docs/analyze-before-commit-receipts.md](docs/analyze-before-commit-receipts.md)

## License

[MIT](LICENSE)
