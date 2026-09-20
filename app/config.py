"""App configuration (D1, per A5's config-and-secrets contract).

`settings` is a module-level singleton, imported wherever config is
needed. All fields are required except `environment` and `plaid_env`;
in production, values come from Render's environment variable
dashboard, never committed anywhere.
"""

from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    environment: Literal["development", "production"] = "development"

    # Database (Neon in production, per R5)
    database_url: str

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

    @field_validator("database_url")
    @classmethod
    def _normalize_database_url(cls, value: str) -> str:
        """Neon issues a plain postgresql:// URL; SQLAlchemy's async
        engine needs the asyncpg driver scheme (A5's note for D1)."""
        for plain_scheme in ("postgresql://", "postgres://"):
            if value.startswith(plain_scheme):
                return "postgresql+asyncpg://" + value[len(plain_scheme) :]
        return value


settings = Settings()
