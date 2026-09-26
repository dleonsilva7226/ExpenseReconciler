---
role: researcher
status: draft
depends_on: []
supersedes: []
---

# Findings: Hosting / Deployment Options (R5)

**Task:** you asked for a hosting recommendation with one constraint —
no credit card. Also resolves the deployment-target question raised
against A2/A4 (Plaid and Telegram webhooks both need a public HTTPS
endpoint reachable from their servers).

## Options checked

### Fly.io — ruled out
As of 2026, Fly.io no longer has a free tier. New accounts get a
2-VM-hour / 7-day trial, and a credit card is required before you can
deploy anything beyond that. Doesn't meet your constraint.

### Render — partially fits, one real problem
Render's free web service tier genuinely requires no credit card:
deploy a web service, no payment info needed, suspended (not billed)
if you exceed limits. Free web services get 512MB RAM / 0.1 CPU and
**spin down after 15 minutes of no inbound traffic**, taking ~1 minute
to wake on the next request.

**The problem:** Render's free PostgreSQL databases **expire 30 days
after creation**, with a 14-day grace period to upgrade before the
data is deleted — and free databases don't support backups. For a
personal finance app whose entire point is accumulating transaction
history, losing (or having to manually migrate) the database every
30 days is a real dealbreaker, not a minor inconvenience.

Also relevant: Render's free tier has no free background-worker or
cron-job instance type — cron jobs start at $1/month minimum. So
relying on Render's own scheduling for the weekly digest isn't free
either.

### Neon — good fit for the database half
Neon's free Postgres tier requires no credit card and is a genuinely
permanent tier (not a trial that deletes your data): 0.5GB storage,
100 compute-hours/month, compute scales to zero after 5 min idle but
the database itself doesn't expire or get deleted. Comfortably covers
a personal transaction-history workload.

### Supabase — considered, weaker fit
Also no-card and free, but free projects **pause after 7 days of
inactivity** and can eventually be removed if never resumed — a real
risk for an app that might go quiet between digest runs. Neon's model
fits better here.

### Self-hosting via Cloudflare Tunnel — no cloud vendor at all
`cloudflared` (Cloudflare Tunnel) gives a Docker Compose stack running
on your own machine a public HTTPS URL, without opening router ports,
without a static IP, and without paying anything or entering a card.
Postgres data lives on your own disk, under your own control, with no
external expiry policy of any kind. This is also just... what
`PLAN.md`'s own `docker-compose.yml` already assumed — Compose running
somewhere, not a cloud platform.

**The real tradeoff isn't cost or cards — it's uptime responsibility.**
This only works if some machine you own is actually on and running the
stack when Plaid/Telegram need to reach it (and to fire the Sunday
job). A laptop that sleeps overnight won't cut it; a Raspberry Pi, a
NAS, or an always-on desktop would.

## Direct answer to "is there a specific reason you want the cloud?"

No — I don't have one. The actual technical requirement is just
"something with a public HTTPS URL," not "cloud" specifically. I raised
it as a deployment question because the original spec assumed
webhook-driven ingestion, and webhooks need to reach *something*
public. Self-hosting satisfies that requirement exactly as well as a
cloud host does, without a hosting vendor in the loop at all.

## Recommendation (non-binding)

Comes down to one question only you can answer: **do you have a
machine you're willing to leave on and connected continuously** (old
laptop, mini PC, Raspberry Pi, home server)?

- **If yes:** self-host via Docker Compose + Cloudflare Tunnel. Free
  forever, no card, no data-expiry policy to manage, matches the
  plan's existing infra design as-is. This is my lean if it's an
  option for you.
- **If no:** Render (compute, free, no card) + Neon (Postgres, free,
  no card, no expiry) as two separate free services. Two real caveats
  to accept: (1) webhook responses will occasionally eat a ~1 minute
  cold-start delay after 15 min of inactivity — Plaid/Telegram both
  tolerate this fine; (2) the weekly digest can't rely on Render's own
  process staying alive to fire an in-process APScheduler job on
  schedule while asleep — it would need to be triggered by an external
  free cron pinger (e.g. cron-job.org, also no card) hitting an
  authenticated endpoint that runs the job, rather than the app timing
  itself. This is a real design difference for A4 to account for,
  not just a deployment detail.

## Sources

- [Platforms with a real free tier for developers in 2026](https://render.com/articles/platforms-with-a-real-free-tier-for-developers-in-2026)
- [Pricing | Render](https://render.com/pricing)
- [Deploy for Free – Render Docs](https://render.com/docs/free)
- [Free PostgreSQL instances now expire after 30 days (previously 90) | Render Changelog](https://render.com/changelog/free-postgresql-instances-now-expire-after-30-days-previously-90)
- [Cron Jobs – Render Docs](https://render.com/docs/cronjobs)
- [Does the free tier require a credit card or credits to be added to the account? - Fly.io](https://community.fly.io/t/does-the-free-tier-require-a-credit-card-or-credits-to-be-added-to-the-account/5803)
- [Fly.io Free Trial · Fly Docs](https://fly.io/docs/about/free-trial/)
- [Neon Has a Free Tier — Serverless Postgres, 512 MB Storage, No Credit Card](https://dev.to/0012303/neon-has-a-free-tier-serverless-postgres-with-branching-512-mb-storage-and-no-credit-card-i3e)
- [Which managed Postgres databases have a free tier generous enough to run a real app? - Neon FAQs](https://neon.com/faqs/managed-postgres-databases-free-tier)
