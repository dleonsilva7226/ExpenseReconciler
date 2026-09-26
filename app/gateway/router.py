"""Gateway router (D4, per A2 + A2a; extended by D6, per A4): inbound
webhooks, the account-linking UI, and the weekly digest job trigger.

Endpoints:
    POST /webhooks/plaid              - Plaid sync-ready notifications
    POST /webhooks/telegram           - Telegram bot updates
    GET  /link-account                - Plaid Link UI page (auth required)
    POST /link-account/token          - mint a short-lived Plaid Link token (auth required)
    POST /link-account/callback       - exchange public_token, persist the account (auth required)
    POST /jobs/weekly-digest/trigger  - run the weekly digest job (JOBS_TRIGGER_SECRET-gated)
"""

from __future__ import annotations

import secrets
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from plaid.model.country_code import CountryCode
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.products import Products
from pydantic import BaseModel
from sqlalchemy import text
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.database import async_session_factory
from app.domains.finance import service as finance_service
from app.domains.finance.schemas import PlaidWebhookPayload, TelegramUpdate
from app.gateway.auth import AdminUser
from app.integrations.bank.plaid_connector import (
    PlaidBankConnector,
    build_plaid_client,
    build_sync_engine,
)
from app.integrations.bank.plaid_webhook import verify_plaid_webhook
from app.jobs.weekly_finance_audit import run_weekly_digest

router = APIRouter()

_STATIC_DIR = Path(__file__).parent / "static"

# Built once at module import (process startup), reused across requests.
_plaid_client = build_plaid_client(settings)
_sync_engine = build_sync_engine(settings)
_bank_connector = PlaidBankConnector(_plaid_client, _sync_engine, settings.token_encryption_key)


# --- Plaid webhook ---------------------------------------------------------


async def _run_plaid_sync(item_id: str) -> None:
    """Background task body (A2: runs after the webhook response is
    already sent). `sync_transactions` is sync (Plaid's SDK is
    blocking), so it runs in a threadpool; `ingest_transactions` is
    async and runs directly."""
    transactions = await run_in_threadpool(_bank_connector.sync_transactions, item_id)
    async with async_session_factory() as session:
        await finance_service.ingest_transactions(transactions, session)
        await session.commit()


@router.post("/webhooks/plaid", status_code=status.HTTP_200_OK)
async def plaid_webhook(request: Request, background_tasks: BackgroundTasks) -> dict:
    raw_body = await request.body()
    jwt_header = request.headers.get("Plaid-Verification", "")

    if not verify_plaid_webhook(_plaid_client, jwt_header, raw_body):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook signature"
        )

    payload = PlaidWebhookPayload.model_validate_json(raw_body)

    if payload.webhook_code == "SYNC_UPDATES_AVAILABLE":
        background_tasks.add_task(_run_plaid_sync, payload.item_id)

    return {"acknowledged": True}


# --- Telegram webhook -------------------------------------------------------


@router.post("/webhooks/telegram", status_code=status.HTTP_200_OK)
async def telegram_webhook(request: Request) -> dict:
    secret_header = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not secrets.compare_digest(secret_header, settings.telegram_webhook_secret_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook secret"
        )

    body = await request.json()
    update = TelegramUpdate.model_validate(body)

    if update.message is None or update.message.chat.id != settings.telegram_allowed_chat_id:
        # Chat-ID allowlist (A2): silently drop anything not from you.
        return {"acknowledged": True}

    # Dispatch to app/agent/engine.py is A3/D5's contract, not built
    # yet (A2 explicitly scopes that out of this ticket). Intentional
    # no-op placeholder until D5 lands — see the D1-D4 status note.

    return {"acknowledged": True}


# --- Account linking UI (A2a) -----------------------------------------------


@router.get("/link-account", response_class=HTMLResponse)
async def link_account_page(_: AdminUser) -> HTMLResponse:
    html = (_STATIC_DIR / "link_account.html").read_text()
    return HTMLResponse(content=html)


@router.post("/link-account/token")
async def create_link_token(_: AdminUser) -> dict:
    request_obj = LinkTokenCreateRequest(
        user=LinkTokenCreateRequestUser(client_user_id=settings.admin_username),
        client_name="ExpenseReconciler",
        products=[Products("transactions")],
        country_codes=[CountryCode("US")],
        language="en",
    )
    response = await run_in_threadpool(_plaid_client.link_token_create, request_obj)
    return {"link_token": response.link_token}


class LinkAccountCallbackAccount(BaseModel):
    id: str
    name: str
    mask: str | None = None
    type: str | None = None
    subtype: str | None = None


class LinkAccountCallbackRequest(BaseModel):
    """Body shape not explicitly assigned a home by A2a beyond the
    example JSON in its spec; kept local to this route rather than in
    the finance domain's schemas.py since it's endpoint-specific, not
    a finance-domain concept. Flagged as a minor implementation
    choice in the status note."""

    public_token: str
    institution_name: str
    accounts: list[LinkAccountCallbackAccount]


@router.post("/link-account/callback")
async def link_account_callback(
    body: LinkAccountCallbackRequest,
    _: AdminUser,
) -> dict:
    if not body.accounts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No accounts returned by Plaid Link",
        )

    linked = await run_in_threadpool(_bank_connector.exchange_public_token, body.public_token)

    # A1 amendment 2026-09-20 ("Item vs. account identity"): one Plaid
    # Item can cover multiple accounts (e.g. checking + credit card at
    # the same bank) — insert one credit_accounts row per account
    # returned by Link, all sharing item_id/institution_name/token but
    # each with its own plaid_account_id.
    async with async_session_factory() as session:
        for account in body.accounts:
            await session.execute(
                text(
                    "INSERT INTO credit_accounts "
                    "(id, plaid_item_id, plaid_account_id, plaid_access_token_encrypted, "
                    " institution_name, account_name, account_mask, account_type, "
                    " account_subtype, currency_code) "
                    "VALUES (:id, :item_id, :account_id, pgp_sym_encrypt(:token, :key), "
                    " :institution_name, :account_name, :account_mask, :account_type, "
                    " :account_subtype, :currency_code)"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "item_id": linked.item_id,
                    "account_id": account.id,
                    "token": linked.access_token,
                    "key": settings.token_encryption_key,
                    "institution_name": body.institution_name,
                    "account_name": account.name,
                    # ASSUMPTION (status note): mask/type default to
                    # placeholders if Plaid Link's metadata omits them;
                    # currency_code is hardcoded USD — reasonable for
                    # personal US bank accounts, not derived from a real
                    # Plaid /accounts/get call yet.
                    "account_mask": account.mask or "",
                    "account_type": account.type or "unknown",
                    "account_subtype": account.subtype,
                    "currency_code": "USD",
                },
            )
        await session.commit()

    return {
        "linked": True,
        "item_id": linked.item_id,
        "accounts_linked": len(body.accounts),
    }


# --- Weekly digest job trigger (A4/D6) ---------------------------------------


def _verify_jobs_trigger_secret(request: Request) -> None:
    """Machine-to-machine auth (A4/R4): a bearer token compared via
    `secrets.compare_digest`, distinct from A2a's admin Basic Auth -
    this is called by an external cron service (`cron-job.org`), not a
    browser."""
    auth_header = request.headers.get("Authorization", "")
    prefix = "Bearer "
    provided = auth_header[len(prefix) :] if auth_header.startswith(prefix) else ""
    if not secrets.compare_digest(provided, settings.jobs_trigger_secret):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid trigger secret"
        )


@router.post("/jobs/weekly-digest/trigger")
async def trigger_weekly_digest(request: Request) -> dict:
    _verify_jobs_trigger_secret(request)
    async with async_session_factory() as session:
        return await run_weekly_digest(session)
