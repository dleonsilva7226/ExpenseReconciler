"""Gateway router (D4, per A2 + A2a; extended by D6, per A4): inbound
webhooks, the account-linking UI, and the weekly digest job trigger.

Endpoints:
    POST /webhooks/plaid              - Plaid sync-ready notifications
    POST /webhooks/telegram           - Telegram bot updates
    GET  /link-account                - public verification/connect page
    GET  /link-account/assets/*       - two public CSS/JS assets
    GET  /link-account/session        - current browser verification status
    POST /link-account/session        - verify admin access, create browser session
    POST /link-account/logout         - delete browser session cookie
    POST /link-account/token          - mint a Plaid Link token (session protected)
    POST /link-account/callback       - exchange public_token, persist accounts (protected)
    POST /jobs/weekly-digest/trigger  - run the weekly digest job (JOBS_TRIGGER_SECRET-gated)
"""

from __future__ import annotations

import json
import logging
import secrets
import uuid
from pathlib import Path

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Request,
    Response,
    status,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.routing import APIRoute
from plaid.exceptions import ApiException
from plaid.model.country_code import CountryCode
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.products import Products
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool
from telegram import Bot
from urllib3.exceptions import HTTPError as ProviderHTTPError

from app.agent.engine import run_interactive_query
from app.config import settings
from app.database import async_session_factory
from app.domains.finance import service as finance_service
from app.domains.finance.schemas import PlaidWebhookPayload, TelegramUpdate
from app.gateway.auth import (
    COOKIE_NAME,
    AdminUser,
    clear_session_cookie,
    create_session,
    credentials_match,
    decode_session,
    require_login_request,
    require_transport,
    session_status,
    set_session_cookie,
)
from app.integrations.bank.plaid_connector import (
    PlaidBankConnector,
    build_plaid_client,
    build_sync_engine,
)
from app.integrations.bank.plaid_webhook import verify_plaid_webhook
from app.jobs.weekly_finance_audit import run_weekly_digest


class BrowserResponseRoute(APIRoute):
    """Never cache browser responses, including validation/auth failures."""

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def browser_handler(request: Request):
            if not request.url.path.startswith("/link-account"):
                return await handler(request)
            try:
                response = await handler(request)
            except HTTPException as exc:
                exc.headers = {**(exc.headers or {}), "Cache-Control": "no-store"}
                raise
            except RequestValidationError:
                # FastAPI validation payloads can echo submitted passwords.
                response = JSONResponse(
                    {"detail": "Please check the submitted fields."}, status_code=422
                )
            response.headers["Cache-Control"] = "no-store"
            return response

        return browser_handler


router = APIRouter(route_class=BrowserResponseRoute)
_logger = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).parent / "static"

# Built once at module import (process startup), reused across requests.
_plaid_client = build_plaid_client(settings)
_sync_engine = build_sync_engine(settings)
_bank_connector = PlaidBankConnector(
    _plaid_client, _sync_engine, settings.token_encryption_key
)


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


_TELEGRAM_MAX_UNITS = 4096
_TRUNCATION_SUFFIX = "\n\n[truncated]"
_TELEGRAM_HELP = (
    "Ask me a finance question in a text message. "
    "Use /start or /help for this guidance."
)
_AGENT_ERROR_REPLY = "I couldn't answer that right now. Please try again later."


def _fit_telegram_reply(text: str) -> str:
    """Bound plain text conservatively in UTF-16 units, including emoji."""
    encoded = text.encode("utf-16-le")
    if len(encoded) <= _TELEGRAM_MAX_UNITS * 2:
        return text
    budget = _TELEGRAM_MAX_UNITS - len(_TRUNCATION_SUFFIX)
    # Dropping an incomplete surrogate pair preserves valid Unicode.
    return (
        encoded[: budget * 2].decode("utf-16-le", errors="ignore") + _TRUNCATION_SUFFIX
    )


async def _reply_to_telegram(chat_id: int, user_text: str) -> None:
    """Run after acknowledgment; failures never provoke webhook retries.

    No conversational state or weekly-digest trigger is introduced.
    Avoid logging exception details: provider/HTTP exceptions can carry
    financial text or Bot API URLs containing the token.
    """
    if user_text.startswith("/"):
        command = user_text.split(maxsplit=1)[0]
        if command in {"/start", "/help"}:
            reply = _TELEGRAM_HELP
        else:
            reply = "Unknown command. " + _TELEGRAM_HELP
    else:
        try:
            reply = await run_interactive_query(user_text)
            if not reply.strip():
                reply = (
                    "I couldn't find an answer. Please try rephrasing your question."
                )
        except Exception:  # noqa: BLE001 - contain provider failures after acknowledgment
            _logger.warning("Telegram interactive query failed")
            reply = _AGENT_ERROR_REPLY

    try:
        async with Bot(token=settings.telegram_bot_token) as bot:
            await bot.send_message(
                chat_id=chat_id, text=_fit_telegram_reply(reply), parse_mode=None
            )
    except Exception:  # noqa: BLE001 - Telegram failures must not trigger duplicate LLM calls
        _logger.warning("Telegram interactive reply delivery failed")


@router.post("/webhooks/telegram", status_code=status.HTTP_200_OK)
async def telegram_webhook(request: Request, background_tasks: BackgroundTasks) -> dict:
    secret_header = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not settings.telegram_webhook_secret_token or not secrets.compare_digest(
        secret_header, settings.telegram_webhook_secret_token
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook secret"
        )

    try:
        update = TelegramUpdate.model_validate_json(await request.body())
    except (ValidationError, json.JSONDecodeError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid Telegram update",
        ) from None

    if (
        update.message is None
        or update.message.chat.id != settings.telegram_allowed_chat_id
    ):
        # Chat-ID allowlist (A2): silently drop anything not from you.
        return {"acknowledged": True}

    user_text = (update.message.text or "").strip()
    if user_text:
        background_tasks.add_task(_reply_to_telegram, update.message.chat.id, user_text)

    return {"acknowledged": True}


# --- Account linking UI (A2a) -----------------------------------------------


@router.get("/link-account", response_class=HTMLResponse)
async def link_account_page() -> HTMLResponse:
    html = (_STATIC_DIR / "link_account.html").read_text()
    return HTMLResponse(content=html, headers={"Referrer-Policy": "no-referrer"})


@router.get("/link-account/assets/link_account.css")
async def link_account_css() -> FileResponse:
    return FileResponse(_STATIC_DIR / "link_account.css", media_type="text/css")


@router.get("/link-account/assets/link_account.js")
async def link_account_js() -> FileResponse:
    return FileResponse(
        _STATIC_DIR / "link_account.js", media_type="application/javascript"
    )


class VerificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=256)
    password: str = Field(min_length=1, max_length=1024)


@router.get("/link-account/session")
async def get_browser_session(request: Request, response: Response) -> dict:
    require_transport(request)
    claims = decode_session(request.cookies.get(COOKIE_NAME))
    if claims is None:
        if COOKIE_NAME in request.cookies:
            clear_session_cookie(response, request)
        return {"authenticated": False}
    return session_status(claims)


@router.post("/link-account/session", dependencies=[Depends(require_login_request)])
async def verify_access(
    body: VerificationRequest, request: Request, response: Response
) -> dict:
    if not credentials_match(body.username, body.password):
        raise HTTPException(401, "We couldn't verify those details. Please try again.")
    token, claims = create_session()
    set_session_cookie(response, request, token)
    return session_status(claims)


@router.post("/link-account/logout")
async def sign_out(request: Request, response: Response, _: AdminUser) -> dict:
    clear_session_cookie(response, request)
    return {"authenticated": False}


@router.post("/link-account/token")
async def create_link_token(_: AdminUser) -> dict:
    request_obj = LinkTokenCreateRequest(
        user=LinkTokenCreateRequestUser(client_user_id=settings.admin_username),
        client_name="ExpenseReconciler",
        products=[Products("transactions")],
        country_codes=[CountryCode("US")],
        language="en",
    )
    try:
        response = await run_in_threadpool(_plaid_client.link_token_create, request_obj)
    except (ApiException, ProviderHTTPError) as exc:
        _logger.warning("Plaid link token creation failed (%s)", type(exc).__name__)
        raise HTTPException(
            502, "We couldn't connect to your bank. Please try again."
        ) from None
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

    try:
        linked = await run_in_threadpool(
            _bank_connector.exchange_public_token, body.public_token
        )
    except (ApiException, ProviderHTTPError) as exc:
        _logger.warning("Plaid token exchange failed (%s)", type(exc).__name__)
        raise HTTPException(
            502, "We couldn't connect to your bank. Please try again."
        ) from None

    # A1 amendment 2026-09-20 ("Item vs. account identity"): one Plaid
    # Item can cover multiple accounts (e.g. checking + credit card at
    # the same bank) — insert one credit_accounts row per account
    # returned by Link, all sharing item_id/institution_name/token but
    # each with its own plaid_account_id.
    try:
        async with async_session_factory() as session:
            try:
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
            except SQLAlchemyError:
                await session.rollback()
                raise
    except SQLAlchemyError as exc:
        _logger.warning("Bank account persistence failed (%s)", type(exc).__name__)
        raise HTTPException(
            500, "We couldn't save your account. Please try again."
        ) from None

    return {
        "linked": True,
        "item_id": linked.item_id,
        "accounts_linked": len(body.accounts),
    }


# --- Weekly digest job trigger (A4/D6) ---------------------------------------


def _verify_jobs_trigger_secret(request: Request) -> None:
    """Machine-to-machine auth (A4/R4): a bearer token compared via
    `secrets.compare_digest`, distinct from browser session verification -
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
