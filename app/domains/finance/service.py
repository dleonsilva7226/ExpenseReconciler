"""Finance domain service (D3, per A2/A1).

Only ever sees `NormalizedTransaction` — must not import anything
Plaid-specific (A2's core boundary between the bank-integration layer
and the finance domain).
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.finance.models import CreditAccount, FinancialTransaction
from app.integrations.bank.base import NormalizedTransaction


async def ingest_transactions(
    transactions: list[NormalizedTransaction],
    session: AsyncSession,
) -> None:
    """Upserts by `provider_transaction_id` (A1's idempotency rule):
    insert new rows, update amount/pending/etc. on ones that already
    exist (Plaid transitions a transaction from pending to posted
    using the same id, so this must be safe to call repeatedly).

    Caller owns the transaction boundary (commit/rollback) — this
    function only stages changes on the session.
    """
    if not transactions:
        return

    provider_ids = [t.provider_transaction_id for t in transactions]
    existing_rows = await session.execute(
        select(FinancialTransaction).where(
            FinancialTransaction.provider_transaction_id.in_(provider_ids)
        )
    )
    existing_by_id = {
        row.provider_transaction_id: row for row in existing_rows.scalars()
    }

    for txn in transactions:
        existing = existing_by_id.get(txn.provider_transaction_id)
        if existing is not None:
            existing.amount = txn.amount
            existing.currency_code = txn.currency_code
            existing.pending = txn.pending
            existing.merchant_name = txn.merchant_name
            existing.posted_date = txn.posted_date
        else:
            session.add(
                FinancialTransaction(
                    account_id=uuid.UUID(txn.account_id),
                    provider_transaction_id=txn.provider_transaction_id,
                    amount=txn.amount,
                    currency_code=txn.currency_code,
                    posted_date=txn.posted_date,
                    merchant_name=txn.merchant_name,
                    pending=txn.pending,
                )
            )


# --- Read paths (D5, per A3's agent tool-execution spec) -------------------
#
# Backing the three read-only tools in app/agent/tools.py. A3 names each
# tool's parameters/return shape but (as an implementation detail, not an
# architectural one) leaves the actual query bodies to Developer - written
# here rather than in tools.py so app/agent/** stays a thin wrapper over
# this domain's own read paths, per A3's module-boundary intent.


async def get_transactions(
    session: AsyncSession,
    start_date: date,
    end_date: date,
    account_id: str | None = None,
    category: str | None = None,
) -> list[FinancialTransaction]:
    """Transactions in `[start_date, end_date]`, optionally filtered by
    account and/or category. Read-only."""
    stmt = select(FinancialTransaction).where(
        FinancialTransaction.posted_date >= start_date,
        FinancialTransaction.posted_date <= end_date,
    )
    if account_id is not None:
        stmt = stmt.where(FinancialTransaction.account_id == uuid.UUID(account_id))
    if category is not None:
        stmt = stmt.where(FinancialTransaction.category == category)
    stmt = stmt.order_by(FinancialTransaction.posted_date.desc())

    result = await session.execute(stmt)
    return list(result.scalars())


async def get_account_summary(
    session: AsyncSession,
    account_id: str | None = None,
) -> list[dict]:
    """Balance/limit/utilization per `CreditAccount` (or every account
    if `account_id` is omitted). Read-only.

    NOTE (flagged in the D5 status note, not silently assumed): A1's
    schema has no stored balance column and A2's `BankConnector`
    Protocol has no live-balance fetch method, so `current_balance`
    here is computed as the sum of non-pending transaction amounts per
    account (Plaid's own convention: positive amounts are
    debits/purchases, negative are credits/refunds/payments) rather
    than read from a real-time Plaid balance call. This is a
    reasonable reading of A3's "balance ... per CreditAccount" given
    what's actually stored, not a redesign of the schema.
    """
    balance_subquery = (
        select(
            FinancialTransaction.account_id,
            func.coalesce(func.sum(FinancialTransaction.amount), 0).label("balance"),
        )
        .where(FinancialTransaction.pending.is_(False))
        .group_by(FinancialTransaction.account_id)
        .subquery()
    )

    stmt = select(CreditAccount, balance_subquery.c.balance).outerjoin(
        balance_subquery, CreditAccount.id == balance_subquery.c.account_id
    )
    if account_id is not None:
        stmt = stmt.where(CreditAccount.id == uuid.UUID(account_id))

    rows = await session.execute(stmt)

    summaries = []
    for account, balance in rows.all():
        balance = balance if balance is not None else Decimal(0)
        limit = account.credit_limit
        utilization = float(balance / limit) if limit else None
        summaries.append(
            {
                "account_id": str(account.id),
                "institution_name": account.institution_name,
                "account_name": account.account_name,
                "account_mask": account.account_mask,
                "current_balance": balance,
                "credit_limit": limit,
                "utilization": utilization,
            }
        )
    return summaries


async def get_spending_by_category(
    session: AsyncSession,
    start_date: date,
    end_date: date,
) -> list[dict]:
    """Aggregated spending totals per category over `[start_date,
    end_date]`. Read-only; excludes pending transactions."""
    stmt = (
        select(
            FinancialTransaction.category,
            func.coalesce(func.sum(FinancialTransaction.amount), 0).label("total"),
        )
        .where(
            FinancialTransaction.posted_date >= start_date,
            FinancialTransaction.posted_date <= end_date,
            FinancialTransaction.pending.is_(False),
        )
        .group_by(FinancialTransaction.category)
        .order_by(func.sum(FinancialTransaction.amount).desc())
    )

    rows = await session.execute(stmt)
    return [
        {"category": category or "uncategorized", "total": total}
        for category, total in rows.all()
    ]
