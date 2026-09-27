"""Async SQLAlchemy engine and session factory (D1).

Only an async engine lives here. `app/integrations/bank/plaid_connector.py`
builds its own small *synchronous* engine for the pgcrypto token
lookups, because `BankConnector`'s Protocol methods are synchronous
(matching Plaid's own blocking SDK) — see that module's docstring and
the D1-D4 status note for why that's kept separate rather than added
here.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    pass


# Neon requires TLS regardless of the URL's query string, but
# app/config.py's `_normalize_database_url` strips `sslmode`/
# `channel_binding` from the URL (asyncpg rejects them as connect
# kwargs) — so TLS is enforced explicitly here instead, and only when
# the original database_url actually requested it (per
# `settings.database_ssl`). Local dev Postgres (no sslmode in the URL)
# is unaffected.
_connect_args: dict[str, object] = {"ssl": True} if settings.database_ssl else {}

engine = create_async_engine(
    settings.database_url, echo=False, connect_args=_connect_args
)

async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session
