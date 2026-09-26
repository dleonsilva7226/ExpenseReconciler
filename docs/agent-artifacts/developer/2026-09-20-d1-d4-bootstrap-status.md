---
role: developer
status: in-review
depends_on: [docs/agent-artifacts/architect/2026-09-20-finance-schema-spec.md, docs/agent-artifacts/architect/2026-09-20-webhook-ingestion-contract.md, docs/agent-artifacts/architect/2026-09-20-account-linking-ui-spec.md, docs/agent-artifacts/architect/2026-09-20-config-secrets-contract.md]
supersedes: []
---

# Status Note: D1–D4 Implementation

## What was built

- **D1 (bootstrap):** `app/main.py`, `app/config.py`, `app/database.py`.
  No scheduler lifecycle (per R4) — startup instead runs
  `CREATE EXTENSION IF NOT EXISTS pgcrypto` and `Base.metadata.create_all`.
- **D2 (finance models):** `app/domains/finance/models.py`
  (`CreditAccount`, `FinancialTransaction`, exactly per A1 including
  `plaid_access_token_encrypted` as `bytea`), `app/domains/finance/schemas.py`
  (`PlaidWebhookPayload`, `TelegramUpdate` + nested Telegram models).
- **D3 (finance service):** `app/domains/finance/service.py` —
  `ingest_transactions()`, idempotent upsert on `provider_transaction_id`,
  only imports `NormalizedTransaction` (never anything Plaid-specific).
- **D4 (gateway):** `app/gateway/router.py`, `app/gateway/auth.py`,
  `app/gateway/static/link_account.html`,
  `app/integrations/bank/base.py`, `app/integrations/bank/plaid_connector.py`,
  `app/integrations/bank/plaid_webhook.py`.
- `requirements.txt` created, seeded only with what this code imports
  (see file header — does not yet include python-telegram-bot/openai/
  google-generativeai, which belong to D5/D6).

## Verification performed

No real Plaid/Telegram/Neon credentials exist yet, so live integration
testing wasn't possible (as expected for this ticket). What was
verified in a throwaway venv (Python 3.11, closer to `PLAN.md`'s
3.12+ target than this sandbox's default 3.8):

- `py_compile` on every new file.
- Full import graph resolves with dummy env vars, including the
  sync-engine path (`psycopg2` installs and connects the dialect
  correctly).
- `app.main`'s FastAPI app builds successfully; its lifespan runs
  correctly up to attempting a real Postgres connection (fails there
  as expected — no real DB available, confirms the startup logic
  itself is wired right).
- Exercised the actual route handlers via `TestClient` against a bare
  app (no lifespan, so no DB dependency): Basic Auth on `/link-account`
  returns 401 with no/wrong credentials and 200 with correct ones
  (serving the real HTML); `/webhooks/plaid` returns 401 with no
  signature header; `/webhooks/telegram` returns 401 with no secret
  header, and — with a valid secret — silently returns 200 for a
  disallowed chat ID and processes a matching one, exactly per A2's
  chat-ID-allowlist model.

## Deviations

- **A5's `class Config: env_file = ".env"`** → implemented as
  `model_config = SettingsConfigDict(...)`, Pydantic v2's idiomatic
  form (A5's snippet used v1-style syntax; `PLAN.md` commits to
  Pydantic v2). Trivial, not a substantive change.

## Assumptions (flagged, not silently decided as final)

1. **No migration tool exists yet.** Schema setup runs via
   `Base.metadata.create_all` + `CREATE EXTENSION` at app startup
   (`app/main.py`'s lifespan), not a dedicated migration step.
   Reasonable for a personal project at this stage; revisit if/when a
   real migrations ticket (e.g. Alembic) gets spec'd.
2. **`BankConnector`'s sync Protocol methods needed DB access** for
   the pgcrypto token lookup, which the app's primary engine (async)
   can't provide inside a sync call. Resolved by giving
   `plaid_connector.py` its own small dedicated sync SQLAlchemy engine
   (adds `psycopg2-binary` to `requirements.txt`), kept fully contained
   in that one module rather than touching `app/database.py`.
3. **Plaid's `transactions_sync` cursor is always `""`** — no
   incremental sync. A1 has no cursor-storage column, so this refetches
   full history each call; `service.ingest_transactions`'s idempotent
   upsert makes this safe, just wasteful. Flagged, not solved — would
   need a follow-up ticket adding a `plaid_sync_cursor` column.
4. **Plaid webhook JWT verification is implemented but unverified
   against a live webhook** (no real Plaid credentials to test
   against). Written against Plaid's documented verification algorithm
   (fetch key by `kid`, verify ES256, check freshness, compare body
   hash) — worth a real sanity check once sandbox credentials exist.
5. **`LinkAccountCallbackRequest`** (the `/link-account/callback` body
   schema) was placed directly in `router.py` rather than
   `domains/finance/schemas.py` — A2a didn't explicitly assign it a
   home; kept local since it's endpoint-specific, not a finance-domain
   concept.

## Known gap needing Architect follow-up (not solved here)

**A1's `CreditAccount.plaid_item_id` is UNIQUE — one row per Plaid
Item — but a single Plaid Link session can return multiple accounts
under one Item** (e.g. checking + savings at the same bank; Link's
`onSuccess` metadata includes an `accounts` array, not a single
account). The `/link-account/callback` handler currently persists only
the **first** selected account and silently drops any others from the
same Link session (returns `accounts_skipped` in the response so it's
at least visible, not silent).

This isn't a blocker for the immediate need (linking one Chase
account), but will produce data loss if a Link session for an account
with multiple sub-accounts is ever used as-is. Fixing it properly
means either constraining Link's account selection to one account at a
time, or a schema change (drop the `plaid_item_id` uniqueness, key
`CreditAccount` on `(plaid_item_id, plaid_account_id)` instead) — an
Architect decision, not mine to make unilaterally.

## Not in scope (confirmed, not attempted)

- `app/agent/**`, `app/jobs/**` — A3/A4 territory (D5/D6).
- `docker-compose.yml`, `Dockerfile`, CI, `.env*` — O1/O1a/O2/O3/O4.
- Test suite — D7.
- `git commit`/`git push` — Manager's action, not taken here.
