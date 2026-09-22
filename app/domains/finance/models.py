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


class CreditAccount(Base):
    __tablename__ = "credit_accounts"
    __table_args__ = (
        # A1 amendment 2026-09-20: one Plaid Item (bank login) can cover
        # multiple accounts (e.g. checking + credit card at the same
        # bank) — identity is the (item, account) pair, not item alone.
        UniqueConstraint("plaid_item_id", "plaid_account_id", name="uq_credit_accounts_item_account"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    transactions: Mapped[list[FinancialTransaction]] = relationship(
        back_populates="account"
    )


class FinancialTransaction(Base):
    __tablename__ = "financial_transactions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    account: Mapped[CreditAccount] = relationship(back_populates="transactions")
