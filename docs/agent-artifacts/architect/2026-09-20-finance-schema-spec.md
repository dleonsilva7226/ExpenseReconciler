---
role: architect
status: approved
depends_on: [docs/agent-artifacts/researcher/2026-09-20-bank-ingestion-provider-options.md, docs/agent-artifacts/architect/2026-09-20-webhook-ingestion-contract.md, docs/agent-artifacts/architect/2026-09-20-account-linking-ui-spec.md]
supersedes: [docs/agent-artifacts/architect/2026-09-13-currency-storage-spec.md]
---

**Approved by user, 2026-09-20.** **Amended by user request, 2026-09-20**
— `plaid_access_token` column updated to store a `pgcrypto`-encrypted
value instead of plaintext; see the amendment note below.

# Spec (A1): Finance Domain Schema

## Input

Formalizes the currency-storage dry run (`NUMERIC(19,4)` + ISO 4217
`currency_code`, superseded by this spec) into real
`CreditAccount`/`FinancialTransaction` models, and adds the Plaid
linkage fields A2a referenced but didn't define.

## `app/domains/finance/models.py` (SQLAlchemy 2.0 async, `Mapped[...]`)

### `CreditAccount`

| column | type | notes |
|---|---|---|
| `id` | `UUID` (PK) | |
| `plaid_item_id` | `str`, nullable | **amended 2026-09-20:** no longer unique alone — see "Item vs. account identity" below |
| `plaid_account_id` | `str`, nullable | **new, 2026-09-20:** Plaid's per-account id; unique together with `plaid_item_id` |
| `plaid_access_token_encrypted` | `bytea`, nullable | **amended:** `pgcrypto`-encrypted (`pgp_sym_encrypt`), not plaintext — see "Token encryption" below |
| `institution_name` | `str` | e.g. "Chase", "Capital One" — from Plaid at link time |
| `account_name` | `str` | Plaid's account nickname, e.g. "Chase Sapphire Preferred" |
| `account_mask` | `str(4)` | last 4 digits, from Plaid |
| `account_type` | `str` | Plaid's `type` (e.g. `credit`, `depository`) |
| `account_subtype` | `str`, nullable | Plaid's `subtype` (e.g. `credit card`, `checking`) |
| `credit_limit` | `Numeric(19,4)`, nullable | only populated for credit accounts — drives the "credit utilization tracking" from `PLAN.md` |
| `currency_code` | `str(3)` | ISO 4217, per the (superseded) dry run |
| `created_at` / `updated_at` | `DateTime(timezone=True)` | |

### `FinancialTransaction`

| column | type | notes |
|---|---|---|
| `id` | `UUID` (PK) | |
| `account_id` | `UUID` (FK → `credit_accounts.id`) | |
| `provider_transaction_id` | `str`, **unique** | Plaid's transaction id — the idempotency key |
| `amount` | `Numeric(19,4)` | per the dry run's recommendation |
| `currency_code` | `str(3)` | ISO 4217 |
| `posted_date` | `Date` | |
| `merchant_name` | `str`, nullable | |
| `category` | `str`, nullable | Plaid's personal finance category, if present |
| `pending` | `bool` | |
| `created_at` / `updated_at` | `DateTime(timezone=True)` | |

Relationship: `CreditAccount.transactions` (one-to-many) /
`FinancialTransaction.account` (many-to-one).

## Item vs. account identity (amendment 2026-09-20)

**Gap found by Developer during D4, confirmed and fixed with the user:**
a single Plaid Item (one bank login) can cover multiple accounts —
confirmed relevant here, since the user has both a checking and a
credit card account at the same bank. The original schema's
`plaid_item_id UNIQUE` assumed one account per Item, which would
silently drop every account past the first one returned by a Link
session.

**Fix:** `CreditAccount` is now uniquely identified by the pair
`(plaid_item_id, plaid_account_id)`, not `plaid_item_id` alone —
add a composite unique constraint, drop the single-column uniqueness.
One row per actual account, potentially several rows sharing the same
`plaid_item_id`.

**Consequence for the access token:** the Plaid access token is
per-Item, not per-account, so the same encrypted token value is now
duplicated across every `CreditAccount` row sharing an item — harmless
redundancy at this scale (a handful of rows), not worth a separate
`Item` table to normalize away.

**Consequence for ingestion (A2/`PlaidBankConnector.sync_transactions`):**
each transaction returned by Plaid carries its own `account_id`. The
connector must resolve the local `CreditAccount` row **per transaction**
via `(item_id, plaid_account_id)`, not resolve a single local account
for the whole `item_id` up front — the previous implementation's
"one local account per item_id" lookup is no longer valid now that an
item can map to several accounts.

**Consequence for the linking handler (A2a's `/link-account/callback`):**
must loop over every account in the Link session's response and insert
one `CreditAccount` row per account, not just `accounts[0]`.

## Token encryption (amendment — supersedes A2a's original "store
directly" note)

`plaid_access_token_encrypted` is written and read via Postgres's
`pgcrypto` extension rather than as plaintext:

- **Requires** `CREATE EXTENSION IF NOT EXISTS pgcrypto;` — run once as
  a migration; Neon supports standard extensions including `pgcrypto`,
  but confirming it activates cleanly on Neon's free tier is a D2
  implementation check, not assumed here.
- **Write** (in A2a's `/link-account/callback` handler): parameterized
  raw SQL, `pgp_sym_encrypt(:token, :key)`, not the SQLAlchemy ORM's
  plain `mapped_column` assignment — the encryption has to happen
  inside the SQL statement, not in Python, so the plaintext token
  never round-trips through application memory as a stored value
  (it's still in memory transiently when received from Plaid, which is
  unavoidable).
- **Read** (wherever `PlaidBankConnector.sync_transactions(item_id)` or
  similar needs the live token to call Plaid): `pgp_sym_decrypt(plaid_access_token_encrypted, :key)::text`,
  same pattern in reverse.
- **Key** (`:key` above): a new env var, `TOKEN_ENCRYPTION_KEY` — see
  the amendment to A5.
- This is deliberately a lighter-weight measure than a full secrets
  manager (discussed and declined in conversation for cost/complexity
  reasons at this project's scale) — it protects the token if the
  database is read directly without the app's decryption key (e.g. a
  DB dump, a misconfigured read replica, Neon-side access), but does
  **not** protect against a compromise of the running app itself,
  which holds the key. That's an accepted, explicit trade-off, not an
  oversight.

## Idempotency

`provider_transaction_id` is globally unique specifically so
`finance.service.ingest_transactions(...)` (A2/A3) can be called
repeatedly — from a retried Plaid sync, a re-run digest, whatever —
without double-inserting. Implementation should upsert (insert, or
update `pending`/`amount` if the row already exists — Plaid transitions
transactions from pending to posted with the same id) rather than
insert-or-fail.

## Deferred / explicitly out of scope

- Multi-currency FX conversion (flagged as an open question in the
  original dry run) — not needed yet; only relevant if a linked
  account itself isn't USD, which isn't the case for Chase/Capital One
  personal accounts. Revisit if that changes.
- A separate `Institution` table normalizing `institution_name` — one
  row per account is fine at this scale (2-3 accounts); not worth the
  join for a personal project.

## Requires User Approval

None — design only.
