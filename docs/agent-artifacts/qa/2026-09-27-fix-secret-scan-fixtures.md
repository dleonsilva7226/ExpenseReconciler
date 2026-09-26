---
role: qa
status: in-review
depends_on: []
---

# Fix secret-scan false positives in test fixtures

## Context

GitGuardian's PR secret-scan check flags `tests/gateway/test_router.py`
for hardcoded "Authentication Tuple" secrets. This is a false positive,
not a real vulnerability: there are no live Plaid/Telegram/Postgres/AI
credentials anywhere in this repo or environment. The flagged values
were:

- `ADMIN_PASSWORD: "test-admin-password"` and similar static,
  human-readable, credential-shaped literals in `tests/conftest.py`'s
  `_ENV_DEFAULTS`, which `app.config.Settings` reads at import time so
  the app's object graph can construct in tests without a real
  service.
- Literal `auth=("wrong", "creds")` tuples in
  `tests/gateway/test_router.py`'s "wrong credentials, expect 401"
  tests -- these are GitGuardian's "Authentication Tuple" detector's
  specific target (a literal 2-tuple passed as `auth=` to an HTTP
  client call).

The actual string values in both cases were always arbitrary -- the
tests only assert that *some* mismatched or well-known-fake value
gets rejected/accepted appropriately. Swapping static literals for
values generated at collection time changes nothing about what's
tested, but removes the static, human-readable, credential-shaped
string literal that trips the scanner and gets committed to git
history on every PR that touches these files.

## What changed

### `tests/conftest.py`

- Every credential-like entry in `_ENV_DEFAULTS`
  (`PLAID_CLIENT_ID`, `PLAID_SECRET`, `TELEGRAM_BOT_TOKEN`,
  `TELEGRAM_WEBHOOK_SECRET_TOKEN`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`,
  `TOKEN_ENCRYPTION_KEY`, `JOBS_TRIGGER_SECRET`, `OPENAI_API_KEY`,
  `GEMINI_API_KEY`) is now generated at collection time via
  `secrets.token_hex(16)` instead of typed out as a static string.
- `DATABASE_URL` keeps its required DSN shape
  (`postgresql://<user>:<pass>@localhost:5432/testdb`); only the
  `user:pass` segment is randomized (`secrets.token_hex(8)` each).
- `PLAID_ENV` stays the literal `"sandbox"` -- not a credential, it's
  Plaid's own required env-name value.
- `TELEGRAM_ALLOWED_CHAT_ID` stays numeric-looking (the `Settings`
  field is typed `int`) but is now a random 9-digit value
  (`secrets.randbelow(900_000_000) + 100_000_000`) instead of the
  static `"555000111"`.
- Added two new fixtures, `wrong_auth()` and `wrong_webhook_secret()`,
  returning freshly-randomized "definitely wrong" values
  (`secrets.token_hex(8)`, half the byte-length of the "real" values
  above) for negative-auth tests to consume, so no test file needs its
  own static wrong-credential literal. The shorter byte-length is a
  deliberate construction choice: it guarantees (not just
  probabilistically) that a "wrong" value can never collide with a
  "real" one, since the two can never have the same string length.

### `tests/gateway/test_router.py`

- `test_link_account_page_rejects_wrong_credentials` and
  `test_link_account_callback_rejects_wrong_credentials` now take the
  `wrong_auth` fixture and pass `auth=wrong_auth` instead of the
  literal `auth=("wrong", "creds")`.
- `test_telegram_webhook_rejects_wrong_secret_token` now takes the
  `wrong_webhook_secret` fixture instead of the literal header value
  `"wrong-secret"` (same category of literal, same file, fixed for
  consistency even though GitGuardian's specific complaint was about
  the auth tuples).
- The telegram tests' hardcoded chat-id literal (`555000111`, matching
  the old static `TELEGRAM_ALLOWED_CHAT_ID` default) is replaced with
  `settings.telegram_allowed_chat_id` everywhere it needs the
  *allowed* chat, and with `settings.telegram_allowed_chat_id + 1`
  where the test needs a chat id that is guaranteed different from the
  allowed one (`test_telegram_webhook_wrong_chat_id_is_silently_dropped`),
  since the allowed id is now randomized per test run rather than a
  fixed literal both files could agree on by eyeball.

## Test semantics

Unchanged. Every test that was a "wrong creds/token/chat, expect
401/still-200-but-not-processed" test still exercises exactly the same
code path with exactly the same expected outcome -- only the concrete
string/int values feeding it are now generated instead of typed out.
No assertions were touched.

## Verification

- `pytest tests/ -q`, Python 3.11 venv (`/opt/homebrew/bin/python3.11`,
  matching the Q1 ticket's setup in
  `docs/agent-artifacts/qa/2026-09-26-d1-d4-test-report.md`):
  **47 passed, 0 failed**, run 6 times back to back to rule out
  flakiness from the new randomization (all 6 runs: `47 passed`).
- `ruff check tests/`: **clean** ("All checks passed!").
- Confirmed no static credential-shaped string literal remains in the
  two changed files: no `auth=(` literal tuple, no `"test-*"` secret
  strings, no `"wrong-secret"`/`"wrong", "creds"` literals, no
  hardcoded `555000111`/`999999999` chat-id literals.

## Scope note -- other test files not touched

`tests/test_config.py` and `tests/gateway/test_auth.py` also contain
credential-shaped words (e.g. `"password"`, `"secret"`, `"admin"`,
`password="wrong"`), but these are single generic placeholder words
constructed directly as `Settings(...)`/`HTTPBasicCredentials(...)`
kwargs, not `auth=(...)` tuples, and GitGuardian's flag on this PR was
specifically about `tests/gateway/test_router.py`'s Authentication
Tuple pattern and `tests/conftest.py`'s `_ENV_DEFAULTS`. Left as-is per
the task's explicit scope; can be a follow-up QA ticket if GitGuardian
starts flagging those too.

## Not covered by this fix

This PR only prevents *future* GitGuardian flags on new commits to
these files. The commits already on merged/open PRs that GitGuardian
previously flagged (the historical `"test-admin-password"`-style
literals and `auth=("wrong", "creds")` calls, already in `main`'s
history) are not retroactively cleared by this change -- git history
is immutable short of a rewrite, which is out of scope and would be
destructive/irreversible (requires explicit user approval per
`.claude/AGENTS.md` Section 2/3.7, not something QA would do
unilaterally regardless). Those existing flagged findings need to be
dismissed as false positives directly in GitGuardian's dashboard by
whoever has access to it -- that's a manual step outside this
repo/PR.

## Requires User Approval

None. This change only touches `tests/**` (within QA's file-domain per
`.claude/AGENTS.md` Section 3.6), is fully reversible, and does not
touch `main` directly -- it is a PR against `main` per QA's git
carve-out (Section 3.6/3.7), pending Manager/user review and merge.
