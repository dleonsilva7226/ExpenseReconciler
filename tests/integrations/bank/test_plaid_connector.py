"""`PlaidBankConnector` tests (priority 2 of the Q1 ticket) -- the
item/account identity fix
(docs/agent-artifacts/developer/2026-09-20-item-account-identity-fix.md):
a single Plaid Item can cover multiple accounts, so a transaction must
be resolved to the correct *local* account via its own `account_id`,
not attributed to "the" account for the whole item; and an account
Plaid knows about but that was never linked locally must be
skipped-and-logged, not crash the sync or get misattributed.

No real Postgres/Plaid credentials exist here, so both the connector's
sync engine and its Plaid API client are faked: a `_FakeEngine`/
`_FakeConnection` pair stands in for `sqlalchemy.Engine` for the two
raw-SQL pgcrypto lookup methods, and a bare `Mock`/`SimpleNamespace`
stands in for the Plaid SDK response shape `sync_transactions` reads.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.integrations.bank.plaid_connector import PlaidBankConnector


class _FakeConnection:
    def __init__(self, result):
        self._result = result

    def execute(self, statement, params=None):
        return self._result

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeEngine:
    def __init__(self, result):
        self._result = result

    def connect(self):
        return _FakeConnection(self._result)


def _connector(client=None, sync_engine=None) -> PlaidBankConnector:
    return PlaidBankConnector(
        client=client or Mock(),
        sync_engine=sync_engine or Mock(),
        encryption_key="test-key",
    )


def _fake_plaid_txn(transaction_id, account_id, amount=10.0, merchant="Merchant", pending=False):
    return SimpleNamespace(
        transaction_id=transaction_id,
        account_id=account_id,
        amount=amount,
        iso_currency_code="USD",
        date=date(2026, 9, 20),
        merchant_name=merchant,
        pending=pending,
    )


# --- _get_decrypted_access_token --------------------------------------------


def test_get_decrypted_access_token_returns_token_when_row_found():
    fake_result = SimpleNamespace(first=lambda: SimpleNamespace(token="decrypted-access-token"))
    connector = _connector(sync_engine=_FakeEngine(fake_result))

    token = connector._get_decrypted_access_token("item-1")

    assert token == "decrypted-access-token"


def test_get_decrypted_access_token_raises_when_item_not_linked():
    fake_result = SimpleNamespace(first=lambda: None)
    connector = _connector(sync_engine=_FakeEngine(fake_result))

    with pytest.raises(ValueError, match="item-unknown"):
        connector._get_decrypted_access_token("item-unknown")


# --- _get_local_account_id_map ----------------------------------------------


def test_get_local_account_id_map_returns_every_account_under_the_item():
    """The A1 amendment this fix closes: an Item can map to more than
    one local CreditAccount row, keyed by (item_id, plaid_account_id)
    -- the map must contain all of them, not just one."""
    rows = [
        SimpleNamespace(id="local-uuid-checking", plaid_account_id="plaid-acct-checking"),
        SimpleNamespace(id="local-uuid-credit", plaid_account_id="plaid-acct-credit"),
    ]
    fake_result = SimpleNamespace(all=lambda: rows)
    connector = _connector(sync_engine=_FakeEngine(fake_result))

    account_map = connector._get_local_account_id_map("item-1")

    assert account_map == {
        "plaid-acct-checking": "local-uuid-checking",
        "plaid-acct-credit": "local-uuid-credit",
    }


def test_get_local_account_id_map_raises_when_item_not_linked():
    fake_result = SimpleNamespace(all=list)
    connector = _connector(sync_engine=_FakeEngine(fake_result))

    with pytest.raises(ValueError, match="item-unknown"):
        connector._get_local_account_id_map("item-unknown")


# --- sync_transactions: per-transaction account resolution ------------------


def test_sync_transactions_maps_each_transaction_to_its_own_correct_account(mocker):
    """The core regression guard: two accounts under one Item, two
    transactions each belonging to a *different* one of those accounts
    -- each must land on its own correct local account, not both on
    whichever account the old "one local account per item" lookup
    used to pick."""
    connector = _connector()
    mocker.patch.object(connector, "_get_decrypted_access_token", return_value="access-token")
    mocker.patch.object(
        connector,
        "_get_local_account_id_map",
        return_value={
            "plaid-acct-checking": "local-uuid-checking",
            "plaid-acct-credit": "local-uuid-credit",
        },
    )
    connector._client.transactions_sync = Mock(
        return_value=SimpleNamespace(
            added=[
                _fake_plaid_txn("txn-checking-1", "plaid-acct-checking", amount=42.00),
                _fake_plaid_txn("txn-credit-1", "plaid-acct-credit", amount=15.50),
            ],
            modified=[],
        )
    )

    result = connector.sync_transactions("item-1")

    by_id = {t.provider_transaction_id: t for t in result}
    assert len(result) == 2
    assert by_id["txn-checking-1"].account_id == "local-uuid-checking"
    assert by_id["txn-checking-1"].amount == Decimal("42.0")
    assert by_id["txn-credit-1"].account_id == "local-uuid-credit"
    assert by_id["txn-credit-1"].amount == Decimal("15.5")


def test_sync_transactions_skips_and_logs_transaction_for_unlinked_account(mocker, caplog):
    """A transaction for an account Plaid knows about (it's on the
    Item) but that was never linked locally must be skipped, not
    crash the sync and not get misattributed to some other local
    account."""
    connector = _connector()
    mocker.patch.object(connector, "_get_decrypted_access_token", return_value="access-token")
    mocker.patch.object(
        connector,
        "_get_local_account_id_map",
        return_value={"plaid-acct-checking": "local-uuid-checking"},
    )
    connector._client.transactions_sync = Mock(
        return_value=SimpleNamespace(
            added=[
                _fake_plaid_txn("txn-linked", "plaid-acct-checking"),
                _fake_plaid_txn("txn-unlinked", "plaid-acct-not-linked-locally"),
            ],
            modified=[],
        )
    )

    with caplog.at_level(logging.WARNING):
        result = connector.sync_transactions("item-1")

    assert [t.provider_transaction_id for t in result] == ["txn-linked"]
    assert any(
        "skipped" in record.message and "item-1" in record.message for record in caplog.records
    )


def test_sync_transactions_includes_both_added_and_modified():
    connector = _connector()
    connector._get_decrypted_access_token = Mock(return_value="access-token")
    connector._get_local_account_id_map = Mock(
        return_value={"plaid-acct-checking": "local-uuid-checking"}
    )
    connector._client.transactions_sync = Mock(
        return_value=SimpleNamespace(
            added=[_fake_plaid_txn("txn-new", "plaid-acct-checking")],
            modified=[
                _fake_plaid_txn("txn-now-posted", "plaid-acct-checking", pending=False)
            ],
        )
    )

    result = connector.sync_transactions("item-1")

    assert {t.provider_transaction_id for t in result} == {"txn-new", "txn-now-posted"}


def test_sync_transactions_returns_empty_list_when_all_transactions_unlinked():
    connector = _connector()
    connector._get_decrypted_access_token = Mock(return_value="access-token")
    connector._get_local_account_id_map = Mock(return_value={})
    connector._client.transactions_sync = Mock(
        return_value=SimpleNamespace(
            added=[_fake_plaid_txn("txn-1", "plaid-acct-orphan")],
            modified=[],
        )
    )

    result = connector.sync_transactions("item-1")

    assert result == []
