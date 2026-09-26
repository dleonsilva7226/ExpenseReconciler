---
role: qa
status: in-review
depends_on: [docs/agent-artifacts/developer/2026-09-20-d1-d4-bootstrap-status.md, docs/agent-artifacts/developer/2026-09-20-d1-pr.md, docs/agent-artifacts/developer/2026-09-20-d2-pr.md, docs/agent-artifacts/developer/2026-09-20-item-account-identity-fix.md, docs/agent-artifacts/developer/2026-09-21-d3-pr.md, docs/agent-artifacts/developer/2026-09-22-d4-pr.md, docs/agent-artifacts/architect/2026-09-20-finance-schema-spec.md, docs/agent-artifacts/architect/2026-09-20-webhook-ingestion-contract.md, docs/agent-artifacts/architect/2026-09-20-account-linking-ui-spec.md]
supersedes: []
---

# Test Report (Q1): D1-D4 Test Suite

## Scope

First test suite for this repo -- zero tests existed before this
ticket. Covers everything merged to `main` as of `ab08765`: D1
(bootstrap -- `app/main.py`, `app/config.py`, `app/database.py`), D2
(finance models/schemas), D3 (finance service), D4 (gateway/Plaid
integration), including the 2026-09-20 item/account identity fix and
the 2026-09-26 `AdminUser` refactor.

47 tests, organized to mirror `app/`:

```
tests/
├── conftest.py                              # env setup + shared fixtures
├── test_config.py                           # D1 priority 5
├── domains/finance/
│   ├── test_models.py                       # D2 priority 6
│   └── test_service.py                      # D3 priority 1
├── gateway/
│   ├── test_auth.py                         # D4 priority 3 (unit)
│   └── test_router.py                       # D4 priorities 3 + 4 (endpoint)
└── integrations/bank/
    └── test_plaid_connector.py              # D4 priority 2
```

## Result: 47 passed, 0 failed

```
$ python -m pytest tests/ -q
...............................................                          [100%]
47 passed in 0.47s
```

Run with Python 3.11 (this sandbox's default `python3` is 3.8, which
can't even import `app/domains/finance/models.py` -- its `X | None`
annotations, evaluated by SQLAlchemy's declarative mapper via
`from __future__ import annotations` + runtime `eval`, need 3.10+; this
matches the D1-D4 status note's own observation that the app targets
3.11+, not this sandbox's default). No live Plaid, Telegram, or
Postgres credentials exist in this environment -- every external call
(Plaid API client, Plaid's sync engine, the app's async DB session) is
faked or mocked; see "Approach" below. `ruff check tests/`: clean.

`ruff check tests/` was run standalone (not `ruff check .`) since QA
doesn't own `app/**` and a whole-repo run isn't this ticket's job to
fix either way -- it's `app/**` code, already the previous rounds'
responsibility.

## Priorities and why (highest risk first, per the ticket)

### 1. `service.ingest_transactions` idempotent upsert -- `tests/domains/finance/test_service.py`

The single most safety-critical piece for real financial data: a
duplicate/retried ingest must never double-count a transaction. This
risk is concrete, not theoretical, here -- the connector's own
documented limitation (`plaid_connector.py`'s cursor is always `""`,
so every sync re-fetches full history) means `ingest_transactions` is
*guaranteed* to see the same `provider_transaction_id` repeatedly in
normal operation, not just on a retry.

Tested directly against the real function with a faked `AsyncSession`
(records `execute`/`add` calls; no engine/DB needed since the function
itself never touches anything beyond those two calls):
- empty list is a no-op (no query, no add)
- brand-new transaction: exactly one `session.add`, correct fields
- transaction whose `provider_transaction_id` already exists: `amount`,
  `currency_code`, `pending`, `merchant_name`, `posted_date` are all
  updated **in place** on the existing row, and `session.add` is
  **not** called (no duplicate row) -- this is the core guarantee
- mixed batch (one new + one existing) does both correctly in the same
  call
- one batched `SELECT` for the whole incoming list, not one query per
  transaction (guards against an accidental N+1)

All 5 pass.

### 2. `plaid_connector.py` per-transaction account resolution -- `tests/integrations/bank/test_plaid_connector.py`

The item/account identity fix
(`docs/agent-artifacts/developer/2026-09-20-item-account-identity-fix.md`):
a Plaid Item can cover multiple accounts, so `sync_transactions` must
resolve each transaction to the correct local account via its own
`account_id`, not misattribute everything to one account for the whole
Item -- and must skip-and-log (not crash) a transaction for an account
Plaid knows about but that was never linked locally.

Tested with a fake `Engine`/`Connection` pair standing in for the
connector's dedicated sync SQLAlchemy engine (real production code
runs, just against a fake connection instead of Postgres):
- `_get_decrypted_access_token`: returns the token when a row is
  found; raises `ValueError` when the item isn't linked
- `_get_local_account_id_map`: returns the full `plaid_account_id ->
  local id` map for every account under an item (not just one);
  raises `ValueError` when the item isn't linked
- `sync_transactions`: two transactions for two *different* accounts
  under the same Item each resolve to their own correct local account
  (this is the regression the fix closes -- the old code resolved one
  local account per item_id, which would have put both transactions on
  whichever account it picked)
- a transaction for an account not linked locally is skipped, not
  crashed on or misattributed, and a warning is logged naming the
  item_id
- `added` and `modified` are both included
- an all-unlinked batch returns an empty list cleanly

All 9 pass.

### 3. `gateway/auth.py` + admin-gating on `/link-account*` -- `tests/gateway/test_auth.py`, `tests/gateway/test_router.py`

`require_admin` tested directly (correct credentials accepted, wrong
username/wrong password/both wrong all rejected with 401 + a
`WWW-Authenticate: Basic` challenge header) and again end-to-end
through real HTTP requests to all three admin routes (`GET
/link-account`, `POST /link-account/token`, `POST
/link-account/callback`): each returns 401 with no credentials and with
wrong credentials, 200 with correct ones. The `/link-account/callback`
success case also mocks the bank connector's `exchange_public_token`
and the router's `async_session_factory` (via a fake `AsyncSession`
recording `execute` calls) to confirm the item/account fix holds at
the route level too: a 2-account Link payload produces exactly 2
inserts and `accounts_linked: 2` in the response, not just the first
account.

All 9 pass (5 in test_auth.py, plus the auth-gating assertions folded
into test_router.py's endpoint tests below).

### 4. Webhook auth on `/webhooks/plaid` and `/webhooks/telegram` -- `tests/gateway/test_router.py`

- Plaid: missing `Plaid-Verification` header -> 401 (real
  `verify_plaid_webhook`, no mocking needed -- it short-circuits on an
  empty header); an invalid/rejected signature (mocked
  `verify_plaid_webhook` returning `False`, since a real ES256
  signature can't be produced without live Plaid webhook-verification
  keys) -> 401; a valid signature with `webhook_code ==
  SYNC_UPDATES_AVAILABLE` -> 200 and the background sync task
  (`_run_plaid_sync`, mocked to avoid a real DB/Plaid round trip) is
  scheduled with the right `item_id`; any other webhook_code -> 200
  but the sync is *not* scheduled.
- Telegram: no `X-Telegram-Bot-Api-Secret-Token` header -> 401; wrong
  secret -> 401; correct secret + the allowlisted chat_id -> 200
  acknowledged; correct secret + a different chat_id -> also 200
  acknowledged (the "silently dropped" behavior -- see caveat below);
  an update with no `message` at all (e.g. an edited_message-only
  update) doesn't crash the allowlist check.

All 9 pass.

**Caveat worth flagging explicitly (not a bug):** "wrong chat silently
dropped" and "right chat processed" are only distinguishable in the
*code path taken* right now, not in any observable response
difference -- both return the identical `{"acknowledged": true}`,
because dispatch to `app/agent/engine.py` is A3/D5's contract and
isn't built yet (the router's own comment confirms this is an
intentional placeholder). The tests assert both paths return 200
without erroring, which is what's actually checkable today; once D5
lands, the "right chat processed" test should be strengthened to
assert the update was actually dispatched.

### 5. `config.py` database_url normalization -- `tests/test_config.py`

4 parametrized/direct tests: plain `postgresql://` and `postgres://`
both normalize to `postgresql+asyncpg://` (Neon's actual issued
scheme); a URL already using `postgresql+asyncpg://` is left alone
(no double-prefixing); an unrelated scheme (e.g. a hypothetical
`sqlite+aiosqlite://`) is left alone too, guarding against the
validator being broader than it should be.

All 4 pass.

### 6. D2 model/schema sanity -- `tests/domains/finance/test_models.py`

Pure metadata introspection, no engine needed:
`plaid_access_token_encrypted` is `LargeBinary` (`bytea`), nullable;
`CreditAccount`'s only unique constraint is the composite
`(plaid_item_id, plaid_account_id)` pair, and `plaid_item_id` itself
carries no single-column `unique=True` (this is exactly the
pre-amendment bug shape -- a regression back to single-column
uniqueness would silently drop every account past the first one under
a multi-account Item, and this test would catch it);
`FinancialTransaction.provider_transaction_id` is unique + non-null
(the idempotency key priority 1 depends on); FK from
`FinancialTransaction.account_id` to `credit_accounts.id`; both models
carry the shared `id`/`created_at`/`updated_at` mixin columns.

All 7 pass.

## Approach notes

- **No live credentials anywhere.** Plaid's API client, the
  connector's dedicated sync engine, and the app's async DB session
  are all faked/mocked -- never skipped. Where the ticket asked for
  behavior that needs a real service to fully exercise (e.g. an actual
  Plaid ES256-signed webhook, a real Postgres round trip through
  `pgp_sym_encrypt`), the surrounding logic (signature check
  short-circuiting, SQL shape, per-account insert count) is tested
  instead of the network/DB call itself.
- **`TestClient` built without the app's lifespan** (no `with` block),
  matching the precedent the D1-D4 status note already established --
  the lifespan does a real `CREATE EXTENSION`/`create_all` against
  Postgres, unavailable here, and none of this suite's routes need the
  ORM tables to already exist.
- **Python 3.11 venv** (`/opt/homebrew/bin/python3.11`), separate from
  this sandbox's default 3.8, for the same reason the Developer role
  used one during D1-D4: the app's type-hint style needs 3.10+.
- **`fastapi.testclient.TestClient` required an `httpx2` package** to
  even import, under the versions `pip install -r requirements.txt`
  resolved unpinned (`fastapi==0.141.1` / `starlette==1.7.0`) --
  added as a Q1-only test dependency in `requirements.txt` (see below).
  This is worth DevOps/Architect awareness: `requirements.txt` has no
  version pins yet (flagged as O2's job in the D1-D4 status note), and
  resolving completely unpinned today already pulls in a very recent
  major Starlette rewrite. Not filing this as a bug-report since
  nothing is actually broken -- the app itself imports and runs fine
  under these versions -- but it's a heads-up for whoever eventually
  pins dependencies.

## `requirements.txt` changes

Added a new `# Q1 (QA, tests/** only) additions:` section: `pytest`,
`pytest-asyncio` (the code under test is async), `pytest-mock`, and
`httpx2` (transitively required by `fastapi.testclient.TestClient`
under the currently-unpinned dependency versions -- see above). No
`app/**` dependency was touched.

## Not covered (explicitly out of scope for Q1, or no code yet to test)

- `app/gateway/static/link_account.html` (frontend JS) -- no test
  framework for it in scope here.
- `plaid_webhook.py`'s actual JWT/ES256 verification algorithm against
  a real signed webhook -- can't be done without live Plaid
  sandbox credentials; the D1-D4 status note already flags this as
  needing a sanity check once those exist. `verify_plaid_webhook` is
  exercised indirectly (mocked) at the router level, not directly
  unit-tested against a real signature.
- `app/agent/**`, `app/jobs/**` -- don't exist yet (D5/D6).
- Live Postgres behavior of `pgp_sym_encrypt`/`pgp_sym_decrypt`
  themselves (the SQL text is present in `plaid_connector.py` and
  `router.py` but only exercised against fakes here) -- would need a
  real Postgres with `pgcrypto` enabled; worth a follow-up
  integration-level check (e.g. via Docker Compose in CI) if that
  becomes available, not something a unit suite can responsibly fake.

## Bug reports filed

None. No defect was found in the merged D1-D4 code during this pass --
every test that failed on first write was a test-writing mistake on my
end (fixed before this report), not an application bug. See "Not
covered" above for gaps that are limits of what's testable without
live credentials, not defects.

## Requires User Approval

None -- test code and a `requirements.txt` addition only, no
irreversible action.
