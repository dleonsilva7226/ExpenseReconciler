---
role: devops
status: in-review
depends_on: [docs/agent-artifacts/researcher/2026-09-20-hosting-options.md, docs/agent-artifacts/architect/2026-09-20-config-secrets-contract.md]
supersedes: []
---

# Infra note: Render + Neon deploy config (O1a) and `.env.example` (O3)

## What was created

- **`.env.example`** (repo root) — one line per `app/config.py`
  `Settings` field, with a comment explaining what it's for and, where
  relevant, where to get a real value. Placeholder text only
  (`your-plaid-client-id-here`, `<set-your-own-random-secret-here>`,
  etc.) — no real values, and nothing shaped to look like a real key
  (learned from this repo's prior GitGuardian false-positive history:
  obviously-fake placeholders, not plausible-looking fake secrets).
- **`Dockerfile`** (repo root) — builds the Render web service image.
- **`render.yaml`** (repo root) — Render Blueprint declaring the web
  service, its build (via the Dockerfile), health check, and every env
  var it needs by name (`sync: false` — no values).
- **`docs/agent-artifacts/devops/2026-09-27-neon-asyncpg-sslmode-handoff-request.md`**
  — a real deploy-blocking issue found in `app/config.py` while
  verifying A5/D1's Neon URL-normalization claim (see below and that
  file). Not fixed here — out of DevOps's file-domain (`app/**`).

## Dockerfile vs. Render's native Python buildpack — decision and reasoning

Went with a **Dockerfile** (`runtime: docker` in `render.yaml`) rather
than Render's native Python buildpack. Reasoning:

- **Version pinning matches CI exactly.** `.github/workflows/ci.yml`
  pins `python-version: "3.12"` and `PLAN.md` specifies "Python 3.12+".
  `FROM python:3.12-slim` guarantees the same interpreter version in
  prod as CI verifies against. Render's native buildpack infers the
  version from a `runtime.txt`/`PYTHON_VERSION` env var or its own
  default, which is one more thing that can silently drift from CI
  over time without a build failure calling it out.
- **No dependency install surprises.** The Dockerfile's `pip install
  -r requirements.txt` step is byte-for-byte the same install CI and
  local dev already run — no buildpack-specific interpretation of
  `requirements.txt` to second-guess.
- **Portability.** The same image can be built and run locally
  (`docker build . && docker run -e ... -p 8000:8000 ...`) for a
  closer-to-prod smoke test than the buildpack path offers, and isn't
  tied to Render specifically if hosting ever changes again (R5's
  findings note hosting was already revisited once).
- **Cost of this choice:** one more file to maintain (`Dockerfile`)
  and Render's Docker builds can be marginally slower than its native
  buildpack's cached layers. Judged worth it for the reproducibility
  gain given this project's history of environment-drift issues (see
  the CI import-check saga in
  `docs/agent-artifacts/devops/2026-09-21-ci-import-check-fix.md` and
  `2026-09-26-restore-live-import-check.md` — module-graph/env
  mismatches between CI and reality have already bitten this repo
  once).

`docker-compose.yml` does not exist in this repo yet (checked — no
`Dockerfile*`/`docker-compose*` anywhere in the tree before this
change). Ticket O1 (a local-dev Compose file) is evidently still
unbuilt; this note only covers O1a (the separate Render production
path per the hosting decision record, which explicitly says
`docker-compose.yml` is now local-dev-only and production goes via a
"separate Render service config"). The `Dockerfile` created here is
usable by a future O1 Compose file too (`build: .`) if/when that
ticket is picked up — no need to duplicate build logic.

## `render.yaml` contents

- `runtime: docker`, `dockerfilePath: ./Dockerfile`, `dockerContext: .`
- `plan: free` — Render's free web service tier, per R5/the hosting
  decision record (spins down after 15 min idle, ~1 min cold start on
  next request; accepted tradeoff already recorded in the decision
  record).
- `healthCheckPath: /health` — matches the existing `GET /health`
  endpoint in `app/main.py` (returns `{"status": "ok"}`), so Render's
  own health monitoring has something real to check.
- `region: oregon` — Render's default US region; no requirement drove
  a specific choice, flagging this as a low-stakes default rather than
  a researched decision, changeable freely in the dashboard or this
  file.
- `ENVIRONMENT=production` and `PLAID_ENV=production` are set directly
  (not secrets, not `sync: false`) since they're fixed, non-sensitive
  values for the prod deploy target. Every other `Settings` field is
  declared with `sync: false`, meaning **Render prompts for a real
  value in its dashboard on first deploy from this blueprint and
  stores it there** — never in this file, never in git.

## Every env var `.env.example` documents (mirrors `app/config.py`'s `Settings`)

| Var | Purpose | Where to get a real value |
|---|---|---|
| `ENVIRONMENT` | `"development"` / `"production"`, defaults to development | n/a — you choose |
| `DATABASE_URL` | SQLAlchemy async Postgres connection string | Local Postgres (dev) / Neon project dashboard -> Connection Details (prod) — **see the sslmode caveat below** |
| `PLAID_CLIENT_ID` | Plaid API client ID | Plaid dashboard -> Team Settings -> Keys |
| `PLAID_SECRET` | Plaid API secret | Plaid dashboard -> Team Settings -> Keys |
| `PLAID_ENV` | `"sandbox"` / `"production"`, defaults to sandbox | n/a — matches which Plaid secret you're using |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot API token | @BotFather (`/newbot` or `/token`) |
| `TELEGRAM_ALLOWED_CHAT_ID` | Personal-use chat allowlist | Your own Telegram numeric chat ID |
| `TELEGRAM_WEBHOOK_SECRET_TOKEN` | Verifies inbound Telegram webhook calls | You generate it (`openssl rand -hex 32`), register with Telegram's `setWebhook` |
| `ADMIN_USERNAME` | Basic Auth for `/link-account` UI | You choose it |
| `ADMIN_PASSWORD` | Basic Auth for `/link-account` UI | You choose it |
| `TOKEN_ENCRYPTION_KEY` | pgcrypto encryption key for stored Plaid access tokens | You generate it (`openssl rand -base64 32`) |
| `JOBS_TRIGGER_SECRET` | Bearer-auth secret for `POST /jobs/weekly-digest/trigger` | You generate it (`openssl rand -hex 32`) — cron-job.org sends this back |
| `OPENAI_API_KEY` | OpenAI provider for the agent engine | OpenAI platform dashboard -> API keys |
| `GEMINI_API_KEY` | Gemini provider for the agent engine | Google AI Studio -> API keys |

All 14 match `app/config.py`'s current `Settings` fields exactly
(checked against the live file, not just A5 — A5 is accurate here,
nothing was added since it was written).

## `DATABASE_URL` / Neon — driver scheme and a real caveat found

**Scheme normalization:** confirmed `app/config.py`'s
`_normalize_database_url` field validator already rewrites a plain
`postgresql://` or `postgres://` URL to `postgresql+asyncpg://`, per
A5's note for D1. Neon issues plain `postgresql://` URLs, so this part
works as intended — no gap there.

**The real caveat — `sslmode`/`channel_binding`:** Neon's
dashboard-issued connection strings look like:

```
postgresql://<user>:<password>@<host>/<database>?sslmode=require&channel_binding=require
```

`app/config.py`'s validator only rewrites the scheme; it does not
touch this query string. `asyncpg` (the driver behind
`postgresql+asyncpg`) does not accept `sslmode`/`channel_binding` as
connect kwargs the way `psycopg2` does — passing them through
(as SQLAlchemy's asyncpg dialect does for unrecognized query params)
raises `TypeError: connect() got an unexpected keyword argument
'sslmode'` **at first connection**, i.e. inside `app/main.py`'s
`lifespan` on service startup, not at import time — which is why
neither the existing CI import check nor local `import app.main`
smoke tests (both use a bare `DATABASE_URL` with no query string) have
caught this yet.

This is a real, deploy-blocking gap, confirmed against Neon's own
SQLAlchemy connection guide and multiple other projects' documented
fixes for the identical Neon+asyncpg+SQLAlchemy combination. It needs
a code change in `app/config.py` (and possibly `app/database.py`'s
engine construction) — outside DevOps's `app/**` boundary — so it's
written up as its own handoff request rather than patched here:
**`docs/agent-artifacts/devops/2026-09-27-neon-asyncpg-sslmode-handoff-request.md`**.
Routing that to Architect (A5 owns the `database_url` contract) is a
Manager decision.

**Practical consequence for right now:** if the user provisions Neon
and Render before that fix lands, the service will build and start but
fail on first DB access. Recommend sequencing the code fix (or at
minimum confirming the workaround below) before actually pointing
Render at a live Neon database, even though the config files here are
otherwise ready.

## `cron-job.org` setup (weekly digest trigger) — manual dashboard steps, not a committed file

Per R4, there's no in-process scheduler (`app/main.py` confirms this —
no scheduler lifecycle code). The weekly digest is triggered externally.
This is entirely an external SaaS dashboard configuration —
`cron-job.org` has no repo-side config file to commit. Steps for the
user:

1. Create a free account at cron-job.org (no card required, per R4).
2. Create a new cron job with:
   - **URL:** `https://<your-render-service>.onrender.com/jobs/weekly-digest/trigger`
     (the exact hostname is assigned by Render once the service is
     created — fill this in after O1a is deployed).
   - **Method:** `POST`
   - **Header:** `Authorization: Bearer <JOBS_TRIGGER_SECRET>` — the
     exact same value entered for `JOBS_TRIGGER_SECRET` in Render's
     environment variable dashboard (per `app/gateway/router.py`'s
     `_verify_jobs_trigger_secret`, which expects a `Bearer <token>`
     `Authorization` header compared via `secrets.compare_digest`).
   - **Schedule:** weekly, your desired day/time and timezone
     (cron-job.org supports per-job timezones per R4's findings — pick
     whatever "weekly digest" cadence the product intends; not
     specified elsewhere in the artifacts I read, so left to the
     user's preference here).
3. cron-job.org's free tier has no automatic retries and only email
   alerting on failure (per R4) — a low-stakes failure mode for a
   single weekly job (worst case: one week's digest doesn't arrive).
   No fallback service is recommended, matching R4's own conclusion.
4. Because Render's free tier spins down after 15 min idle, the first
   cron hit after a dormant week will eat Render's ~1 min cold-start
   delay before the job actually runs — cron-job.org's request timeout
   should be set generously (its default is usually fine, but confirm
   it's not set below ~60s) so it doesn't mark the job "failed" purely
   due to the cold start.

## Limitations on what I could verify in this sandbox

- **No Docker daemon available.** `docker` the CLI binary exists at
  `/usr/local/bin/docker` but `docker info` fails (no daemon running)
  — could not actually `docker build` the `Dockerfile`. Verified only
  by hand: instruction-by-instruction read-through
  (`FROM`/`WORKDIR`/`COPY`/`RUN`/`COPY`/`ENV`/`EXPOSE`/`CMD`, all
  well-formed single-purpose lines, `CMD` uses shell form specifically
  so `${PORT}` expands — a JSON-array `CMD` would not expand env vars).
  This is a real, not just formal, limitation — a genuine build could
  still fail on something a syntax read-through can't catch (e.g. a
  transitive dependency needing a system library not present in
  `python:3.12-slim`, per the Dockerfile's own comment about
  `build-essential`).
- **`render.yaml` parsed successfully** with Python's `yaml.safe_load`
  (confirms valid YAML) and its structure matches Render's documented
  Blueprint schema by inspection — not validated against a live Render
  account (I have no such account/credentials, and provisioning one is
  a user action, see below).
- **Did not attempt to fix or verify the Neon/asyncpg `sslmode` issue
  in code** — confirmed by web research (Neon's own SQLAlchemy guide,
  matched against multiple independent projects' documented fixes for
  the same combination), not by running this app against a live Neon
  database (no Neon account exists yet for this project).
- **`.env.example` env var list** was checked against `app/config.py`
  on this branch directly (all 14 fields), not against a running app
  — pydantic-settings would in principle be able to validate that
  `.env.example`'s keys are a superset of what `Settings` requires,
  but doing so isn't meaningful without also injecting real values, so
  this was a manual field-by-field comparison instead.

## Requires User Approval

None of the files in this PR provision or spend anything by
themselves — `Dockerfile`/`render.yaml`/`.env.example` are config-as-
code only. The following remain manual actions only the user can take,
none performed here:

1. **Create a Render account** and deploy this repo as a Blueprint
   (Render dashboard -> New -> Blueprint -> point at this repo/branch
   once merged) — this is what actually provisions the free web
   service.
2. **Create a Neon account and project**, copy its connection string
   into Render's `DATABASE_URL` env var — recommend doing this only
   after the sslmode handoff request above is resolved, or the service
   will fail on startup.
3. **Enter every `sync: false` var's real value** in Render's
   environment variable dashboard (`PLAID_CLIENT_ID`, `PLAID_SECRET`,
   `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_CHAT_ID`,
   `TELEGRAM_WEBHOOK_SECRET_TOKEN`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`,
   `TOKEN_ENCRYPTION_KEY`, `JOBS_TRIGGER_SECRET`, `OPENAI_API_KEY`,
   `GEMINI_API_KEY`, `DATABASE_URL`) — none of these exist anywhere in
   this repo, by design.
4. **Create a cron-job.org account** and configure the weekly-digest
   pinger per the steps above, once Render has assigned a real
   hostname.

## PR

Branch `devops/render-neon-deploy-config`, pushed to `origin`. Per the
current `.claude/AGENTS.md` Section 3.5 git carve-out (2026-09-26),
DevOps may commit/push its own per-ticket branch and open a PR against
`main` directly — done here (see the compare/PR link reported
alongside this artifact).

## Files touched

- `.env.example` (new)
- `Dockerfile` (new)
- `render.yaml` (new)
- `docs/agent-artifacts/devops/2026-09-27-render-neon-deploy-config.md` (this file, new)
- `docs/agent-artifacts/devops/2026-09-27-neon-asyncpg-sslmode-handoff-request.md` (new)
