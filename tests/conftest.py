"""Shared pytest fixtures for the D1-D4 test suite (ticket Q1).

Env vars for `app.config.Settings` are set here, at collection time,
*before* any `app.*` module is imported anywhere in the suite --
`app.config.settings` is a module-level singleton built at import time
(see `app/config.py`), so it must see these values on its first
import, not later.

No live Plaid/Telegram/Postgres credentials exist in this environment.
Every value below is a syntactically-valid dummy used only so the
app's settings/object graph (and things built from it, like
`app/gateway/router.py`'s module-level Plaid client and sync engine)
can construct without contacting a real service. Tests that exercise
behavior gated behind a real network/DB call mock that call directly
rather than relying on these values being "real."
"""

from __future__ import annotations

import os
from typing import Self

_ENV_DEFAULTS = {
    "DATABASE_URL": "postgresql://user:pass@localhost:5432/testdb",
    "PLAID_CLIENT_ID": "test-plaid-client-id",
    "PLAID_SECRET": "test-plaid-secret",
    "PLAID_ENV": "sandbox",
    "TELEGRAM_BOT_TOKEN": "test-telegram-bot-token",
    "TELEGRAM_ALLOWED_CHAT_ID": "555000111",
    "TELEGRAM_WEBHOOK_SECRET_TOKEN": "test-telegram-webhook-secret",
    "ADMIN_USERNAME": "test-admin",
    "ADMIN_PASSWORD": "test-admin-password",
    "TOKEN_ENCRYPTION_KEY": "test-token-encryption-key",
    "JOBS_TRIGGER_SECRET": "test-jobs-trigger-secret",
    "OPENAI_API_KEY": "test-openai-key",
    "GEMINI_API_KEY": "test-gemini-key",
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
