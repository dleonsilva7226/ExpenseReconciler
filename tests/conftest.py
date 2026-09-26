"""Shared pytest fixtures for the D1-D4 test suite (ticket Q1).

Env vars for `app.config.Settings` are set here, at collection time,
*before* any `app.*` module is imported anywhere in the suite --
`app.config.settings` is a module-level singleton built at import time
(see `app/config.py`), so it must see these values on its first
import, not later.

No live Plaid/Telegram/Postgres credentials exist in this environment.
Every value below is generated at collection time (`secrets.token_hex`
et al.) rather than typed out as a static string, so nothing
credential-shaped sits in git history for a secret scanner to flag as
a false positive (see
docs/agent-artifacts/qa/2026-09-27-fix-secret-scan-fixtures.md) --
they're still just syntactically-valid dummies used only so the app's
settings/object graph (and things built from it, like
`app/gateway/router.py`'s module-level Plaid client and sync engine)
can construct without contacting a real service. Tests that exercise
behavior gated behind a real network/DB call mock that call directly
rather than relying on these values being "real."
"""

from __future__ import annotations

import os
import secrets
from typing import Self

_ENV_DEFAULTS = {
    # DSN shape is structurally required (asyncpg needs a real-looking
    # postgres URL); only the user:pass segment is credential-shaped,
    # so only that segment is randomized.
    "DATABASE_URL": (
        f"postgresql://{secrets.token_hex(8)}:{secrets.token_hex(8)}"
        "@localhost:5432/testdb"
    ),
    "PLAID_CLIENT_ID": secrets.token_hex(16),
    "PLAID_SECRET": secrets.token_hex(16),
    "PLAID_ENV": "sandbox",  # not a credential -- Plaid's own env-name literal
    "TELEGRAM_BOT_TOKEN": secrets.token_hex(16),
    # Must stay numeric-looking (Settings declares it `int`); random
    # 9-digit value instead of a static literal.
    "TELEGRAM_ALLOWED_CHAT_ID": str(secrets.randbelow(900_000_000) + 100_000_000),
    "TELEGRAM_WEBHOOK_SECRET_TOKEN": secrets.token_hex(16),
    "ADMIN_USERNAME": secrets.token_hex(16),
    "ADMIN_PASSWORD": secrets.token_hex(16),
    "TOKEN_ENCRYPTION_KEY": secrets.token_hex(16),
    "JOBS_TRIGGER_SECRET": secrets.token_hex(16),
    "OPENAI_API_KEY": secrets.token_hex(16),
    "GEMINI_API_KEY": secrets.token_hex(16),
}

for _name, _value in _ENV_DEFAULTS.items():
    os.environ.setdefault(_name, _value)

import pytest


@pytest.fixture
def admin_auth() -> tuple[str, str]:
    """(username, password) matching this test session's env -- pass as
    `auth=admin_auth` to TestClient calls against Basic-Auth-gated
    routes."""
    from app.config import settings

    return (settings.admin_username, settings.admin_password)


@pytest.fixture
def wrong_auth() -> tuple[str, str]:
    """A syntactically-valid but definitely-wrong (username, password)
    pair for "bad credentials, expect 401" tests -- pass as
    `auth=wrong_auth` to TestClient calls against Basic-Auth-gated
    routes. Randomized (8 random bytes each, vs. `admin_auth`'s 16) so
    no static credential-shaped string literal sits in a test's source
    -- the actual values here are, and always were, arbitrary; what's
    tested is only that they don't match the real admin credentials,
    which they can't by construction (different length)."""
    return (secrets.token_hex(8), secrets.token_hex(8))


@pytest.fixture
def wrong_webhook_secret() -> str:
    """A syntactically-valid but definitely-wrong webhook secret-token
    value, for the same reason and by the same construction as
    `wrong_auth` above (shorter than the real
    `TELEGRAM_WEBHOOK_SECRET_TOKEN`, so it can't collide with it)."""
    return secrets.token_hex(8)


@pytest.fixture
def client():
    """A TestClient built *without* running the app's lifespan (no
    `with` block), matching how this repo's Developer already verified
    D4's routes -- see
    docs/agent-artifacts/developer/2026-09-20-d1-d4-bootstrap-status.md.
    The lifespan does a real `CREATE EXTENSION`/`create_all` against
    Postgres, which isn't available here; skipping it means these
    tests exercise real route/dependency logic without a live DB,
    which is fine for every route this suite touches (none of them
    need the ORM's declared tables to already exist -- the ones that
    touch the DB at all use raw SQL via a mocked session)."""
    from fastapi.testclient import TestClient

    import app.main as main_module

    return TestClient(main_module.app)


class FakeAsyncSession:
    """A minimal stand-in for `AsyncSession` used as an async context
    manager, e.g. `async with async_session_factory() as session: ...`.
    Records every `execute()` call (statement + params) so tests can
    assert on what was staged, without a real database connection."""

    def __init__(self) -> None:
        self.executed: list[tuple[object, object]] = []
        self.committed = False

    async def execute(self, statement, params=None):
        self.executed.append((statement, params))

    async def commit(self) -> None:
        self.committed = True

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


@pytest.fixture
def fake_async_session():
    """A single `FakeAsyncSession` instance, plus a zero-arg factory
    callable returning it -- matches the shape of
    `app.database.async_session_factory` (`async_session_factory()`
    returns something usable as `async with ... as session`), so it
    can be monkeypatched in directly wherever a route captures that
    name at import time (e.g. `app.gateway.router`)."""
    session = FakeAsyncSession()
    return session


@pytest.fixture
def fake_async_session_factory(fake_async_session):
    return lambda: fake_async_session
