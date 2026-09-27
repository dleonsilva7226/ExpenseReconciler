---
role: devops
status: in-review
depends_on: [docs/agent-artifacts/researcher/2026-09-20-hosting-options.md, docs/agent-artifacts/architect/2026-09-20-config-secrets-contract.md]
supersedes: []
---

# Handoff request: `app/config.py`'s `database_url` normalization doesn't handle Neon's `sslmode`/`channel_binding` params (blocks a real Render+Neon deploy)

## What I was doing

Building O1a (Render + Neon deploy config: `Dockerfile`, `render.yaml`)
and O3 (`.env.example`). Part of that was verifying A5's note that
`app/config.py` already "validated/normalized" the `database_url` field
so Neon's connection string can be pasted in largely as-is.

## What I found

`app/config.py`'s `_normalize_database_url` field validator (current
`main`, D1) only rewrites the URL **scheme** —
`postgresql://`/`postgres://` -> `postgresql+asyncpg://`. It does not
touch the query string.

Neon's dashboard issues connection strings in the form:

```
postgresql://<user>:<password>@<host>/<database>?sslmode=require&channel_binding=require
```

(confirmed against Neon's own SQLAlchemy connection guide,
neon.com/docs/guides/sqlalchemy, which shows exactly this
`sslmode=require&channel_binding=require` query string — that page
documents the sync/psycopg2 case, but the connection string Neon
issues is the same regardless of driver).

**The problem:** `asyncpg` (the driver SQLAlchemy's
`postgresql+asyncpg` dialect uses, per A5/D1) does not accept
`sslmode` or `channel_binding` as connection kwargs the way
`psycopg2` does. When SQLAlchemy's asyncpg dialect passes an unknown
query-string parameter straight through to `asyncpg.connect()`, the
call fails with:

```
TypeError: connect() got an unexpected keyword argument 'sslmode'
```

This is a well-documented asyncpg/SQLAlchemy interaction, not
something specific to this repo — search results turned up multiple
other projects hitting and fixing the exact same Neon+asyncpg+
SQLAlchemy combination this way. The commonly recommended fix is: the
`database_url` normalizer should strip `sslmode`/`channel_binding` from
the query string, and the engine should instead be created with
`connect_args={"ssl": True}` (or an equivalent explicit SSL context)
when the driver is asyncpg, rather than relying on the URL's query
string to carry SSL config for that driver.

## Why this didn't get caught yet

Both `_normalize_database_url` and `create_async_engine` are lazy —
they don't open a real connection at import time. The existing CI
"live import sanity check"
(`docs/agent-artifacts/devops/2026-09-26-restore-live-import-check.md`)
and local `import app.main` checks with a dummy
`DATABASE_URL=postgresql://user:password@localhost:5432/jarvis_ci`
(no query string at all) never exercise this path, so nothing so far
has actually attempted a real Neon connection through this code.

## Why I'm not fixing it myself

Per `.claude/AGENTS.md` Section 3.5, DevOps may not write or edit
anything under `app/**` — `app/config.py`'s validator is squarely
application code, not infra/deploy config. This needs an Architect
decision (does the fix belong in the `field_validator`, in
`app/database.py`'s engine construction, or both — A5 owns the
`database_url` contract) and then a gated Developer change, not a
DevOps patch.

## What O1a/O3 do in the meantime

The `.env.example` and `render.yaml` I've written flag this in
comments and point at this handoff request, but do not attempt to
work around it (e.g. I did not suggest manually hand-editing the
Neon-issued connection string as the primary fix — that's fragile,
operator-dependent, and exactly the kind of thing that should be
handled once in `config.py`, per A5's own stated intent that
`database_url` normalization happen "once in config.py rather than
every call site remembering to do it"). The full O1a/O3 work is not
blocked on this — Dockerfile/render.yaml/.env.example are complete and
usable — but a real Render+Neon deploy **will fail at first DB
access** (inside `app/main.py`'s `lifespan`, i.e. on service startup)
until this is fixed.

## Suggested fix (non-binding — Architect's call)

In `app/config.py`'s `_normalize_database_url`, after the existing
scheme rewrite, strip `sslmode` and `channel_binding` query params
when the target scheme is `postgresql+asyncpg://`, and have
`app/database.py`'s `create_async_engine(...)` call pass
`connect_args={"ssl": True}` (or equivalent) for that case so TLS is
still enforced — Neon requires TLS regardless of whether the query
string says so. Local dev Postgres (no `sslmode` in the URL at all,
per `.env.example`'s example value) is unaffected either way.

## Requires User Approval

None directly from this artifact — no irreversible action is proposed
here. The eventual code fix, once Architect/Developer take it up, is a
normal gated Developer change per Section 2.3 (needs an approved spec
+ explicit user build command), not something requiring separate
user approval beyond that existing gate.
