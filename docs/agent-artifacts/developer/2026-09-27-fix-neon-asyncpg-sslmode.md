---
role: developer
status: in-review
depends_on: [docs/agent-artifacts/architect/2026-09-20-config-secrets-contract.md]
supersedes: []
---

# Status note: fix Neon/asyncpg `sslmode`/`channel_binding` crash

Closes the DevOps handoff request:
`docs/agent-artifacts/devops/2026-09-27-neon-asyncpg-sslmode-handoff-request.md`
(on unmerged branch `origin/devops/render-neon-deploy-config`, read via
`git show` — not checked out).

Branch: `dev/fix-neon-asyncpg-sslmode`.

## The bug

`app/config.py`'s `_normalize_database_url` field validator only
rewrote the URL scheme (`postgresql://`/`postgres://` ->
`postgresql+asyncpg://`) and left the query string untouched. Neon
issues connection strings like
`postgresql://user:pass@host/db?sslmode=require&channel_binding=require`.
`asyncpg` (the driver behind SQLAlchemy's `postgresql+asyncpg`
dialect) rejects `sslmode`/`channel_binding` as unknown connect
kwargs when SQLAlchemy passes them through from the URL, crashing at
first DB access (`app/main.py`'s `lifespan`, i.e. service startup)
with `TypeError: connect() got an unexpected keyword argument
'sslmode'`.

## The fix

**`app/config.py`:**

- Added `_ASYNCPG_INCOMPATIBLE_QUERY_PARAMS = {"sslmode",
  "channel_binding"}` (module-level constant).
- Added a new `database_ssl: bool = False` field on `Settings`.
- Added a `model_validator(mode="before")` classmethod,
  `_detect_database_ssl`, that inspects the **raw** `database_url`
  input (before any normalization) and sets `database_ssl = True` if
  its query string contains `sslmode` or `channel_binding`. This runs
  before per-field validation, so it sees Neon's original query
  string. An explicit `DATABASE_SSL` env var can still override it if
  ever needed, since it's a normal (if undocumented-in-`.env.example`)
  settings field.
- Extended the existing `_normalize_database_url` field validator: after
  the scheme rewrite, if the resulting scheme is
  `postgresql+asyncpg://`, it now parses the query string
  (`urllib.parse.parse_qsl`/`urlencode`) and strips `sslmode` and
  `channel_binding`, rebuilding the URL. Any other query params (e.g.
  `application_name`) are preserved untouched.

**`app/database.py`:**

- `create_async_engine(...)` now passes `connect_args={"ssl": True}`
  when `settings.database_ssl` is `True`, `{}` otherwise, so TLS is
  enforced explicitly for the asyncpg driver exactly when the original
  `database_url` requested it (Neon's case) — not unconditionally, so
  a plain local dev Postgres URL (no `sslmode` in the URL, per
  `.env.example`) is unaffected.

## Deviations from the DevOps handoff request's suggested mechanics

The handoff request's suggested shape was: strip the params in
`config.py`, force `connect_args={"ssl": True}` in `database.py` "when
the driver is asyncpg" but conditioned on "the original URL actually
requested it." Implementing that condition requires *some* channel to
carry "did the original URL request SSL" from `config.py` (where the
raw URL is seen and then stripped) to `database.py` (which only sees
the already-normalized `settings.database_url`). I added the
`database_ssl` field/`model_validator` for this, rather than e.g. a
module-level global or a private attribute, since it's the most
idiomatic pydantic way to have one field's validation observe another
field's raw input. This field is not named in A5's original
`Settings` field list (A5 predates Neon/asyncpg's incompatibility being
discovered — see the handoff request's "why this didn't get caught
yet" section), but the Manager's build dispatch for this exact ticket
explicitly authorized refining the mechanics and using judgment on
"the cleanest way to satisfy" the SSL condition, so this is treated as
within the authorized scope of this fix rather than requiring a
separate Architect spec update. Flagging it here for Manager visibility
regardless, since it does add one field not in A5's enumerated list.

No other deviations. Nothing outside `app/config.py`/`app/database.py`
was touched.

## Verification performed

All in a throwaway Python 3.11 venv (`/tmp/neonfixvenv` — this
sandbox's default `python3` resolves to 3.8, same reasoning as prior
tickets' status notes), `pip install -r requirements.txt`, not
committed:

1. **Neon-shaped URL**
   (`postgresql://user:pass@ep-cool-host-123.us-east-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require`)
   fed directly to `Settings(...)`: resulting `database_url` ==
   `postgresql+asyncpg://user:pass@ep-cool-host-123.us-east-2.aws.neon.tech/neondb`
   (both query params stripped, scheme correctly rewritten), and
   `database_ssl` == `True`.
2. **Plain local dev URL** (`postgresql://localhost:5432/jarvis_ci`,
   no query string): passes through with only the scheme rewritten,
   `database_ssl` == `False` — confirmed unaffected.
3. **Mixed query string**
   (`postgresql://u:p@host/db?sslmode=require&application_name=foo`):
   only `sslmode` stripped, `application_name=foo` preserved,
   `database_ssl` == `True` — confirms the strip is targeted, not a
   blanket query-string wipe.
4. **Full app import** (`import app.main`) against a full set of dummy
   env vars covering every `Settings` field: imports cleanly.
5. Inspected `app.database._connect_args` directly against the
   Neon-shaped env: `{'ssl': True}`, confirming `create_async_engine`
   receives the expected `connect_args`.
6. `ruff check --fix app/config.py app/database.py` (scoped to the two
   changed files, matching this ticket's file scope): all checks
   passed, no changes needed beyond what was already written.

All six checks passed. Verification script and venv were not
committed (throwaway, per every prior ticket's practice).

## Requires User Approval

None. This is a bug fix within the terms the user already authorized
(build command issued this session against the already-approved A5
spec); no irreversible action is proposed.
