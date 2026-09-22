"""Finance domain service (D3, per A2/A1).

Only ever sees `NormalizedTransaction` — must not import anything
Plaid-specific (A2's core boundary between the bank-integration layer
and the finance domain).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.finance.models import FinancialTransaction
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
