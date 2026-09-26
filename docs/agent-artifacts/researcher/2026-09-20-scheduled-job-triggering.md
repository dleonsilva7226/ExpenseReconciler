---
role: researcher
status: draft
depends_on: [docs/agent-artifacts/researcher/2026-09-20-hosting-options.md]
supersedes: []
---

# Findings: Scheduled-Job Triggering Under Render's Sleep Model (R4)

**Task:** R5 established Render's free web service spins down after 15
min idle. An in-process `AsyncIOScheduler` can't reliably fire a
Sunday-morning job if the process isn't running at that moment. This
resolves whether to keep APScheduler at all.

## Option 1: Keep APScheduler, try to keep the dyno awake
Would require a separate always-on "keep this awake" pinger anyway
(hitting some health endpoint every <15 min, all week, just so the one
weekly job can fire on schedule). That's strictly more moving parts
than triggering the job directly, for no benefit — recommend against.

## Option 2: Drop APScheduler, use an external cron service to call the job directly
An external free scheduler hits an authenticated endpoint
(`POST /jobs/weekly-digest/trigger`) once a week. Render wakes on the
incoming request (cold start ~1 min, acceptable for a job that isn't
time-critical to the second), runs the job, responds. No scheduler
dependency inside the app at all — `app/main.py` no longer needs
scheduler startup/shutdown lifecycle handling.

**Provider:** `cron-job.org` — free, unlimited jobs, no credit card,
in operation since 2008 with a solid reliability track record. One
caveat: no automatic retries and only email alerting if a trigger
fails to reach the endpoint (e.g. transient Render cold-start timeout).
For a single weekly job this is a low-stakes failure mode (worst case,
one week's digest doesn't arrive and you'd notice) rather than
something that needs a fallback service.

## Recommendation (non-binding)

Drop APScheduler entirely for Phase 1. Replace with:

1. `POST /jobs/weekly-digest/trigger` endpoint, protected by a shared
   secret (separate from A2a's admin Basic Auth — this is
   machine-to-machine, not a browser flow; a bearer token or a query
   param compared via `secrets.compare_digest` is enough).
2. `cron-job.org` configured to call it weekly at the desired
   day/time, in the desired timezone (cron-job.org supports
   per-job timezones, so this doesn't need to be solved app-side).
3. The endpoint itself should be **idempotent within the week** — a
   simple "have we already sent a digest since last Monday" check
   before running — to protect against a duplicate trigger (retry,
   accidental double-click while testing) sending the digest twice.

This removes `APScheduler` as a dependency entirely (simplifies O2's
`requirements.txt` and D1's bootstrap ticket), and removes the
scheduler-lifecycle question `PLAN.md` originally implied needed
solving in `app/main.py`. Formalizing this belongs to Architect ticket
**A4** (weekly triage job spec).

## Sources

- [Best External Cron Job Services Compared (2026)](https://dev.to/ronency/best-external-cron-job-services-compared-2026-8a3)
