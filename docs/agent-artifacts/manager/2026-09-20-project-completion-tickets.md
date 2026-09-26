---
role: manager
status: in-review
depends_on: []
supersedes: []
---

# Task Breakdown: Project Jarvis Phase 1 — Completion Tickets

## Context

`PLAN.md` defines Phase 1 scope: an event-driven Finance Spoke +
Agent Core Engine (FastAPI + async SQLAlchemy/Postgres, OpenAI +
Gemini, APScheduler, Telegram Bot API, Docker Compose). As of this
writing the repo contains only `LICENSE`, `README.md`, and `PLAN.md`
— no application code, infra, or tests exist yet. These tickets cover
everything needed to go from that state to a working Phase 1 system.

Tickets are grouped by role per `.claude/AGENTS.md`. **Developer
tickets are gated (Section 2.3 of AGENTS.md): none of them may start
until the governing Architect spec is `status: approved` AND the user
has explicitly issued a build command for that ticket.** They're
listed now for planning visibility only.

---

## Researcher tickets

Open questions that block design decisions. Each produces a `findings`
artifact under `docs/agent-artifacts/researcher/`.

- **R1 — Bank alert ingestion format. DONE.** Findings at
  `docs/agent-artifacts/researcher/2026-09-20-bank-ingestion-provider-options.md`:
  recommends Plaid (free hobbyist tier covers Chase + Capital One)
  behind a `BankConnector` provider interface, so per-bank and
  per-aggregator specifics stay out of the ingestion/service code.
  Unblocks A2.
- **R2 — Telegram Bot API delivery patterns. DONE.** Findings at
  `docs/agent-artifacts/researcher/2026-09-20-telegram-delivery-patterns.md`.
  4,096-char message limit → digest must summarize, not enumerate.
  Render's HTTPS is compatible with Telegram's webhook requirements.
  Feeds A4.
- **R3 — OpenAI vs. Gemini tool-calling integration. DONE.** Findings
  at `docs/agent-artifacts/researcher/2026-09-20-openai-gemini-tool-calling.md`.
  Confirms `PLAN.md`'s split (GPT-4o-mini for interactive/tool
  execution, Gemini for large-context weekly triage) is well-founded —
  Gemini's ~1M token window vs. GPT-4o-mini's 128K, plus ~1.5x lower
  cost. Recommends a canonical tool schema + provider adapters, same
  pattern as A2's `BankConnector`. Feeds A3.
- **R4 — Scheduled-job triggering under Render's sleep model. DONE.**
  Findings at
  `docs/agent-artifacts/researcher/2026-09-20-scheduled-job-triggering.md`.
  Recommendation: drop `APScheduler` entirely; use `cron-job.org`
  (free, no card) to call an authenticated, idempotent
  `POST /jobs/weekly-digest/trigger` endpoint weekly. Simplifies D1
  (no scheduler lifecycle) and O2 (one fewer dependency). Feeds A4.
- **R5 — Hosting/deployment options. DONE.** Findings at
  `docs/agent-artifacts/researcher/2026-09-20-hosting-options.md`.
  Decision: **Render (compute) + Neon (Postgres)**, both free/no-card.
  Fly.io ruled out (card required). Render's own free Postgres ruled
  out (auto-deletes after 30 days) — Neon fixes that gap. See decision
  record: `docs/agent-artifacts/manager/2026-09-20-hosting-decision.md`.

## Architect tickets

Each produces a `spec` (or `adr`) artifact under
`docs/agent-artifacts/architect/`, depends_on the relevant Researcher
findings.

- **A1 — Finance schema spec. APPROVED.** Spec at
  `docs/agent-artifacts/architect/2026-09-20-finance-schema-spec.md`,
  supersedes the 2026-09-13 currency-storage dry run. `CreditAccount` +
  `FinancialTransaction` models, including the `plaid_item_id`/
  `plaid_access_token` fields A2a needed.
- **A2 — Webhook ingestion contract. APPROVED.** Spec at
  `docs/agent-artifacts/architect/2026-09-20-webhook-ingestion-contract.md`.
  Pydantic schemas + `gateway/router.py` interface for Plaid + Telegram
  inbound traffic; ingestion happens via a background task, not
  synchronously.
- **A2a — Account linking UI flow. APPROVED.** Spec at
  `docs/agent-artifacts/architect/2026-09-20-account-linking-ui-spec.md`.
  New ticket, split out of A2: a small single-user, Basic-Auth-gated
  page to run Plaid Link and connect a bank account.
- **A3 — Agent tool-execution interface. APPROVED.** Spec at
  `docs/agent-artifacts/architect/2026-09-20-agent-tool-execution-spec.md`.
  New `app/agent/providers/` module (adapters, same pattern as A2's
  `BankConnector`); three read-only, deterministic parameterized-query
  tools (`get_transactions`, `get_account_summary`,
  `get_spending_by_category`) — no text-to-SQL tool.
- **A4 — Weekly financial triage job spec. APPROVED.** Spec at
  `docs/agent-artifacts/architect/2026-09-20-weekly-triage-job-spec.md`.
  Externally-triggered (no scheduler), idempotent via a new `DigestLog`
  table, respects Telegram's 4096-char limit, 30% utilization
  threshold confirmed by you.
- **A5 — Config & secrets contract. APPROVED.** Spec at
  `docs/agent-artifacts/architect/2026-09-20-config-secrets-contract.md`.
  Full `app/config.py` field list consolidated from A2/A2a/R4, plus a
  correction to A2's Plaid webhook-verification note.

## Developer tickets (gated — see above)

Each implements against one `approved` Architect spec, writes a
`status-note` under `docs/agent-artifacts/developer/`.

- **D1 — Bootstrap. MERGED.** `app/main.py`, `app/config.py`,
  `app/database.py`. Depends on A5.
- **D2 — Finance domain models. MERGED.** `app/domains/finance/models.py`,
  `schemas.py`. Depends on A1.
- **D3 — Finance service logic. MERGED.** `app/domains/finance/service.py`
  (ingestion + ledger calculation). Depends on A1, A2.
- **D4 — Gateway. MERGED.** `app/gateway/router.py`, `auth.py`,
  `static/link_account.html`, `app/integrations/bank/**`. Depends on A2, A2a.
  This closes out the original D1-D4 sequence.
- **D5 — Agent engine.** `app/agent/engine.py`, `app/agent/tools.py`.
  Depends on A3. Not yet authorized by the user to build.
- **D6 — Weekly audit job.** `app/jobs/weekly_finance_audit.py`.
  Depends on A4. Not yet authorized by the user to build.
- **D-refactor — Code quality pass. Rounds 1-3 (D1+D2, D3, D4) done.**
  Once each ticket PR merges, a follow-up PR reviews the newly-merged
  code for duplication/DRY-ness and confirms `ruff check .` passes
  cleanly, without sacrificing readability — kept as its own small PR
  per round, not folded into the ticket PRs themselves. Round 1
  (D1+D2) found and fixed real duplication (extracted mixins). Round 2
  (D3) found nothing worth changing. Round 3 (D4) found and fixed one
  real duplication (`AdminUser` dependency alias).

## QA tickets (role added 2026-09-26 — was previously folded into
## Developer's D7; now owned separately per `.claude/AGENTS.md` 3.6)

Each writes tests under `tests/**` and a `test-report` or `bug-report`
under `docs/agent-artifacts/qa/`. Not build-gated the way Developer is —
QA can test against any already-merged or approved-spec code as soon as
the Manager delegates it, without needing its own separate user build
command.

- **Q1 — Test suite for D1-D4.** Coverage for what's currently merged:
  `app/main.py`/`config.py`/`database.py` (D1), finance models/schemas
  (D2), finance service ingestion/upsert logic (D3), gateway webhook
  endpoints + Plaid connector (D4). Not yet authorized by the user to
  start.

## DevOps tickets

Each produces an `infra-note` or `runbook` under
`docs/agent-artifacts/devops/`.

- **O1 — `docker-compose.yml` (local dev only).** API service + local
  Postgres service, networking, volumes — for local development. Not
  used in production per the R5/hosting decision (Render + Neon).
- **O1a — Render + Neon deploy config. NEW (from R5).** `Dockerfile`
  (or Render's native Python build) for the Render web service,
  Render dashboard/service config pointing `DATABASE_URL` at Neon
  instead of local Postgres, and registering the external cron
  pinger from R4 once that's resolved.
- **O2 — Dependency manifest.** `requirements.txt` pinned to the
  Phase 1 stack (FastAPI, Uvicorn, SQLAlchemy 2.0 async, asyncpg,
  Pydantic v2, APScheduler, OpenAI SDK, Gemini client, python-telegram-bot
  or equivalent).
- **O3 — Secrets & env template.** `.env.example` matching the var
  names A5 defines — references only, no values committed.
- **O4 — CI pipeline + Dependabot. IN PROGRESS.** Confirmed in scope by
  you 2026-09-20, delivered as its own PR (separate from D1-D4's
  branch) via an isolated worktree. Lint + import sanity-check (no
  test suite exists yet — D7) on push/PR, plus `dependabot.yml` for
  `pip` + `github-actions`, weekly schedule.
- **O5 — Runbook.** How to bring the stack up locally via Compose, and
  how the Sunday job's schedule/timezone is configured.

---

## Suggested sequencing

1. Resolve **R1** with you directly (bank ingestion source) — nothing
   in the ingestion path can be designed without it.
2. Run R2–R4 in parallel (independent of each other and of R1).
3. A5 (config contract) can start immediately — it only depends on
   knowing the stack, not on R1.
4. A1, A3, A4 can start once their respective Researcher findings land.
5. A2 waits on R1.
6. Developer tickets stay blocked until you review and approve the
   relevant spec(s) and explicitly tell me to build a specific ticket.
7. O1–O3 can largely proceed in parallel with Architect work once A5
   is drafted, since compose/env just need the var *names*, not final
   app code.

## Requires User Input

- **R1** needs your decision on the bank-alert ingestion mechanism
  before it can be scoped.
- **O4** (CI) is optional — confirm if you want it in Phase 1 scope.
- No Developer ticket may start without your explicit build
  instruction per the AGENTS.md build-gate, regardless of spec status.
