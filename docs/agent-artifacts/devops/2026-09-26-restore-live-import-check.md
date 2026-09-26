---
role: devops
status: in-review
depends_on: []
---

# CI: restore live `import app.main` check now that D4/gateway has merged

## Context

`.github/workflows/ci.yml`'s sanity-check step was deliberately downgraded
from a live `python -c "import app.main"` check to a syntax-only
`python -m compileall -q app` check (see
`docs/agent-artifacts/devops/2026-09-21-ci-import-check-fix.md`), because
`app/main.py` imports `app.gateway.router`, which didn't exist yet at that
point in the stacked-PR build (D1→D2→D3→D4). The comment left in the
workflow explicitly said to revisit once the full module graph existed
after D4 merged.

D4 (gateway: webhooks, account-linking UI, Plaid connector) has now merged
into `main` (`8cbf770`, PR #9). `app/gateway/router.py` and the rest of the
module graph `app.main` depends on exist for real, so the live import
check is restored.

## What changed

In `.github/workflows/ci.yml`:

- The "Syntax sanity check" step (`python -m compileall -q app`) is
  replaced with a "Live import sanity check" step running
  `python -c "import app.main"`, matching the original pre-downgrade
  approach.
- The job name reverted from "Lint & syntax sanity check" to "Lint &
  import sanity check".
- The explanatory comment above the step, and the one in the job-level
  `env:` block, were rewritten to reflect that D4 has landed and the
  check is live again (no more "will fail until D4 lands" language).
- The dummy `Settings` env-var block (`DATABASE_URL`, `PLAID_CLIENT_ID`,
  `PLAID_SECRET`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_CHAT_ID`,
  `TELEGRAM_WEBHOOK_SECRET_TOKEN`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`,
  `TOKEN_ENCRYPTION_KEY`, `JOBS_TRIGGER_SECRET`, `OPENAI_API_KEY`,
  `GEMINI_API_KEY`) was left as-is after checking it against the current
  `app/config.py` `Settings` model on `main`: every required field
  (`database_url`, `plaid_client_id`, `plaid_secret`, `telegram_bot_token`,
  `telegram_allowed_chat_id`, `telegram_webhook_secret_token`,
  `admin_username`, `admin_password`, `token_encryption_key`,
  `jobs_trigger_secret`, `openai_api_key`, `gemini_api_key`) is still
  covered by an env var of the matching uppercase name, and the two
  optional fields (`environment`, `plaid_env`) have defaults so they don't
  need one. No changes were needed there.

## Verified locally

Built a throwaway venv (`python3.11`, since `python3.12` wasn't available
in this environment — close enough for an import-check verification),
installed `requirements.txt` cleanly, then ran:

```
DATABASE_URL=postgresql://user:password@localhost:5432/jarvis_ci \
PLAID_CLIENT_ID=dummy-plaid-client-id \
PLAID_SECRET=dummy-plaid-secret \
TELEGRAM_BOT_TOKEN=dummy-telegram-bot-token \
TELEGRAM_ALLOWED_CHAT_ID=123456789 \
TELEGRAM_WEBHOOK_SECRET_TOKEN=dummy-telegram-webhook-secret \
ADMIN_USERNAME=dummy-admin \
ADMIN_PASSWORD=dummy-admin-password \
TOKEN_ENCRYPTION_KEY=dummy-token-encryption-key \
JOBS_TRIGGER_SECRET=dummy-jobs-trigger-secret \
OPENAI_API_KEY=dummy-openai-api-key \
GEMINI_API_KEY=dummy-gemini-api-key \
python -c "import app.main"
```

**Result: succeeded (exit 0).** No `ModuleNotFoundError`, no config
validation error. Traced through why it works cleanly with only dummy
strings:

- `app/database.py`'s `create_async_engine(...)` and
  `app/integrations/bank/plaid_connector.py`'s `build_sync_engine`
  (`create_engine(...)`) are both lazy — no real DB connection is
  attempted at import time, only at first query/connect (and
  `app/main.py`'s DB touch — `CREATE EXTENSION pgcrypto` /
  `create_all` — is inside the FastAPI `lifespan`, not at import time).
- `build_plaid_client` only builds a `plaid.Configuration`/`PlaidApi`
  object client-side; it doesn't call out to Plaid's API at import time.
- `settings.token_encryption_key` is just threaded through as an opaque
  string (used later in a `pgp_sym_encrypt(...)` SQL call at request
  time) — nothing validates its format (e.g. as a Fernet key) at import
  time.

Also re-ran `ruff check .` (clean) and confirmed the edited
`ci.yml` still parses as valid YAML (`yaml.safe_load`).

## Requires User Approval / open issue — not pushed

Per the current `.claude/AGENTS.md` (Section 4's tool-access table),
**DevOps is listed as unable to `git commit`/`git push` to its own
feature branch or open a PR** — that row is checked only for Manager
(unconditionally) and Developer (a dated, narrow carve-out added
2026-09-20 specifically for Developer, per Section 3.4). DevOps's own
row for that capability is unchecked, and Section 3.6 states git write
actions are performed by the Manager (or Developer under its carve-out),
not DevOps.

This conflicts with two things:
1. The task instructions this note was written against, which asked for
   a branch to be created, committed, and pushed to `origin` directly by
   this DevOps agent.
2. Actual precedent in this repo:
   `docs/agent-artifacts/devops/2026-09-20-ci-dependabot.md` and
   `docs/agent-artifacts/devops/2026-09-21-ci-import-check-fix.md` both
   record a prior DevOps agent branching, committing, and pushing to
   `origin` directly (`devops/ci-dependabot`, `devops/fix-ci-import-check`).

`.claude/AGENTS.md` shows as staged-but-further-modified in `git status`
at the start of this session, so it looks like it's being actively
tightened right now — plausibly to remove a git ability DevOps used to
have (paralleling Developer's dated carve-out, but this time *not*
extending it to DevOps). Given the binding-document instruction to act
**strictly** as the role AGENTS.md currently defines, and that a task
description cannot override that document, this agent did **not** create
a branch, commit, or push. The `.github/workflows/ci.yml` edit above and
this artifact file are left as uncommitted changes in the worktree for
the Manager to review and commit/push (to a feature branch and PR, or
directly, per Manager's own git authority) — or, if the user intends for
DevOps to retain the same git carve-out Developer has, that should be
made explicit in `.claude/AGENTS.md` first.

## Files touched (uncommitted, awaiting Manager)

- `.github/workflows/ci.yml`
- `docs/agent-artifacts/devops/2026-09-26-restore-live-import-check.md` (this file)
