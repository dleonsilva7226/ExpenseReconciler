---
role: devops
status: in-review
depends_on: []
supersedes: []
---

# Infra Note (O1): local-dev `docker-compose.yml`

## What this is

Per the project-completion tickets
(`docs/agent-artifacts/manager/2026-09-20-project-completion-tickets.md`,
O1): a **local-development-only** Docker Compose setup — an `api`
service and a local Postgres `db` service, networked together, with a
named volume for data persistence. Not used in production; production
is Render (compute) + Neon (Postgres) per the R5 hosting decision
(`docs/agent-artifacts/researcher/2026-09-20-hosting-options.md`,
`docs/agent-artifacts/manager/2026-09-20-hosting-decision.md`) and
O1a's Render config (`docs/agent-artifacts/devops/2026-09-27-render-neon-deploy-config.md`).
This exists purely so the user can run the app on their own machine
before going anywhere near Render.

## What was built

- **`docker-compose.yml`** (repo root):
  - `db`: `postgres:16` (matches the `python:3.12-slim` pin style of
    reusing a specific recent stable version; no prior artifact pinned
    a Postgres major version, and 16 is a reasonable current-stable
    choice that Neon also supports). Named volume
    `jarvis_local_db_data` for persistence across `docker-compose
    down`/`up` cycles (not across `down -v`, deliberately — see
    quick-start's reset instructions). Port `5432` published to the
    host for direct `psql` access if wanted. Local-only throwaway
    credentials (`POSTGRES_USER=localdev`, `POSTGRES_PASSWORD=localdev`,
    `POSTGRES_DB=jarvis_local`) set directly in the compose file — not
    a secret in any meaningful sense (container-local password with no
    external validity), and deliberately an obvious placeholder value
    rather than anything resembling a real credential, consistent with
    the O3 "references only, no real values" posture for anything that
    *is* a real secret. Health check via `pg_isready` so `api` doesn't
    race Postgres's startup.
  - `api`: builds from the **existing** `Dockerfile` (O1a's
    Render-oriented one) via compose's `build:` directive, unchanged.
    Judgment call: reused as-is rather than adding a dev-specific
    Dockerfile/stage or a live-reload volume mount. Reasoning below.
    `depends_on: db` with `condition: service_healthy`. `env_file:
    .env` — **no values hardcoded in the compose file for `api`**; all
    app config comes from a local `.env` the user creates themselves
    (from `.env.example`, O3). Port `8000:8000`, matching the
    Dockerfile's `CMD` (`uvicorn ... --port ${PORT}`, `PORT` defaulting
    to `8000` via the Dockerfile's own `ENV PORT=8000`).
  - No top-level `version:` key — obsolete/ignored by the Compose
    version installed in this environment (`Docker Compose version
    v5.1.1`) and by current Compose spec generally.

- **`README.md`**: added a "Local development" section (the existing
  file was a one-line stub, `# ExpenseReconciler`, so this is more
  discoverable than an artifact-only doc for someone about to run the
  app). Covers prerequisites, `.env` setup — explicitly which fields
  need real values vs. can stay placeholder (see below), bringing the
  stack up, verifying it's live, and tearing down / resetting the DB
  volume.

## Design choice: reused Dockerfile as-is, no dev-specific variant

Checked whether the existing `Dockerfile` (O1a, built for Render) is
reusable for local dev via `docker-compose`'s `build:` directive, per
the ticket's instruction to use judgment here.

- It `COPY`s `app ./app` (static, not a live-reload mount) and runs
  plain `uvicorn app.main:app` (no `--reload`).
- Decided **not** to add a `docker-compose.override.yml` with a source
  volume mount + `--reload` for this ticket. Reasoning: the ticket's
  own framing is "the user can bring this up and hit it locally," not
  a polished iterative-dev workflow, and the existing Dockerfile
  already satisfies that bar — `docker-compose up --build` rebuilds
  the image on every code change reasonably fast at this project's
  current size. A live-reload dev variant is a real quality-of-life
  improvement but is additional scope beyond what was asked; flagging
  it here as a natural follow-up (a small `docker-compose.override.yml`
  adding a `./app:/app/app` volume mount and overriding `CMD` to add
  `--reload`) rather than building it speculatively.
- No `app/**` changes were needed to make this work — the existing
  Dockerfile CMD binds `0.0.0.0:${PORT}`, which is exactly what
  compose's `api` service needs to be reachable at `localhost:8000`.
  No handoff-request was necessary.

## Env vars: what needs a real value vs. what can stay placeholder

Cross-checked every field in `app/config.py`'s `Settings` (the
authoritative list per A5,
`docs/agent-artifacts/architect/2026-09-20-config-secrets-contract.md`)
against how it's actually used in `app/**`, to confirm — not assume —
what's needed just to start the server locally:

- **`DATABASE_URL`** — must be real (points at the `db` service):
  `postgresql://localdev:localdev@db:5432/jarvis_local`.
- **`TELEGRAM_ALLOWED_CHAT_ID`** — typed as `int` in `Settings`.
  `.env.example`'s placeholder (`your-telegram-chat-id-here`) is
  **not** a valid int and will fail Pydantic validation at startup —
  flagged explicitly in the README as needing *some* numeric value
  (e.g. `0`), even though it doesn't need to be a real chat ID just to
  start the process.
- **`ADMIN_USERNAME`/`ADMIN_PASSWORD`** — any value works; checked
  `app/gateway/auth.py`'s `require_admin` — it's a local
  `secrets.compare_digest` check against these settings values, no
  external call.
- **`TOKEN_ENCRYPTION_KEY`**, **`TELEGRAM_WEBHOOK_SECRET_TOKEN`**,
  **`JOBS_TRIGGER_SECRET`** — any non-empty string satisfies startup;
  none are validated against an external service at import time.
- **`PLAID_CLIENT_ID`/`PLAID_SECRET`**, **`TELEGRAM_BOT_TOKEN`**,
  **`OPENAI_API_KEY`**, **`GEMINI_API_KEY`** — placeholder text is
  sufficient for the process to start. Verified by reading the actual
  construction sites rather than assuming "probably lazy":
  - `app/gateway/router.py:47-48` builds `_plaid_client` and
    `_sync_engine` at **module import time** (not per-request), but
    `build_plaid_client` (`app/integrations/bank/plaid_connector.py`)
    only constructs a `plaid.ApiClient`/`PlaidApi` object — no network
    call happens at construction, so a placeholder key doesn't break
    startup. It only surfaces as an error the first time an actual
    Plaid endpoint is called (`/link-account/token`, webhook
    verification).
  - `app/agent/providers/openai_provider.py` and `.../gemini_provider.py`
    construct their clients (`OpenAI(api_key=...)`,
    `genai.configure(api_key=...)`) inside `app/agent/engine.py`'s
    `run_interactive_query`/`run_weekly_triage` functions — i.e. lazily,
    only when an actual agent query runs, not at import time.
  - `app/jobs/weekly_finance_audit.py:137` constructs the Telegram
    `Bot` inside `run_weekly_digest`, also lazily.

  So: server starts fine, `/health` works, and the admin UI page
  loads, but linking a real bank account, sending/receiving real
  Telegram messages, or running an agent/digest query will fail
  without real credentials for that specific integration.

## Table creation / startup behavior

Confirmed via `app/main.py`'s `lifespan` (no Alembic anywhere in the
repo, consistent with the D1 status note's flagged assumption): on
every `api` startup, it runs `CREATE EXTENSION IF NOT EXISTS pgcrypto`
then `Base.metadata.create_all` against `DATABASE_URL`. No separate
migration step exists or is needed for local dev — documented as such
in the README rather than describing a migration step that doesn't
exist.

## Verification performed (and its limits)

**No live `docker-compose up` was run.** This sandbox has a `docker`
CLI (`Docker version 29.3.1`) but no reachable daemon backing it — the
prior O1a ticket confirmed this same limitation for `docker build`,
and it applies equally here.

What *was* actually run and passed:

1. `python3 -c "import yaml; yaml.safe_load(open('docker-compose.yml'))"`
   — parses cleanly.
2. `docker-compose config` (using a copy of `.env.example` as a
   stand-in `.env`, deleted immediately after) — this does not require
   a running daemon, only the CLI's own YAML/interpolation validation.
   It succeeded (exit 0) and rendered the fully-merged config,
   confirming: `env_file` interpolation pulls every expected key from
   `.env.example`'s names correctly into `api`'s environment, the
   `depends_on`/`condition: service_healthy` wiring is syntactically
   valid, `db`'s healthcheck/volume/env blocks are well-formed, and
   port mappings match the Dockerfile's exposed port.
3. Hand cross-referenced `docker-compose.yml`'s `api.ports` against
   `Dockerfile`'s `EXPOSE 8000`/`CMD ... --port ${PORT}` and
   `.env.example`'s var names against `app/config.py`'s `Settings`
   fields — no mismatches found.

**Not verified:** an actual image build, container startup, Postgres
connectivity from inside the `api` container, or that the app
genuinely reaches a healthy running state end-to-end. The user needs
to run `docker-compose up --build` themselves and report back if
something doesn't come up as expected — this is explicitly a
hand-checked, not daemon-verified, artifact.

## Try it now (copy-paste)

```sh
cp .env.example .env
# then edit .env: at minimum set
#   DATABASE_URL=postgresql://localdev:localdev@db:5432/jarvis_local
#   TELEGRAM_ALLOWED_CHAT_ID=0
# (or any integer) — .env.example's own placeholder for this field
# is not a valid int and will fail startup validation as-is.

docker-compose up --build
# in another terminal, once it's up:
curl http://localhost:8000/health
# expect: {"status":"ok"}

# to stop:
docker-compose down
# to also wipe the local DB volume:
docker-compose down -v
```

## Requires User Approval

None — this is a local-dev-only, non-production, non-destructive
addition. No secrets, real values, or irreversible actions are
involved.
