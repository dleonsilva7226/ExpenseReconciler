"""Finance domain models (D2, per A1's finance schema spec).

CreditAccount and FinancialTransaction, exactly as A1 defines them,
including the pgcrypto-encrypted `plaid_access_token_encrypted`
column (A1's "Token encryption" amendment).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    LargeBinary,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base


class UUIDPrimaryKeyMixin:
    """Shared by every model in this domain — a random UUID primary
    key, generated app-side. Pulled out once both models below needed
    the identical column; extend to future models (e.g. A4's
    DigestLog) rather than re-copying it."""

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )


class TimestampMixin:
    """Shared `created_at`/`updated_at` columns — same reasoning as
    `UUIDPrimaryKeyMixin` above."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CreditAccount(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "credit_accounts"
    __table_args__ = (
        # A1 amendment 2026-09-20: one Plaid Item (bank login) can cover
        # multiple accounts (e.g. checking + credit card at the same
        # bank) — identity is the (item, account) pair, not item alone.
        UniqueConstraint("plaid_item_id", "plaid_account_id", name="uq_credit_accounts_item_account"),
    )

    plaid_item_id: Mapped[str | None] = mapped_column(String, nullable=True)
    plaid_account_id: Mapped[str | None] = mapped_column(String, nullable=True)
    # pgcrypto-encrypted (pgp_sym_encrypt); written/read via raw SQL,
    # never through a plain ORM assignment — see A1's "Token
    # encryption" section and app/integrations/bank/plaid_connector.py.
    plaid_access_token_encrypted: Mapped[bytes | None] = mapped_column(
        LargeBinary, nullable=True
    )
    institution_name: Mapped[str] = mapped_column(String, nullable=False)
    account_name: Mapped[str] = mapped_column(String, nullable=False)
    account_mask: Mapped[str] = mapped_column(String(4), nullable=False)
    account_type: Mapped[str] = mapped_column(String, nullable=False)
    account_subtype: Mapped[str | None] = mapped_column(String, nullable=True)
    credit_limit: Mapped[Decimal | None] = mapped_column(Numeric(19, 4), nullable=True)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False)

    transactions: Mapped[list[FinancialTransaction]] = relationship(
        back_populates="account"
    )


class FinancialTransaction(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "financial_transactions"

    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("credit_accounts.id"), nullable=False
    )
    provider_transaction_id: Mapped[str] = mapped_column(
        String, unique=True, nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False)
    posted_date: Mapped[date] = mapped_column(Date, nullable=False)
    merchant_name: Mapped[str | None] = mapped_column(String, nullable=True)
    category: Mapped[str | None] = mapped_column(String, nullable=True)
    pending: Mapped[bool] = mapped_column(nullable=False, default=False)

    account: Mapped[CreditAccount] = relationship(back_populates="transactions")


class DigestLog(UUIDPrimaryKeyMixin, Base):
    """Weekly-digest idempotency table (D6, per A4's "Idempotency"
    section). A4 defines this table's columns itself — additive to
    this domain's schema, not part of A1's original spec — so only
    `id`/`sent_at`/`period_start`/`period_end` exist here; no
    `TimestampMixin`, since A4 doesn't call for created/updated
    tracking on this row.

    One row is written per digest actually sent. `period_end` is
    unique so a duplicate trigger (e.g. `cron-job.org` retrying, or a
    manual double-trigger while testing) can't race past the
    application-level check in `app/jobs/weekly_finance_audit.py` and
    insert two rows for the same week — a defensive DB-level backstop
    for the exact idempotency guarantee A4 asks for, not a schema
    change A4 didn't authorize.
    """

    __tablename__ = "digest_logs"
    __table_args__ = (
        UniqueConstraint("period_end", name="uq_digest_logs_period_end"),
    )

    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
