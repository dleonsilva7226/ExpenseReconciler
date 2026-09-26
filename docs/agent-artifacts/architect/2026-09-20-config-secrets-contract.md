---
role: architect
status: approved
depends_on: [docs/agent-artifacts/architect/2026-09-20-webhook-ingestion-contract.md, docs/agent-artifacts/architect/2026-09-20-account-linking-ui-spec.md, docs/agent-artifacts/researcher/2026-09-20-scheduled-job-triggering.md, docs/agent-artifacts/researcher/2026-09-20-hosting-options.md]
supersedes: []
---

**Approved by user, 2026-09-20.** **Amended by user request, 2026-09-20**
— added `token_encryption_key` for A1's `pgcrypto` token encryption.

# Spec (A5): Config & Secrets Contract

## Input

Consolidates every env var referenced across A2, A2a, and R4 into one
`app/config.py` contract — the interface DevOps' O3 (`.env.example`)
and O1a (Render service config) implement against, and what D1
(bootstrap) implements.

## Correction to A2

A2 said the Plaid webhook signature check "needs Plaid's webhook
verification key, also env-sourced." That's not quite right and is
corrected here rather than carried forward: Plaid webhook JWTs carry a
`kid` (key ID) header, and the actual verification key is fetched from
Plaid's `/webhook_verification_key/get` endpoint at verify time (using
the same `PLAID_CLIENT_ID`/`PLAID_SECRET` credentials), typically
cached in-process since keys rotate infrequently. No separate static
env var is needed for this — removing it from scope below.

## `app/config.py` (Pydantic `BaseSettings`)

```python
from typing import Literal
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    environment: Literal["development", "production"] = "development"

    # Database (Neon in production, per R5)
    database_url: str  # postgresql+asyncpg://... — see note below on driver scheme

    # Plaid (per A2, R1)
    plaid_client_id: str
    plaid_secret: str
    plaid_env: Literal["sandbox", "production"] = "sandbox"

    # Telegram (per A2)
    telegram_bot_token: str
    telegram_allowed_chat_id: int
    telegram_webhook_secret_token: str

    # Admin UI / account linking (per A2a)
    admin_username: str
    admin_password: str

    # Token encryption (per A1 amendment — pgcrypto)
    token_encryption_key: str  # generate once via `openssl rand -base64 32`, never committed

    # Weekly digest trigger (per R4 — external cron, no APScheduler)
    jobs_trigger_secret: str

    # AI providers (per PLAN.md)
    openai_api_key: str
    gemini_api_key: str

    class Config:
        env_file = ".env"
```

All fields required except `environment` and `plaid_env`, which
default for local dev convenience — production values are set via
Render's environment variable dashboard, not committed anywhere.

## Notes for downstream tickets

- **D1 (bootstrap):** Neon issues a standard `postgresql://` URL;
  SQLAlchemy's async engine needs the `postgresql+asyncpg://` scheme.
  `database_url` should be validated/normalized once in `config.py`
  (a Pydantic field validator rewriting the scheme if needed) rather
  than every call site remembering to do it.
- **D1 (bootstrap):** per R4, `app/main.py` needs **no** scheduler
  startup/shutdown lifecycle code — that entire concern is gone, not
  deferred. Confirming explicitly since `PLAN.md`'s original file-tree
  comment for `main.py` said "App initialization & scheduler
  lifecycle" — that comment is now stale relative to R4/A4.
- **O2 (`requirements.txt`):** drop `APScheduler` from the dependency
  list per R4.
- **O3 (`.env.example`):** should mirror every field above by name,
  with placeholder/example values only — never real secrets.
- **O1a (Render config):** all of the above get set as Render
  environment variables in the dashboard; `database_url` points at
  Neon's connection string.

## Requires User Approval

None — design only, no secrets or values are set by this artifact.
