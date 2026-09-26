"""Weekly financial triage job (D6, per A4's weekly-triage-job spec).

No in-process scheduler (R4/A4): this module's `run_weekly_digest` is
called by the gateway's `POST /jobs/weekly-digest/trigger` endpoint,
itself invoked by an external cron service (`cron-job.org`). This file
owns the job body only - trigger auth and HTTP wiring live in
`app/gateway/router.py`.

Job logic, per A4:
    1. Query the past 7 days of `FinancialTransaction` rows across all
       `CreditAccount`s via `app/domains/finance/service.py`'s read
       paths (not a tool - server-side logic, not LLM-driven).
    2. Compute/flag credit utilization per account (30% threshold,
       confirmed by the user in A4).
    3. Pass transactions + accounts to `agent.engine.run_weekly_triage`
       (A3) for the natural-language summary.
    4. Fit the result to Telegram's 4,096-char limit (R2).
    5. Send via the Telegram Bot API to `TELEGRAM_ALLOWED_CHAT_ID`.
    6. Write a `DigestLog` row.

Idempotent: short-circuits before any of the above (no query, no model
call, no send) if a `DigestLog` row already exists for the current
period.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Bot

from app.agent.engine import run_weekly_triage
from app.config import settings
from app.domains.finance import service as finance_service
from app.domains.finance.models import DigestLog, FinancialTransaction

# Telegram's hard per-message limit (R2). `run_weekly_triage`'s own
# prompt already asks Gemini to stay well under this (A4's preferred
# fix for overflow - a bounded-length instruction, not post-hoc
# truncation), but this is a defensive backstop so a request can never
# reach the Bot API oversized regardless of what the model returns.
_TELEGRAM_MAX_CHARS = 4096
_TRUNCATION_SUFFIX = "\n\n[truncated]"

# A4's "what credit utilization tracking means here": a reasonable
# default threshold, confirmed at 30% by the user.
_UTILIZATION_ALERT_THRESHOLD = Decimal("0.30")


@dataclass(frozen=True)
class DigestPeriod:
    start: date
    end: date


def _current_period(today: date | None = None) -> DigestPeriod:
    """Past 7 days ending today (A4 step 1). `end` also doubles as the
    `DigestLog` idempotency key."""
    end = today or datetime.now(timezone.utc).date()
    return DigestPeriod(start=end - timedelta(days=7), end=end)


def _serialize_transaction(txn: FinancialTransaction) -> dict:
    """`run_weekly_triage` (A3/D5) takes `list[dict]`, not ORM rows -
    only the fields relevant to a spending summary."""
    return {
        "account_id": str(txn.account_id),
        "amount": txn.amount,
        "currency_code": txn.currency_code,
        "posted_date": txn.posted_date,
        "merchant_name": txn.merchant_name,
        "category": txn.category,
        "pending": txn.pending,
    }


def _annotate_utilization(accounts: list[dict]) -> list[dict]:
    """`finance_service.get_account_summary` already computes a raw
    `utilization` ratio per account (A1's `credit_limit`); this flags
    which accounts cross A4's 30% threshold explicitly, rather than
    leaving that judgment call to the model."""
    annotated = []
    for account in accounts:
        utilization = account.get("utilization")
        over_threshold = (
            utilization is not None
            and Decimal(str(utilization)) > _UTILIZATION_ALERT_THRESHOLD
        )
        annotated.append({**account, "over_utilization_threshold": over_threshold})
    return annotated


def _fit_to_telegram_limit(text: str) -> str:
    if len(text) <= _TELEGRAM_MAX_CHARS:
        return text
    return text[: _TELEGRAM_MAX_CHARS - len(_TRUNCATION_SUFFIX)] + _TRUNCATION_SUFFIX


async def _already_sent(session: AsyncSession, period: DigestPeriod) -> bool:
    result = await session.execute(
        select(DigestLog.id).where(DigestLog.period_end == period.end)
    )
    return result.scalars().first() is not None


async def run_weekly_digest(session: AsyncSession) -> dict:
    """The job body (A4). Caller (the gateway trigger endpoint) owns
    the session lifecycle; this function commits once on success.

    Returns a small JSON-able summary dict describing what happened -
    the trigger endpoint returns this directly as the HTTP response
    body.
    """
    period = _current_period()

    if await _already_sent(session, period):
        return {
            "sent": False,
            "reason": "digest already sent for this period",
            "period_start": period.start.isoformat(),
            "period_end": period.end.isoformat(),
        }

    transactions = await finance_service.get_transactions(session, period.start, period.end)
    accounts = _annotate_utilization(await finance_service.get_account_summary(session))

    digest_text = await run_weekly_triage(
        [_serialize_transaction(txn) for txn in transactions],
        accounts,
    )
    digest_text = _fit_to_telegram_limit(digest_text)

    bot = Bot(token=settings.telegram_bot_token)
    await bot.send_message(chat_id=settings.telegram_allowed_chat_id, text=digest_text)

    session.add(
        DigestLog(
            sent_at=datetime.now(timezone.utc),
            period_start=period.start,
            period_end=period.end,
        )
    )
    await session.commit()

    return {
        "sent": True,
        "period_start": period.start.isoformat(),
        "period_end": period.end.isoformat(),
    }
