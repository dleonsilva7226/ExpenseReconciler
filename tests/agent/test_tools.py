"""`app/agent/tools.py` tests (D5, per A3): each of the three
read-only tools must call the right `finance_service` read path with
the right arguments/keyword names, and return the shape promised by
its own `Tool` schema. Each tool opens its own short-lived session
(A3: "invoked directly by the agent loop rather than from a request
that already has one open") -- faked here rather than backed by a
real database.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import app.agent.tools as tools_module


class _FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.fixture(autouse=True)
def fake_session_factory(monkeypatch):
    """Every tool opens `async_session_factory()` itself -- patched
    module-wide so no test here needs a real database connection."""
    monkeypatch.setattr(tools_module, "async_session_factory", lambda: _FakeSession())


def _txn(**overrides):
    defaults = {
        "id": "11111111-1111-1111-1111-111111111111",
        "account_id": "22222222-2222-2222-2222-222222222222",
        "provider_transaction_id": "txn-1",
        "amount": Decimal("12.34"),
        "currency_code": "USD",
        "posted_date": date(2026, 9, 20),
        "merchant_name": "Coffee Shop",
        "category": "dining",
        "pending": False,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# --- get_transactions --------------------------------------------------------


async def test_get_transactions_parses_dates_and_passes_through_filters(monkeypatch):
    fake_get_transactions = AsyncMock(return_value=[_txn()])
    monkeypatch.setattr(tools_module.finance_service, "get_transactions", fake_get_transactions)

    result = await tools_module.get_transactions(
        start_date="2026-09-01",
        end_date="2026-09-26",
        account_id="acct-1",
        category="dining",
    )

    fake_get_transactions.assert_awaited_once()
    _, kwargs = fake_get_transactions.call_args
    assert kwargs["start_date"] == date(2026, 9, 1)
    assert kwargs["end_date"] == date(2026, 9, 26)
    assert kwargs["account_id"] == "acct-1"
    assert kwargs["category"] == "dining"

    assert result == [
        {
            "id": "11111111-1111-1111-1111-111111111111",
            "account_id": "22222222-2222-2222-2222-222222222222",
            "provider_transaction_id": "txn-1",
            "amount": Decimal("12.34"),
            "currency_code": "USD",
            "posted_date": "2026-09-20",
            "merchant_name": "Coffee Shop",
            "category": "dining",
            "pending": False,
        }
    ]


async def test_get_transactions_defaults_account_and_category_to_none(monkeypatch):
    fake_get_transactions = AsyncMock(return_value=[])
    monkeypatch.setattr(tools_module.finance_service, "get_transactions", fake_get_transactions)

    await tools_module.get_transactions(start_date="2026-09-01", end_date="2026-09-26")

    _, kwargs = fake_get_transactions.call_args
    assert kwargs["account_id"] is None
    assert kwargs["category"] is None


# --- get_account_summary -----------------------------------------------------


async def test_get_account_summary_passes_through_finance_service_result(monkeypatch):
    fake_summary = [{"account_id": "acct-1", "current_balance": Decimal("10.00")}]
    fake_get_account_summary = AsyncMock(return_value=fake_summary)
    monkeypatch.setattr(
        tools_module.finance_service, "get_account_summary", fake_get_account_summary
    )

    result = await tools_module.get_account_summary(account_id="acct-1")

    fake_get_account_summary.assert_awaited_once()
    _, kwargs = fake_get_account_summary.call_args
    assert kwargs["account_id"] == "acct-1"
    assert result is fake_summary


async def test_get_account_summary_defaults_account_id_to_none(monkeypatch):
    fake_get_account_summary = AsyncMock(return_value=[])
    monkeypatch.setattr(
        tools_module.finance_service, "get_account_summary", fake_get_account_summary
    )

    await tools_module.get_account_summary()

    _, kwargs = fake_get_account_summary.call_args
    assert kwargs["account_id"] is None


# --- get_spending_by_category ------------------------------------------------


async def test_get_spending_by_category_parses_dates_and_passes_through_result(monkeypatch):
    fake_result = [{"category": "dining", "total": Decimal("42.00")}]
    fake_get_spending = AsyncMock(return_value=fake_result)
    monkeypatch.setattr(
        tools_module.finance_service, "get_spending_by_category", fake_get_spending
    )

    result = await tools_module.get_spending_by_category(
        start_date="2026-09-01", end_date="2026-09-26"
    )

    fake_get_spending.assert_awaited_once()
    _, kwargs = fake_get_spending.call_args
    assert kwargs["start_date"] == date(2026, 9, 1)
    assert kwargs["end_date"] == date(2026, 9, 26)
    assert result is fake_result


# --- Tool schema / TOOLS <-> TOOL_IMPLEMENTATIONS consistency ---------------


def test_tools_list_names_match_tool_implementations_keys():
    assert {tool.name for tool in tools_module.TOOLS} == set(
        tools_module.TOOL_IMPLEMENTATIONS.keys()
    )


def test_get_transactions_tool_schema_requires_start_and_end_date():
    assert tools_module.GET_TRANSACTIONS_TOOL.parameters["required"] == [
        "start_date",
        "end_date",
    ]


def test_get_account_summary_tool_schema_has_no_required_fields():
    assert tools_module.GET_ACCOUNT_SUMMARY_TOOL.parameters["required"] == []


def test_get_spending_by_category_tool_schema_requires_start_and_end_date():
    assert tools_module.GET_SPENDING_BY_CATEGORY_TOOL.parameters["required"] == [
        "start_date",
        "end_date",
    ]
