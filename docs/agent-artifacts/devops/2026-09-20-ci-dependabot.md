---
role: devops
status: in-review
depends_on: []
---

# CI pipeline + Dependabot config

## What changed

- `.github/workflows/ci.yml` — runs on `push` and `pull_request` to
  `main`. Checks out the repo, sets up Python 3.12 (per `PLAN.md`'s
  tech stack), installs `ruff`, and installs `requirements.txt` only
  when that file exists, then runs:
  1. `ruff check .` (no existing lint config to conflict with).
  2. `python -c "import app.main"` as an import-sanity check when
     `app/main.py` exists, with dummy values for every required field on
     `app.config.Settings` supplied via the job's `env:` block (`DATABASE_URL`,
     `PLAID_CLIENT_ID`, `PLAID_SECRET`, `TELEGRAM_BOT_TOKEN`,
     `TELEGRAM_ALLOWED_CHAT_ID`, `TELEGRAM_WEBHOOK_SECRET_TOKEN`,
     `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `TOKEN_ENCRYPTION_KEY`,
     `JOBS_TRIGGER_SECRET`, `OPENAI_API_KEY`, `GEMINI_API_KEY`). These
     are placeholder strings only, never real secrets, and construct
     the `Settings` singleton without requiring a live database — the
     app's actual DB connection happens lazily inside `app.main`'s
     `lifespan`, not at import time, so no database service is needed
     in this job.
- `.github/dependabot.yml` — two ecosystems, both weekly:
  - `pip`, directory `/` (for when `requirements.txt` is added).
  - `github-actions`, directory `/` (keeps `actions/checkout`,
    `actions/setup-python`, etc. current).

## No-test-suite handling (D7 not started yet)

There is no `tests/` directory yet — D7 (test suite) is a separate,
not-yet-started ticket. Rather than leave the pipeline a no-op (or
have it fail looking for a test command that doesn't exist), this
workflow substitutes two cheap, real checks that are useful today:
static lint (`ruff check .`) and an import-sanity check that the
FastAPI app object actually builds. Both are non-trivial: a broken
import (bad syntax, a missing dependency, a config field mismatch)
will fail this job. When D7 lands a real test suite, whoever
implements it should add a `pytest` step to this same job (or a new
job) — this workflow does not need to change shape, just gain a step.

## Dependabot schedule rationale

Weekly was chosen over daily as a reasonable default for a personal
project — frequent enough to catch security advisories promptly
without generating PR noise faster than a single maintainer can
triage.

## PR

Branch `devops/ci-dependabot` is pushed to `origin`. The `gh` CLI was
not preinstalled in this sandbox, and authenticating it (device-code
login, or polling for that login to complete) was blocked by the
session's auto-mode security classifier (credential-exploration /
unauthorized-persistence). The PR itself was therefore not opened by
this agent — open it via the compare link GitHub prints on push:
https://github.com/dleonsilva7226/ExpenseReconciler/pull/new/devops/ci-dependabot
(or `gh pr create --base main --head devops/ci-dependabot` from an
already-authenticated shell). Update this line with the PR URL once
opened.
