"""App configuration (D1, per A5's config-and-secrets contract).

`settings` is a module-level singleton, imported wherever config is
needed. All fields are required except `environment` and `plaid_env`;
in production, values come from Render's environment variable
dashboard, never committed anywhere.
"""

from typing import Any, Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Query params Neon's connection strings carry (`sslmode`, `channel_binding`)
# that `psycopg2` understands but SQLAlchemy's `asyncpg` dialect passes
# straight through to `asyncpg.connect()`, which rejects them as unknown
# connect kwargs (see the 2026-09-27 Neon/asyncpg handoff request).
_ASYNCPG_INCOMPATIBLE_QUERY_PARAMS = {"sslmode", "channel_binding"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    environment: Literal["development", "production"] = "development"

    # Database (Neon in production, per R5)
    database_url: str

    # Whether app/database.py must enforce TLS explicitly via
    # `connect_args` instead of relying on the URL's query string.
    # Derived automatically from the raw `database_url` below (before
    # `_normalize_database_url` strips `sslmode`/`channel_binding` from
    # it) — not meant to be set directly, though an explicit
    # `DATABASE_SSL` env var can still force it if ever needed.
    database_ssl: bool = False

    # Plaid (per A2, R1)
    plaid_client_id: str
    plaid_secret: str
    plaid_env: Literal["sandbox", "production"] = "sandbox"

    # Telegram (per A2)
    telegram_bot_token: str
    telegram_allowed_chat_id: int
    telegram_webhook_secret_token: str

    # Admin UI / account linking (per A2a)
    admin_username: str
    admin_password: str

    # Token encryption (per A1's pgcrypto amendment)
    token_encryption_key: str

    # Weekly digest trigger (per R4 — external cron, no APScheduler)
    jobs_trigger_secret: str

    # AI providers (per PLAN.md)
    openai_api_key: str
    gemini_api_key: str

    @model_validator(mode="before")
    @classmethod
    def _detect_database_ssl(cls, data: Any) -> Any:
        """Record whether the *raw* database_url requested sslmode/
        channel_binding, before _normalize_database_url strips them."""
        if isinstance(data, dict) and "database_ssl" not in data:
            raw_url = data.get("database_url")
            if isinstance(raw_url, str):
                params = {k for k, _ in parse_qsl(urlsplit(raw_url).query)}
                if params & _ASYNCPG_INCOMPATIBLE_QUERY_PARAMS:
                    data["database_ssl"] = True
        return data

    @field_validator("database_url")
    @classmethod
    def _normalize_database_url(cls, value: str) -> str:
        """Neon issues a plain postgresql:// URL; SQLAlchemy's async
        engine needs the asyncpg driver scheme (A5's note for D1).

        Neon's URL also carries `sslmode`/`channel_binding` query params
        that asyncpg rejects as unknown connect kwargs at engine-connect
        time. Strip them once here; app/database.py enforces TLS
        explicitly via connect_args instead, using `database_ssl` above.
        """
        for plain_scheme in ("postgresql://", "postgres://"):
            if value.startswith(plain_scheme):
                value = "postgresql+asyncpg://" + value[len(plain_scheme) :]
                break

        if value.startswith("postgresql+asyncpg://"):
            parts = urlsplit(value)
            kept_params = [
                (k, v)
                for k, v in parse_qsl(parts.query, keep_blank_values=True)
                if k not in _ASYNCPG_INCOMPATIBLE_QUERY_PARAMS
            ]
            value = urlunsplit(parts._replace(query=urlencode(kept_params)))

        return value


settings = Settings()
