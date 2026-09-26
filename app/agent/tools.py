"""Read-only agent tools (D5, per A3).

Three fixed, named, parameterized query functions over
`app/domains/finance/service.py`'s read paths - deliberately **not** a
text-to-SQL or arbitrary-query tool. That's an explicit, user-approved
security decision recorded in A3: an LLM-driven arbitrary-SQL tool
against a database holding real financial data and (per A1) an
encrypted secret column is not an acceptable risk for the value it'd
add here. Do not add one.

Each function below is what `engine.py`'s tool loop actually calls
(`TOOL_IMPLEMENTATIONS`), paired with a `Tool` schema (`TOOLS`) that
the provider adapters advertise to the model. Each opens and closes
its own short-lived session, since these are invoked directly by the
agent loop rather than from a request that already has one open.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from app.agent.providers.base import Tool
from app.database import async_session_factory
from app.domains.finance import service as finance_service
from app.domains.finance.models import FinancialTransaction


def _transaction_to_dict(txn: FinancialTransaction) -> dict[str, Any]:
    return {
        "id": str(txn.id),
        "account_id": str(txn.account_id),
        "provider_transaction_id": txn.provider_transaction_id,
        "amount": txn.amount,
        "currency_code": txn.currency_code,
        "posted_date": txn.posted_date.isoformat(),
        "merchant_name": txn.merchant_name,
        "category": txn.category,
        "pending": txn.pending,
    }


async def get_transactions(
    start_date: str,
    end_date: str,
    account_id: str | None = None,
    category: str | None = None,
) -> list[dict[str, Any]]:
    """List transactions in a date range, optionally filtered by
    account or category. Read-only."""
    async with async_session_factory() as session:
        rows = await finance_service.get_transactions(
            session,
            start_date=date.fromisoformat(start_date),
            end_date=date.fromisoformat(end_date),
            account_id=account_id,
            category=category,
        )
        return [_transaction_to_dict(row) for row in rows]


async def get_account_summary(account_id: str | None = None) -> list[dict[str, Any]]:
    """Balance/limit/utilization per account, or every account if
    `account_id` is omitted. Read-only."""
    async with async_session_factory() as session:
        return await finance_service.get_account_summary(session, account_id=account_id)


async def get_spending_by_category(start_date: str, end_date: str) -> list[dict[str, Any]]:
    """Aggregated spending totals per category over a date range.
    Read-only."""
    async with async_session_factory() as session:
        return await finance_service.get_spending_by_category(
            session,
            start_date=date.fromisoformat(start_date),
            end_date=date.fromisoformat(end_date),
        )


GET_TRANSACTIONS_TOOL = Tool(
    name="get_transactions",
    description=(
        "List financial transactions in a date range, optionally filtered "
        "by account or category. Read-only."
    ),
    parameters={
        "type": "object",
        "properties": {
            "start_date": {
                "type": "string",
                "format": "date",
                "description": "ISO 8601 date, e.g. 2026-09-01",
            },
            "end_date": {
                "type": "string",
                "format": "date",
                "description": "ISO 8601 date, e.g. 2026-09-26",
            },
            "account_id": {
                "type": "string",
                "description": "Optional CreditAccount UUID to filter by",
            },
            "category": {
                "type": "string",
                "description": "Optional category to filter by",
            },
        },
        "required": ["start_date", "end_date"],
    },
)

GET_ACCOUNT_SUMMARY_TOOL = Tool(
    name="get_account_summary",
    description=(
        "Get balance, credit limit, and utilization per credit account, "
        "or for all accounts if account_id is omitted. Read-only."
    ),
    parameters={
        "type": "object",
        "properties": {
            "account_id": {
                "type": "string",
                "description": "Optional CreditAccount UUID",
            },
        },
        "required": [],
    },
)

GET_SPENDING_BY_CATEGORY_TOOL = Tool(
    name="get_spending_by_category",
    description="Get aggregated spending totals per category over a date range. Read-only.",
    parameters={
        "type": "object",
        "properties": {
            "start_date": {
                "type": "string",
                "format": "date",
                "description": "ISO 8601 date, e.g. 2026-09-01",
            },
            "end_date": {
                "type": "string",
                "format": "date",
                "description": "ISO 8601 date, e.g. 2026-09-26",
            },
        },
        "required": ["start_date", "end_date"],
    },
)

TOOLS: list[Tool] = [
    GET_TRANSACTIONS_TOOL,
    GET_ACCOUNT_SUMMARY_TOOL,
    GET_SPENDING_BY_CATEGORY_TOOL,
]

TOOL_IMPLEMENTATIONS = {
    "get_transactions": get_transactions,
    "get_account_summary": get_account_summary,
    "get_spending_by_category": get_spending_by_category,
}
