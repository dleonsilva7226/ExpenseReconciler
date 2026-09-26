---
role: manager
status: approved
depends_on: [docs/agent-artifacts/researcher/2026-09-20-hosting-options.md]
supersedes: []
---

# Decision Record: Hosting — Render + Neon

## Decision

Deploy to **Render** (compute/web service) + **Neon** (PostgreSQL),
both on free, no-credit-card tiers. Self-hosting was considered and
explicitly declined by the user (no interest in keeping a machine
running continuously).

## Why not the alternatives

- **Fly.io** — ruled out; no longer has a free tier, requires a card
  after a 2-hour trial.
- **Render's own free Postgres** — ruled out; auto-deletes 30 days
  after creation (14-day grace period, no backups on free tier).
  Unacceptable for a database meant to accumulate transaction history.
  Neon's free Postgres doesn't have this expiry behavior, so pairing
  Render (compute) with Neon (database) covers the gap.
- **Self-hosting via Cloudflare Tunnel** — technically the most
  durable/free option and would have matched `PLAN.md`'s original
  `docker-compose.yml`-centric design most closely, but requires an
  always-on machine, which the user does not want to maintain.

## Consequences

- `docker-compose.yml` (ticket O1) is now local-dev-only; production
  deploys via a separate Render service config (new ticket O1a).
- Render's free web service spins down after 15 min of inactivity —
  accepted tradeoff: occasional ~1 min cold-start delay on incoming
  webhooks.
- The weekly digest job cannot rely on an in-process scheduler running
  while the service sleeps — resolved by R4 (drop `APScheduler`, use
  an external free cron service to trigger the job via HTTP).

## Full findings

See `docs/agent-artifacts/researcher/2026-09-20-hosting-options.md`
for the full comparison and sourcing.
