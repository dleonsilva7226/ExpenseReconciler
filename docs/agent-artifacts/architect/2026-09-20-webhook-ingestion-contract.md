---
role: architect
status: approved
depends_on: [docs/agent-artifacts/researcher/2026-09-20-bank-ingestion-provider-options.md]
supersedes: []
---

**Approved by user, 2026-09-20.**

# Spec (A2): Webhook Ingestion Contract — Bank + Telegram

## Input

Researcher findings (R1) recommend Plaid, on its free hobbyist tier,
as the ingestion provider, abstracted behind a `BankConnector`
interface so per-bank and per-aggregator specifics stay out of
`app/domains/finance/service.py`.

## Correction to `PLAN.md`'s framing

`PLAN.md` describes `gateway/router.py` as handling "Inbound Webhooks
(Bank alerts & Telegram router)," implying the bank pushes transaction
alerts directly to this app. That isn't how Plaid works, and it's the
reason a direct-from-bank model was ruled out in R1. The actual event
flow is:

1. A bank event happens (new transaction posts).
2. **Plaid** — not the bank — sends **our app** a webhook saying
   "new data is ready for Item `<item_id>`" (webhook type
   `TRANSACTIONS`, code `SYNC_UPDATES_AVAILABLE`).
3. Our app then **pulls** the actual transactions from Plaid's
   `/transactions/sync` endpoint using that `item_id`.

So "bank alerts" in the plan should be read as "Plaid sync-ready
notifications," and the router's job is to receive that notification
and trigger a pull, not to receive transaction data directly in the
webhook body. Flagging this explicitly since it changes the shape of
the endpoint from what the plan's wording suggests.

## Module boundaries

```text
app/
├── gateway/
│   └── router.py                    # FastAPI router: /webhooks/plaid, /webhooks/telegram
├── integrations/
│   └── bank/
│       ├── base.py                  # BankConnector protocol + NormalizedTransaction schema
│       └── plaid_connector.py       # PlaidBankConnector implementation
└── domains/
    └── finance/
        ├── models.py                # (A1) adds BankConnection fields to CreditAccount
        ├── schemas.py                # adds PlaidWebhookPayload, TelegramUpdate
        └── service.py                # ingest_transactions(list[NormalizedTransaction])
```

`app/integrations/bank/` is new relative to `PLAN.md`'s file tree —
needed so `BankConnector` and its Plaid implementation aren't buried
inside the finance domain, keeping the provider swap-out story from R1
real rather than nominal.

## Interfaces

### `BankConnector` (provider abstraction)

```python
class BankConnector(Protocol):
    def sync_transactions(self, item_id: str) -> list[NormalizedTransaction]: ...
    def exchange_public_token(self, public_token: str) -> LinkedAccount: ...
```

- `sync_transactions` — called by the gateway after a Plaid webhook
  fires; returns transactions already normalized to this project's
  shape, not Plaid's raw schema.
- `exchange_public_token` — called once during the account-linking
  flow (Plaid Link on the frontend, or a one-off script for a
  personal project) to turn a short-lived `public_token` into a
  persisted `item_id` + access token reference.
- `PlaidBankConnector` is the only implementation for now (per R1);
  the Protocol exists specifically so a future provider swap or a
  second aggregator doesn't touch `service.py`.

### `NormalizedTransaction` (Pydantic, in `app/integrations/bank/base.py`)

| field | type | notes |
|---|---|---|
| `provider_transaction_id` | `str` | Plaid's transaction id, kept for idempotency/dedup |
| `account_id` | `str` | maps to `CreditAccount.id` |
| `amount` | `Decimal` | `NUMERIC(19,4)` per the currency-storage spec |
| `currency_code` | `str` | ISO 4217, per the currency-storage spec |
| `posted_date` | `date` | |
| `merchant_name` | `str \| None` | |
| `pending` | `bool` | |

This is the only shape `app/domains/finance/service.py` ever sees —
it must not import anything Plaid-specific.

### `PlaidWebhookPayload` (Pydantic, in `app/domains/finance/schemas.py`)

Validates the incoming webhook body: `webhook_type`, `webhook_code`,
`item_id`, plus a signature/verification step (Plaid webhooks are
JWT-signed — the router must verify this before trusting the payload,
not just parse it).

### `TelegramUpdate`

Standard Telegram Bot API update schema (message/command), scoped to
whatever commands the weekly-digest/triage flow needs (e.g. a manual
"run digest now" command). Full shape deferred to A4 (triage job spec)
for the command set; this ticket only defines that the router accepts
and validates Telegram's update payload before dispatching it.

**Authorization model:** this is a single-user personal bot, so
authorization is a **chat ID allowlist**, not a login. The router
checks the inbound update's `message.chat.id` against a
`TELEGRAM_ALLOWED_CHAT_ID` env var (A5/DevOps O3) and silently drops
(200 OK, no processing) anything from any other chat. This is
independent of A2a's Basic Auth — the Telegram bot is never
credential-gated per-message; you just message it normally, and the
allowlist is what keeps strangers who discover the bot's username from
being able to trigger anything. Distinct from Telegram's own webhook
security (a `secret_token` header Telegram sends, which the router
should also verify to confirm a request genuinely came from Telegram's
servers before even parsing the body) — two different checks, both
needed: one proves "this came from Telegram," the other proves "this
is you."

## `gateway/router.py` endpoints

- `POST /webhooks/plaid` — verify JWT signature → parse
  `PlaidWebhookPayload` → if `webhook_code == SYNC_UPDATES_AVAILABLE`,
  hand off to a **background task** (FastAPI `BackgroundTasks` — see
  resolved open question below) that calls
  `PlaidBankConnector.sync_transactions(item_id)` and passes the
  result to `finance.service.ingest_transactions(...)`. The endpoint
  itself returns 200 immediately after signature verification and
  scheduling the task, without waiting on ingestion to finish — Plaid
  expects fast acknowledgment.
- `POST /webhooks/telegram` — parse `TelegramUpdate` → dispatch to
  `app/agent/engine.py` (out of scope for this ticket — A3 owns that
  contract).

## Account linking (not a webhook, but required for `sync_transactions` to have an `item_id`)

**Resolved:** an authenticated UI flow, not a script — see ticket
**A2a**, spec'd separately at
`docs/agent-artifacts/architect/2026-09-20-account-linking-ui-spec.md`.
This introduces a small authenticated web UI as new architectural
surface area beyond `PLAN.md`'s original headless-API-plus-Telegram
shape — flagged for your awareness, not just a footnote.

## Secrets note (for DevOps' O3)

`LinkedAccount` (returned by `exchange_public_token`) includes a Plaid
access token, which must be stored as a reference/encrypted value, not
plaintext, and must never appear in an artifact. `app/config.py` (A5)
needs a `PLAID_CLIENT_ID` / `PLAID_SECRET` pair; the plaid webhook
verification step needs Plaid's webhook verification key, also
env-sourced. The Telegram side needs `TELEGRAM_BOT_TOKEN` (to call the
Bot API), `TELEGRAM_ALLOWED_CHAT_ID` (the chat-ID allowlist above),
and `TELEGRAM_WEBHOOK_SECRET_TOKEN` (verified against Telegram's
`X-Telegram-Bot-Api-Secret-Token` header, set when the webhook is
registered with Telegram).

## Open questions

Both resolved by you on 2026-09-20:

1. ~~Plaid Link: manual script vs. authenticated UI flow?~~ →
   authenticated UI flow. Spec'd in A2a.
2. ~~Webhook ingestion: synchronous vs. background task?~~ →
   background task via FastAPI `BackgroundTasks`, no queue for Phase 1.

## Requires User Approval

None directly — this is a design artifact. No schema migration, code,
or infra change is authorized by it. Promoting this from `draft` to
`approved` (which the Developer build-gate requires) needs your
review, since it introduces a module (`app/integrations/bank/`) not
in the original `PLAN.md` tree.
