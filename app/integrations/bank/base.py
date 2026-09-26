"""BankConnector protocol + NormalizedTransaction (D4, per A2).

This is the only shape `app/domains/finance/service.py` ever sees.
`PlaidBankConnector` (plaid_connector.py) is the only implementation
for now; the Protocol exists so a future provider swap doesn't touch
the finance domain or service layer.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Protocol

from pydantic import BaseModel


class NormalizedTransaction(BaseModel):
    provider_transaction_id: str
    account_id: str
    amount: Decimal
    currency_code: str
    posted_date: date
    merchant_name: str | None = None
    pending: bool


class LinkedAccount(BaseModel):
    item_id: str
    access_token: str


class BankConnector(Protocol):
    def sync_transactions(self, item_id: str) -> list[NormalizedTransaction]: ...
    def exchange_public_token(self, public_token: str) -> LinkedAccount: ...
