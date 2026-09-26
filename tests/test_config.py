"""D1 config tests (priority 5 of the Q1 ticket): `Settings.database_url`
normalization -- Neon issues a plain `postgresql://` URL, but the async
engine (`app/database.py`) needs the `asyncpg` driver scheme."""

from __future__ import annotations

import pytest

from app.config import Settings

_BASE_KWARGS = {
    "database_url": "postgresql://user:pass@localhost:5432/testdb",
    "plaid_client_id": "id",
    "plaid_secret": "secret",
    "telegram_bot_token": "token",
    "telegram_allowed_chat_id": 1,
    "telegram_webhook_secret_token": "secret",
    "admin_username": "admin",
    "admin_password": "password",
    "token_encryption_key": "key",
    "jobs_trigger_secret": "secret",
    "openai_api_key": "key",
    "gemini_api_key": "key",
}


def _settings_with(database_url: str) -> Settings:
    kwargs = {**_BASE_KWARGS, "database_url": database_url}
    return Settings(**kwargs)


@pytest.mark.parametrize(
    "raw_url, expected",
    [
        (
            "postgresql://user:pass@ep-example.neon.tech/db",
            "postgresql+asyncpg://user:pass@ep-example.neon.tech/db",
        ),
        (
            "postgres://user:pass@ep-example.neon.tech/db",
            "postgresql+asyncpg://user:pass@ep-example.neon.tech/db",
        ),
    ],
)
def test_database_url_normalizes_plain_postgres_schemes(raw_url, expected):
    settings = _settings_with(raw_url)
    assert settings.database_url == expected


def test_database_url_already_using_asyncpg_scheme_is_left_alone():
    already_normalized = "postgresql+asyncpg://user:pass@host/db"
    settings = _settings_with(already_normalized)
    assert settings.database_url == already_normalized


def test_database_url_unrelated_scheme_is_left_alone():
    # Guards against the validator being overly broad and mangling a
    # scheme it has no business touching (e.g. local sqlite in some
    # future dev-mode override).
    sqlite_url = "sqlite+aiosqlite:///./local.db"
    settings = _settings_with(sqlite_url)
    assert settings.database_url == sqlite_url
