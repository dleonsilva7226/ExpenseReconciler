"""PlaidBankConnector — the only BankConnector implementation (D4, per A2/R1).

Assumption/deviation, flagged in the D1-D4 status note: `BankConnector`'s
Protocol methods are synchronous (matching Plaid's own blocking Python
SDK), so this module builds a small *dedicated synchronous* SQLAlchemy
engine for the two pgcrypto encrypt/decrypt lookups A1 requires,
separate from `app/database.py`'s primary async engine used everywhere
else in the app. This keeps the second connection path contained
entirely within the bank-integration layer rather than spilling into
D1's bootstrap module.
"""

from __future__ import annotations

import logging
from decimal import Decimal

import plaid
from plaid.api import plaid_api
from plaid.model.item_public_token_exchange_request import (
    ItemPublicTokenExchangeRequest,
)
from plaid.model.transactions_sync_request import TransactionsSyncRequest
from sqlalchemy import Engine, create_engine, text

from app.config import Settings
from app.integrations.bank.base import (
    BankConnector,
    LinkedAccount,
    NormalizedTransaction,
)

_PLAID_ENV_HOSTS = {
    "sandbox": plaid.Environment.Sandbox,
    "production": plaid.Environment.Production,
}


def build_plaid_client(settings: Settings) -> plaid_api.PlaidApi:
    configuration = plaid.Configuration(
        host=_PLAID_ENV_HOSTS[settings.plaid_env],
        api_key={
            "clientId": settings.plaid_client_id,
            "secret": settings.plaid_secret,
        },
    )
    return plaid_api.PlaidApi(plaid.ApiClient(configuration))


def build_sync_engine(settings: Settings) -> Engine:
    """See module docstring: a dedicated sync engine for the pgcrypto
    lookups below, since Plaid's SDK (and this Protocol) are sync."""
    sync_url = settings.database_url.replace(
        "postgresql+asyncpg://", "postgresql+psycopg2://", 1
    )
    return create_engine(sync_url)


class PlaidBankConnector(BankConnector):
    def __init__(self, client: plaid_api.PlaidApi, sync_engine: Engine, encryption_key: str) -> None:
        self._client = client
        self._engine = sync_engine
        self._encryption_key = encryption_key

    def exchange_public_token(self, public_token: str) -> LinkedAccount:
        response = self._client.item_public_token_exchange(
            ItemPublicTokenExchangeRequest(public_token=public_token)
        )
        return LinkedAccount(item_id=response.item_id, access_token=response.access_token)

    def sync_transactions(self, item_id: str) -> list[NormalizedTransaction]:
        access_token = self._get_decrypted_access_token(item_id)
        # A1 amendment 2026-09-20 ("Item vs. account identity"): an
        # item can now map to several local accounts, so resolve a
        # plaid_account_id -> local id map once per call instead of a
        # single local account for the whole item.
        account_id_map = self._get_local_account_id_map(item_id)

        # KNOWN LIMITATION (flagged in status note): passing cursor=""
        # every call re-fetches full history instead of an incremental
        # sync. finance.service's idempotent upsert makes this safe,
        # just wasteful. A1 has no cursor-storage column yet; adding
        # one (e.g. `plaid_sync_cursor` on CreditAccount) is a
        # follow-up ticket, not solved here.
        request = TransactionsSyncRequest(access_token=access_token, cursor="")
        response = self._client.transactions_sync(request)

        transactions: list[NormalizedTransaction] = []
        skipped = 0
        for txn in list(response.added) + list(response.modified):
            local_account_id = account_id_map.get(txn.account_id)
            if local_account_id is None:
                # Plaid knows this account (it's on the Item) but it
                # was never linked locally — skip rather than crash or
                # misattribute the transaction to the wrong account.
                skipped += 1
                continue
            transactions.append(
                NormalizedTransaction(
                    provider_transaction_id=txn.transaction_id,
                    account_id=local_account_id,
                    amount=Decimal(str(txn.amount)),
                    currency_code=txn.iso_currency_code or "USD",
                    posted_date=txn.date,
                    merchant_name=txn.merchant_name,
                    pending=txn.pending,
                )
            )
        if skipped:
            logging.getLogger(__name__).warning(
                "sync_transactions: skipped %d transaction(s) for item_id=%r "
                "with no matching local CreditAccount",
                skipped,
                item_id,
            )
        return transactions

    def _get_decrypted_access_token(self, item_id: str) -> str:
        with self._engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT pgp_sym_decrypt(plaid_access_token_encrypted, :key)::text AS token "
                    "FROM credit_accounts WHERE plaid_item_id = :item_id"
                ),
                {"key": self._encryption_key, "item_id": item_id},
            ).first()
        if row is None or row.token is None:
            raise ValueError(f"No linked account found for Plaid item_id={item_id!r}")
        return row.token

    def _get_local_account_id_map(self, item_id: str) -> dict[str, str]:
        """plaid_account_id -> local CreditAccount.id, for every local
        account linked under this item (A1 amendment 2026-09-20: an
        item can map to more than one local account)."""
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT id, plaid_account_id FROM credit_accounts "
                    "WHERE plaid_item_id = :item_id"
                ),
                {"item_id": item_id},
            ).all()
        if not rows:
            raise ValueError(f"No linked account found for Plaid item_id={item_id!r}")
        return {row.plaid_account_id: str(row.id) for row in rows}
