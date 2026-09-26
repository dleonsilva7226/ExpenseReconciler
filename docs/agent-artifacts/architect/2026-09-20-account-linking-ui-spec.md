---
role: architect
status: approved
depends_on: [docs/agent-artifacts/architect/2026-09-20-webhook-ingestion-contract.md]
supersedes: []
---

**Approved by user, 2026-09-20**, including the two flagged decisions
(HTTP Basic Auth over sessions; Plaid access token stored directly in
Postgres over a secrets manager).

# Spec (A2a): Account Linking UI Flow

## Input

A2 flagged that something has to run Plaid Link and call
`BankConnector.exchange_public_token(...)` once per bank account
before ingestion webhooks can fire for that account. You resolved this
as an authenticated UI flow rather than a manual script (2026-09-20).

This is new architectural surface area relative to `PLAN.md`, which
described a headless API + Telegram bot with no web UI. Scope is kept
intentionally minimal below — a single-user utility page, not a real
frontend app — to match that this is a personal project, not a
multi-tenant product.

## Module boundaries

```text
app/
├── gateway/
│   ├── router.py                # existing (A2) + new routes below
│   ├── auth.py                  # NEW — single-user auth dependency
│   └── static/
│       └── link_account.html    # NEW — Plaid Link page (HTML + JS, no template engine)
```

No new top-level module — this lives inside `gateway/` since it's
still "inbound to the app," just browser-driven instead of
webhook-driven.

## Auth model

Single-user HTTP Basic Auth, not a full account/session system:

- `app/gateway/auth.py` exposes a FastAPI dependency using
  `fastapi.security.HTTPBasic`, comparing the submitted
  username/password against `ADMIN_USERNAME` / `ADMIN_PASSWORD` env
  vars via `secrets.compare_digest` (constant-time, avoids timing
  attacks).
- Applied to every route below via `Depends(require_admin)`.
- Deliberately not building sessions, cookies, password hashing, or a
  user table — there is exactly one user (you), and Basic Auth over
  HTTPS is adequate for that. If this ever needs to support more than
  one person, that's a re-spec, not an extension of this one.
- **DevOps dependency:** this must only ever be exposed over HTTPS —
  Basic Auth sends credentials base64-encoded on every request, which
  is fine under TLS and not acceptable in plaintext HTTP. Flagging for
  DevOps runbook (O5): local dev over plain HTTP is fine, anything
  reachable off localhost needs TLS in front of it.

## New env vars (feeds A5 / DevOps O3)

- `ADMIN_USERNAME`, `ADMIN_PASSWORD` — Basic Auth credentials for this
  UI.
- (Already implied by A2:) `PLAID_CLIENT_ID`, `PLAID_SECRET` — needed
  here too, to mint link tokens server-side.

## Routes (added to `gateway/router.py`)

1. **`GET /link-account`** *(auth required)*
   Serves `static/link_account.html` — a static page that loads
   Plaid's `link-initialize.js` from Plaid's CDN and renders a "Link a
   bank account" button. No server-side templating needed; it's one
   static file, so no Jinja2 dependency is introduced for this alone.

2. **`POST /link-account/token`** *(auth required)*
   Server calls Plaid's `/link/token/create`, returns
   `{"link_token": "..."}` to the page's JS, which uses it to
   initialize Plaid Link. Short-lived by Plaid's own design (~30 min);
   minted fresh per page load, never persisted.

3. **`POST /link-account/callback`** *(auth required)*
   Body (from Plaid Link's `onSuccess` callback, forwarded by the
   page's JS):
   ```json
   {
     "public_token": "...",
     "institution_name": "Chase",
     "account_ids": ["..."]
   }
   ```
   Handler calls `BankConnector.exchange_public_token(public_token)`
   (defined in A2), then persists the resulting `item_id` + access
   token against a `CreditAccount` row (ties into A1's `plaid_item_id`
   / `plaid_access_token_encrypted` columns — see A1's "Token
   encryption" section for the required write path). Returns a simple
   success page or redirect back to `/link-account` with a
   confirmation.

## Token storage

**Amended 2026-09-20** — superseded by A1's "Token encryption"
section: the Plaid access token returned by `exchange_public_token` is
still stored in the `CreditAccount` row in the same Postgres database
(a separate secrets-manager service is still not justified at this
scale), but as a `pgcrypto`-encrypted value (`pgp_sym_encrypt`), not
plaintext. The `/link-account/callback` handler must write it via the
parameterized-SQL encryption pattern A1 defines, not a plain ORM
assignment. If scope changes later (multi-user, a less-trusted deploy
target), that's a re-spec, not something to over-build now.

## Out of scope for A2a

- Multi-user support, OAuth/SSO, password reset flows — not applicable
  at this project's scale.
- Unlinking/removing a connected account — worth a follow-up ticket if
  you want it, not blocking Phase 1.
- Editing/re-linking an account whose Plaid connection has expired
  (Plaid Items can enter an error state requiring re-auth) — flagging
  as a known gap, not solving it here; Phase 1 can treat a broken Item
  as "re-run the link flow again."

## Requires User Approval

None directly — design only. Note for your review: this spec commits
to Basic Auth (not sessions) and to storing the Plaid access token
directly in Postgres (not a secrets manager) as scope-appropriate
simplifications — flagging both explicitly in case either doesn't sit
right with you before this moves to `approved`.
