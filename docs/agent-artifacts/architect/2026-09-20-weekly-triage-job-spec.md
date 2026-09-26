---
role: architect
status: approved
depends_on: [docs/agent-artifacts/researcher/2026-09-20-scheduled-job-triggering.md, docs/agent-artifacts/researcher/2026-09-20-telegram-delivery-patterns.md, docs/agent-artifacts/architect/2026-09-20-agent-tool-execution-spec.md]
supersedes: []
---

**Approved by user, 2026-09-20**, including the 30% utilization
threshold.

# Spec (A4): Weekly Financial Triage Job

## Input

R4: no in-process scheduler — the job is triggered externally via an
authenticated HTTP endpoint. R2: digest must respect Telegram's 4,096
character limit and should be summarized, not exhaustive. A3: the
Gemini-backed `run_weekly_triage(...)` entry point does the actual
reasoning/text generation.

## Trigger

`POST /jobs/weekly-digest/trigger` (on `gateway/router.py`, alongside
A2's other endpoints), protected by `JOBS_TRIGGER_SECRET` (A5) — a
bearer token or query param compared via `secrets.compare_digest`, not
the admin Basic Auth from A2a (this is machine-to-machine, called by
an external cron service, not a browser). Called weekly by
`cron-job.org` per R4.

## Idempotency

New table, `DigestLog` (added to `app/domains/finance/models.py` as
part of implementing this ticket — additive to A1's approved schema,
not a change to any existing table, so it doesn't require reopening
A1's approval):

| column | type |
|---|---|
| `id` | `UUID` (PK) |
| `sent_at` | `DateTime(timezone=True)` |
| `period_start` / `period_end` | `Date` |

On trigger: check whether a `DigestLog` row already exists with
`period_end` covering the current week; if so, return 200 without
re-sending (protects against a duplicate cron fire or manual
double-trigger while testing).

## Job logic

1. Query the past 7 days of `FinancialTransaction` rows across all
   `CreditAccount`s (via `finance.service`, not a tool — this is
   server-side logic, not an LLM-driven query).
2. Compute credit utilization per account: `balance / credit_limit`
   where `credit_limit` is set (per A1's `CreditAccount.credit_limit`).
3. Pass the compiled transactions + utilization figures to
   `agent.engine.run_weekly_triage(...)` (A3) — Gemini synthesizes the
   natural-language summary, leaning on its larger context budget to
   reason over the full week rather than a pre-aggregated slice.
4. Format the result for Telegram: **must fit 4,096 characters** (R2).
   If the generated summary risks running long, the prompt to
   `run_weekly_triage` should explicitly instruct the model to produce
   a bounded-length summary (e.g. "under 3000 characters, prioritize
   categories/merchants over line-by-line transactions") rather than
   truncating a possibly-mid-sentence response after the fact.
5. Send via Telegram Bot API to `TELEGRAM_ALLOWED_CHAT_ID` (A5/A2).
6. Write the `DigestLog` row.

## What "credit utilization tracking" means here (resolving `PLAN.md`'s vague phrasing)

Simple ratio per account (current balance ÷ credit limit), surfaced in
the digest — e.g. flagging any account over some threshold (a
reasonable default like 30%, commonly cited for credit-score impact —
**confirmed at 30% by you, 2026-09-20**.

## Requires User Approval

None outstanding — the utilization threshold above is resolved.
