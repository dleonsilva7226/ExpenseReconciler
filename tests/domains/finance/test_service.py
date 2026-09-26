"""D3 `ingest_transactions` tests (priority 1 of the Q1 ticket).

This is the safety-critical path flagged by the ticket: idempotent
upsert on `provider_transaction_id` so a duplicate/retried ingest
(a re-delivered Plaid webhook, a re-run digest, the connector's own
"cursor always empty, refetch everything" limitation -- see
docs/agent-artifacts/developer/2026-09-20-d1-d4-bootstrap-status.md's
assumption #3) never double-counts a transaction.

`AsyncSession` is faked rather than backed by a real engine: the
function under test only calls `session.execute(select(...))` and
`session.add(...)`, so a fake that records/serves exactly those two
calls exercises the real upsert branching logic
(`app/domains/finance/service.py`) without needing Postgres.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from app.domains.finance.service import ingest_transactions
from app.integrations.bank.base import NormalizedTransaction


class _FakeScalars:
    def __init__(self, rows):
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)


class _FakeSelectResult:
    """Stands in for the `Result` object `session.execute(select(...))`
    returns -- only `.scalars()` is used by the code under test."""

    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _FakeScalars(self._rows)


def _make_session(existing_rows=()):
    session = SimpleNamespace()
    session.execute = AsyncMock(return_value=_FakeSelectResult(list(existing_rows)))
    # `session.add` is sync in real SQLAlchemy (it only stages the
    # object) -- a plain Mock here means a test that mistakenly awaited
    # it would fail loudly instead of silently passing.
    session.add = Mock()
    return session


def _txn(provider_transaction_id="txn-1", account_id=None, amount="12.34", pending=True):
    return NormalizedTransaction(
        provider_transaction_id=provider_transaction_id,
        account_id=account_id or "11111111-1111-1111-1111-111111111111",
        amount=Decimal(amount),
        currency_code="USD",
        posted_date=date(2026, 9, 20),
        merchant_name="Coffee Shop",
        pending=pending,
    )


async def test_ingest_transactions_empty_list_does_nothing():
    session = _make_session()
    await ingest_transactions([], session)
    session.execute.assert_not_called()
    session.add.assert_not_called()


async def test_ingest_transactions_inserts_new_transaction():
    session = _make_session(existing_rows=())
    txn = _txn(provider_transaction_id="new-txn", amount="9.99", pending=True)

    await ingest_transactions([txn], session)

    session.add.assert_called_once()
    (inserted,), _ = session.add.call_args
    assert inserted.provider_transaction_id == "new-txn"
    assert inserted.amount == Decimal("9.99")
    assert inserted.pending is True
    assert str(inserted.account_id) == txn.account_id


async def test_ingest_transactions_updates_existing_transaction_not_a_duplicate_insert():
    """The core idempotency guarantee: re-ingesting a transaction that
    already exists (matched by `provider_transaction_id`) must update
    the existing row's mutable fields in place, and must NOT insert a
    second row -- Plaid re-sends the same id as a transaction moves
    from pending to posted, and a naive insert-or-fail (or an insert
    that doesn't check first) would double-count it."""
    existing = SimpleNamespace(
        provider_transaction_id="dup-txn",
        amount=Decimal("5.00"),
        currency_code="USD",
        pending=True,
        merchant_name="Old Merchant Name",
        posted_date=date(2026, 9, 18),
    )
    session = _make_session(existing_rows=[existing])

    # Distinct merchant/date/pending from `existing` so we can confirm
    # the update path actually mutates every mutable field service.py
    # documents, not just amount.
    updated_txn = NormalizedTransaction(
        provider_transaction_id="dup-txn",
        account_id="11111111-1111-1111-1111-111111111111",
        amount=Decimal("5.00"),
        currency_code="USD",
        posted_date=date(2026, 9, 19),
        merchant_name="New Merchant Name",
        pending=False,
    )

    await ingest_transactions([updated_txn], session)

    session.add.assert_not_called()
    assert existing.amount == Decimal("5.00")
    assert existing.pending is False
    assert existing.merchant_name == "New Merchant Name"
    assert existing.posted_date == date(2026, 9, 19)


async def test_ingest_transactions_mixed_batch_inserts_new_and_updates_existing():
    existing = SimpleNamespace(
        provider_transaction_id="already-there",
        amount=Decimal("1.00"),
        currency_code="USD",
        pending=True,
        merchant_name="Merchant A",
        posted_date=date(2026, 9, 1),
    )
    session = _make_session(existing_rows=[existing])

    new_txn = _txn(provider_transaction_id="brand-new", amount="2.00")
    update_txn = NormalizedTransaction(
        provider_transaction_id="already-there",
        account_id="11111111-1111-1111-1111-111111111111",
        amount=Decimal("1.50"),
        currency_code="USD",
        posted_date=date(2026, 9, 2),
        merchant_name="Merchant A",
        pending=False,
    )

    await ingest_transactions([new_txn, update_txn], session)

    # Exactly one insert (the brand-new transaction) ...
    session.add.assert_called_once()
    (inserted,), _ = session.add.call_args
    assert inserted.provider_transaction_id == "brand-new"

    # ... and the existing row was updated in place, not re-inserted.
    assert existing.amount == Decimal("1.50")
    assert existing.pending is False


async def test_ingest_transactions_queries_by_provider_transaction_id_only_once():
    """Guards against an accidental N+1: one batched SELECT for all
    incoming ids, not one query per transaction."""
    session = _make_session(existing_rows=())
    txns = [_txn(provider_transaction_id=f"txn-{i}") for i in range(5)]

    await ingest_transactions(txns, session)

    assert session.execute.await_count == 1
