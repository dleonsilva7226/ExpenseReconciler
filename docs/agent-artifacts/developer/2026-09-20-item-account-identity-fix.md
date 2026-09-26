---
role: developer
status: in-review
depends_on: [docs/agent-artifacts/architect/2026-09-20-finance-schema-spec.md]
supersedes: []
---

# Status Note: Item/Account Identity Fix

Closes the gap A1's "Item vs. account identity" amendment (2026-09-20)
describes: a Plaid Item can cover multiple accounts, and the code
previously kept only the first one from a Link session.

## Changes

1. **`app/domains/finance/models.py`** — `CreditAccount` gets a new
   `plaid_account_id` column; the old single-column `unique=True` on
   `plaid_item_id` is replaced with a composite
   `UniqueConstraint("plaid_item_id", "plaid_account_id")`.
2. **`app/gateway/router.py`** (`link_account_callback`) — now loops
   over every account in `body.accounts` and inserts one row per
   account (same `item_id`/token, distinct `plaid_account_id`), instead
   of only `accounts[0]`. Response changed from `accounts_skipped` to
   `accounts_linked` (nothing is skipped anymore).
3. **`app/integrations/bank/plaid_connector.py`** — `_get_local_account_id`
   (single lookup per item) replaced with `_get_local_account_id_map`
   (returns `plaid_account_id -> local id` for every account under the
   item). `sync_transactions` now resolves each transaction's local
   account via its own `account_id` against that map, and skips (with a
   logged warning, not a crash) any transaction whose account isn't
   linked locally.

## Verification

Real Plaid/DB credentials still don't exist, so this was checked the
same way as D1-D4: throwaway Python 3.11 venv, dummy env vars.

- `py_compile` on all three changed files.
- Import graph resolves; confirmed programmatically that
  `plaid_account_id` exists, the composite unique constraint is
  present, `plaid_item_id` is no longer independently unique, and the
  old single-account helper is gone in favor of the map-based one.
- `TestClient` call to `/link-account/callback` with a 2-account Link
  payload (checking + credit card) produced exactly 2 INSERTs, one per
  `plaid_account_id`, both sharing the same `item_id` — confirms the
  gap is closed for the linking path.
- Unit-level check of `sync_transactions`'s mapping logic: 3 fake
  transactions (2 mapped, 1 for an account not linked locally)
  correctly returned only the 2 mapped ones, with the unmapped one
  skipped and logged rather than crashing or misattributed.

## Not touched

`app/agent/**`, `app/jobs/**`, DevOps files, test suite — out of scope
for this patch, as directed.
