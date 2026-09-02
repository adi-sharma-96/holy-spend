# Deploy to Google Cloud Run

Same two-service shape as [Railway](railway-deployment.md) — a public `api`
gateway and a private `mcp` server, both built from the same Docker image —
but Cloud Run has no equivalent to Railway's private networking for two
plain services to trust each other automatically. Instead, `api` calls `mcp`
with a Google-signed identity token, and `mcp` is deployed to require one.
That's the one real mechanism difference; everything else (env vars,
migrations, OAuth) carries over unchanged.

Genuinely free at this app's scale — see the cost section at the bottom
before you're tempted to skip it and just trust it'll be fine.

This is an alternative to Railway, not a replacement for the Railway docs —
`railway-deployment.md` still describes a fully working setup, it just
costs money past its free trial. Pick whichever suits you; nothing here
requires abandoning Railway's config files if you ever want to go back.
This runbook has been run start-to-finish for real, and every gap that
surfaced doing it live is already folded in below.

**Managing services after deploy**: the
[Cloud Console](https://console.cloud.google.com/run) has a full web UI —
service list, env vars, revisions, logs, metrics — you're not limited to
the CLI day-to-day, that's just what this runbook uses since it's
scriptable and exact.

## 0. Prerequisites

1. Install the [`gcloud` CLI](https://cloud.google.com/sdk/docs/install), then:
   ```bash
   gcloud auth login
   ```
2. Create a project (skip if you already have one you want to use):
   ```bash
   gcloud projects create holy-spend-prod --name="Holy Spend"
   gcloud config set project holy-spend-prod
   ```
   `<PROJECT_ID>` in every command below is whatever you used here
   (`holy-spend-prod` if you followed this exactly — project IDs must be
   globally unique, so gcloud will tell you to pick another if it's taken).
3. Link a billing account — required to deploy at all, even within the
   free tier (you won't be charged unless you exceed it, see the cost
   section below). If you don't have one yet: [console.cloud.google.com/billing](https://console.cloud.google.com/billing) →
   create one (needs a card for verification). Then link it to the project:
   ```bash
   gcloud billing accounts list
   gcloud billing projects link holy-spend-prod --billing-account=<BILLING_ACCOUNT_ID>
   ```
4. Enable the required APIs once:
   ```bash
   gcloud services enable run.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com
   ```
5. Set the $1 budget alert now, before deploying anything (Billing →
   Budgets & alerts in the console, or `gcloud billing budgets create`) —
   see the cost section at the bottom for why this is worth doing first,
   not as an afterthought.

- Migrations already applied and `supabase/bootstrap/001_runtime_role.sql`
  already run — this is unaffected by which host runs the container, see
  [Self-hosting](self-hosting.md) for that part if you haven't done it yet.

Pick a region close to you; every command below uses `us-central1` —
swap it consistently if you use another.

## 1. Build and push the image

One image, same as Railway — built from the repo root's `Dockerfile`
directly via Cloud Build, no local Docker required:

```bash
gcloud artifacts repositories create holy-spend \
  --repository-format=docker --location=us-central1

gcloud builds submit --tag us-central1-docker.pkg.dev/<PROJECT_ID>/holy-spend/app:latest .
```

Re-run the `gcloud builds submit` line on every deploy — there's no
git-push-to-deploy here unless you additionally wire up a
[Cloud Build trigger](https://cloud.google.com/build/docs/automating-builds/create-manage-triggers)
on your GitHub repo, which is worth doing once this is working manually.

## 2. Deploy `mcp` (private)

Same role as Railway's `mcp` service: `MCP_ENABLED=true`,
`AUTH_MODE=single_user`, trusts every caller unconditionally — which is why
`--no-allow-unauthenticated` here is not optional. Put the full env list in
a file rather than a giant `--set-env-vars` line:

```yaml
# mcp.env.yaml
ENVIRONMENT: "production"
MCP_ENABLED: "true"
AUTH_MODE: "single_user"
OWNER_USER_ID: "<your profile UUID>"
DATABASE_URL: "<restricted expense_app runtime URL>"
PAT_PEPPER: "<a long random secret — see the note under api's env file, this one's copy doesn't have to match>"
SUPABASE_URL: "<your Supabase project URL>"
SUPABASE_SECRET_KEY: "<your backend-only key>"
STORAGE_BUCKET: "<your private receipt bucket>"
```

```bash
gcloud run deploy holy-spend-mcp \
  --image=us-central1-docker.pkg.dev/<PROJECT_ID>/holy-spend/app:latest \
  --region=us-central1 \
  --no-allow-unauthenticated \
  --env-vars-file=mcp.env.yaml
```

This prints a service URL (`https://holy-spend-mcp-xxxxx.us-central1.run.app`)
— save it, `api` needs it next. `MCP_ALLOWED_HOSTS` isn't set above on
purpose: Cloud Run only assigns the URL after this first deploy, so there's
a real chicken-and-egg problem (the MCP SDK's own DNS-rebinding check needs
the *exact* hostname — `mcp.py`'s `allowed_hosts` matching is exact-match
or `host:*` with a literal port suffix, no wildcard subdomains, and Cloud
Run's HTTPS traffic on 443 sends a bare hostname with no port at all). Fix
it in one more command once you have the URL:

```bash
gcloud run services update holy-spend-mcp --region=us-central1 \
  --update-env-vars=MCP_ALLOWED_HOSTS=holy-spend-mcp-xxxxx.us-central1.run.app
```

(bare hostname from the URL above, no `https://`, no `:*` suffix, no path.)

Confirm `/health` passes: `curl <that-url>/health` — this will `403`
without a valid identity token if you did `--no-allow-unauthenticated`
correctly (that's the point; it should only ever be called by `api`'s
service account, next).

## 3. Let `api` call `mcp`: a dedicated service account

Railway's private networking made this hop implicitly trusted. Cloud Run's
equivalent is IAM: a service account that only `api` runs as, granted
permission to invoke only this specific `mcp` service.

```bash
gcloud iam service-accounts create holy-spend-api \
  --display-name="Holy Spend api gateway"

gcloud run services add-iam-policy-binding holy-spend-mcp \
  --region=us-central1 \
  --member="serviceAccount:holy-spend-api@<PROJECT_ID>.iam.gserviceaccount.com" \
  --role="roles/run.invoker"
```

## 4. Deploy `api` (public gateway)

Same role as Railway's `api`: a public, PAT/OAuth-authenticated reverse
proxy at `/mcp`, never running its own MCP server
(`MCP_ENABLED=false`/omitted). `MCP_GATEWAY_USE_GOOGLE_ID_TOKEN=true` is
the new setting this deployment needs that Railway's didn't — it's what
makes the gateway attach the identity token `mcp` now requires.

```bash
gcloud run services describe holy-spend-mcp --region=us-central1 --format='value(status.url)'
# → https://holy-spend-mcp-xxxxx-uc.a.run.app
```

```yaml
# api.env.yaml
ENVIRONMENT: "production"
AUTH_MODE: "pat"
OWNER_USER_ID: "<same profile UUID as mcp — the OAuth provider requires this even though PAT mode alone wouldn't>"
PAT_PEPPER: "<must be the exact value used when your existing PATs/OAuth tokens were created, not a fresh one — a mismatch silently invalidates every issued token, since this is what verifies them against what's hashed in the database>"
MCP_GATEWAY_UPSTREAM_URL: "https://holy-spend-mcp-xxxxx-uc.a.run.app/mcp"
MCP_GATEWAY_USE_GOOGLE_ID_TOKEN: "true"
DATABASE_URL: "<restricted expense_app runtime URL>"
SUPABASE_URL: "<your Supabase project URL>"
SUPABASE_SECRET_KEY: "<your backend-only key>"
STORAGE_BUCKET: "<your private receipt bucket>"
```

```bash
gcloud run deploy holy-spend-api \
  --image=us-central1-docker.pkg.dev/<PROJECT_ID>/holy-spend/app:latest \
  --region=us-central1 \
  --allow-unauthenticated \
  --service-account="holy-spend-api@<PROJECT_ID>.iam.gserviceaccount.com" \
  --env-vars-file=api.env.yaml
```

`--allow-unauthenticated` here is correct, not a mistake — the app itself
gates `/mcp` with PAT/OAuth (`AUTH_MODE=pat`), same as it did fronting
Railway's `mcp`. Cloud Run-level auth and app-level auth are two different
layers; `mcp` needed the Cloud Run layer because it has no app-level auth
of its own, `api` doesn't because it does.

Confirm: `curl https://<api-url>/health` should return `200` with no
credentials at all; a bare `curl https://<api-url>/mcp` should `401`
(PAT/OAuth required); a call from anywhere other than the
`holy-spend-api` service account straight to `mcp`'s URL should `403`
regardless of any PAT you pass it, since that's enforced by IAM before
the request ever reaches the app.

## 5. OAuth for Claude / ChatGPT

Identical to [Railway's OAuth section](railway-deployment.md#oauth-works-on-any-claude-plan)
— generate the client_id/secret (or reuse the ones from an existing Railway
setup, which keeps a connected Claude host from needing any reconfiguration
beyond the URL), apply the OAuth refresh-token migration, add these to
`api.env.yaml` and redeploy:

```yaml
OAUTH_CLIENT_ID: "<your client id>"
OAUTH_CLIENT_SECRET: "<your client secret>"
OAUTH_ISSUER_URL: "https://holy-spend-api-xxxxx.us-central1.run.app"
```

`OAUTH_ISSUER_URL` is now the Cloud Run `api` URL (or a custom domain
mapped to it) instead of a Railway one — nothing else about the OAuth flow
changes.

**Connecting ChatGPT specifically** will likely fail on the first attempt
with `Redirect URI '...' not registered for client` — ChatGPT mints a
fresh callback URL per connector instance
(`https://chatgpt.com/connector/oauth/<random-id>`), and this new
deployment has no memory of whatever was registered on Railway. Copy the
exact URL from that error, add it, and redeploy:

```yaml
OAUTH_ADDITIONAL_REDIRECT_URIS: "https://chatgpt.com/connector/oauth/<the-id-from-the-error>"
```

Retry connecting in ChatGPT — same OAuth flow, should complete this time.

For a custom domain instead of the `*.run.app` URL:
`gcloud run domain-mappings create --service=holy-spend-api --domain=<your-domain> --region=us-central1`,
then add the DNS records it gives you.

## 6. Redeploying after a code change

Manually: rebuild the image, then re-run both `gcloud run deploy`
commands (they're idempotent — a redeploy with the same image tag just
creates a new revision). `mcp` first, `api` second, same order as the
original deploy, though in practice either order is fine since nothing
about `api` startup depends on `mcp` being reachable at boot.

**Or auto-deploy on every push to `main`**, using `cloudbuild.yaml` in the
repo root (builds once, deploys both services from that same image — not
two separate builds). It deliberately never sets `--env-vars-file` or
`--set-env-vars`, so it can never touch secrets; per Cloud Run's own docs,
"subsequent revisions automatically get [existing] configuration ...
unless you make explicit updates to change it," so env vars stay exactly
as you configured them manually.

Setup, one time:

1. **Grant Cloud Build's service account permission to deploy.** Find
   which SA your trigger will run as (Cloud Build → Settings, or check the
   trigger after creating it in step 3 — it's usually
   `<PROJECT_NUMBER>-compute@developer.gserviceaccount.com` or
   `<PROJECT_NUMBER>@cloudbuild.gserviceaccount.com`), then:
   ```bash
   gcloud projects add-iam-policy-binding <PROJECT_ID> \
     --member="serviceAccount:<CLOUD_BUILD_SA>" --role="roles/run.developer"
   gcloud iam service-accounts add-iam-policy-binding \
     holy-spend-api@<PROJECT_ID>.iam.gserviceaccount.com \
     --member="serviceAccount:<CLOUD_BUILD_SA>" --role="roles/iam.serviceAccountUser"
   ```
2. **Connect the GitHub repo** — Cloud Build console → Triggers → Connect
   Repository. This step is an interactive GitHub App authorization, no
   CLI equivalent for the first-time connection.
3. **Create a trigger**: source = the repo you just connected, event = push
   to `main`, configuration = "Cloud Build configuration file",
   location = `/cloudbuild.yaml`.

From then on, `git push` to `main` builds and redeploys both services
automatically — check progress under Cloud Build → History.

The trigger's default service account (usually the project's compute
default SA) can build, push, and deploy with just `roles/run.developer` +
`roles/iam.serviceAccountUser` above — it deliberately can't rewrite a
service's public/private (`--allow-unauthenticated`) setting, since that
needs the broader `roles/run.admin`. `cloudbuild.yaml` doesn't ask it to;
that setting is fixed once at the original manual deploy and carries
forward automatically on every later redeploy, same as env vars.

## Cost: why this is genuinely free at this app's scale

Two separate things are easy to conflate here:

- **The $300/90-day free trial credit** every new billing account gets —
  a promotional grant, covers *any* GCP usage during that window,
  eventually expires. This is the Railway-trial-shaped thing, and it's not
  what "always free" refers to.
- **Cloud Run's Always Free tier** — a permanent, recurring monthly
  allowance (2,000,000 requests, 180,000 vCPU-seconds, 360,000 GiB-seconds,
  verified against [cloud.google.com/run/pricing](https://cloud.google.com/run/pricing),
  request-based billing, `us-central1`), independent of the trial credit
  and still fully in effect after it's gone. This is what "always free"
  actually means here — published pricing that resets every month forever,
  not a time-boxed grant.

So during the 90 days, the trial credit covers everything regardless of
whether you're within the Always Free limits. After it's gone (or expires),
the Always Free allowance is what continues to apply, on its own, forever.

Is this app's usage actually under those permanent limits? A single-user
app with a couple of scheduled tasks a day is on the order of a few hundred
requests/day — roughly 15,000/month against a 2,000,000/month allowance,
under 1% of quota. Compute is similarly nowhere close: each request is a
sub-second FastAPI+DB call, so even a generous estimate lands around
5,000–10,000 vCPU-seconds/month against 180,000 free. That's roughly
20–100x headroom on current usage, not a "just barely fits" margin — it
would take a genuinely different usage pattern (many more users, a
runaway retry loop) to approach the limit. Same-region service-to-service
traffic (`api` → `mcp`) is free regardless of any of the above. One caveat
worth knowing: the free allowance is pooled *per billing account*, not per
project — a second, unrelated Cloud Run project on the same billing
account would share this same quota.

Set a hard guardrail anyway, since "should never happen" isn't the same as
"structurally can't happen": **Billing → Budgets & alerts** in the Cloud
Console, a $1 threshold — this is the thing that actually catches an
unexpected usage pattern before it costs anything, not the math above. For
something stronger than an email, a budget-triggered Cloud Function that
disables billing on the project is the documented pattern — worth doing
once, not required to get started.

Neither service is configured with a minimum instance count (`--min-instances`
is unset, so it defaults to 0) — keeping one instance always warm is a
paid feature that would break "always free"; a cold start of a few seconds
on the first request after idle is the trade-off for staying at $0.

## Troubleshooting

**`mcp` returns 403 to everything, including `api`.** IAM policy changes
can take a minute or two to propagate — wait and retry before assuming the
binding is wrong. If it's still failing, confirm `api`'s deploy actually
used `--service-account=holy-spend-api@...` (a service redeployed without
that flag silently falls back to the project's default compute service
account, which was never granted `roles/run.invoker` on `mcp`).

**`api` returns 401/403 from `/mcp` even with a valid PAT.** Check
`MCP_GATEWAY_USE_GOOGLE_ID_TOKEN=true` is actually set on `api` — without
it, the gateway proxies to `mcp` with no identity token at all, and `mcp`
(deployed `--no-allow-unauthenticated`) rejects it before your PAT ever
matters.

**An automated build finishes "Successful" but logs `Completed with
warnings: Setting IAM policy failed`.** Expected and harmless if
`cloudbuild.yaml` matches this repo's version — it deploys the image
without touching public/private access, so there's nothing for this
warning to actually change. Confirm with
`gcloud run services get-iam-policy holy-spend-mcp --region=us-central1`;
it should list only `holy-spend-api@...` with `roles/run.invoker`, never
`allUsers`. If `allUsers` does show up, that's real and worth fixing
immediately — but it means something added it outside this pipeline, not
a consequence of this warning itself.

**First request after a while is slow.** Expected — that's the cold start
from `--min-instances=0`. If this becomes annoying for interactive use,
`gcloud run services update holy-spend-api --min-instances=1` removes it
for `api` at a small, no-longer-free cost; leaving `mcp` at 0 is usually
fine since it's only ever called via the already-warm `api`.

**Scheduled tasks (email ingestion, nutrition) time out on a cold start.**
Same root cause. If it becomes a real problem rather than a one-off, a
[Cloud Scheduler](https://cloud.google.com/scheduler) job pinging `/health`
every 10 minutes keeps `api` warm for free (falls under the request quota
easily) without paying for `--min-instances`.
