"""`app/jobs/weekly_finance_audit.py` tests (D6, per A4). Highest
priority in this ticket (Q2): a duplicate trigger for an
already-sent period must short-circuit before any of the expensive/
dangerous side effects (transaction query, LLM call, Telegram send) --
not just before the final commit. Everything external (DB session,
`run_weekly_triage`, the Telegram `Bot`) is faked/mocked; no real
Postgres/Gemini/Telegram credentials exist in this environment.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.jobs.weekly_finance_audit as job_module
from app.jobs.weekly_finance_audit import DigestPeriod


class _FakeScalars:
    def __init__(self, value):
        self._value = value

    def first(self):
        return self._value


class _FakeExecuteResult:
    def __init__(self, value):
        self._value = value

    def scalars(self):
        return _FakeScalars(self._value)


class _FakeSession:
    """Stands in for `AsyncSession`. `digest_log_exists` controls what
    `_already_sent`'s `session.execute(select(DigestLog.id)...)` call
    sees -- a scalar id if a row already exists, `None` if not."""

    def __init__(self, digest_log_exists: bool):
        self._existing_id = uuid.uuid4() if digest_log_exists else None
        self.added: list[object] = []
        self.committed = False

    async def execute(self, statement):
        return _FakeExecuteResult(self._existing_id)

    def add(self, obj) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.committed = True


@pytest.fixture
def mocked_dependencies(monkeypatch):
    """Patches every external dependency `run_weekly_digest` calls
    past the idempotency check: the finance-service read paths, the
    LLM triage call, and the Telegram bot -- so a test can assert on
    exactly which of these were (or, for the already-sent path,
    were NOT) invoked."""
    fake_get_transactions = AsyncMock(return_value=[])
    fake_get_account_summary = AsyncMock(return_value=[])
    fake_run_weekly_triage = AsyncMock(return_value="Weekly summary text.")
    fake_bot_instance = MagicMock()
    fake_bot_instance.send_message = AsyncMock()
    fake_bot_factory = MagicMock(return_value=fake_bot_instance)

    monkeypatch.setattr(job_module.finance_service, "get_transactions", fake_get_transactions)
    monkeypatch.setattr(
        job_module.finance_service, "get_account_summary", fake_get_account_summary
    )
    monkeypatch.setattr(job_module, "run_weekly_triage", fake_run_weekly_triage)
    monkeypatch.setattr(job_module, "Bot", fake_bot_factory)

    return {
        "get_transactions": fake_get_transactions,
        "get_account_summary": fake_get_account_summary,
        "run_weekly_triage": fake_run_weekly_triage,
        "bot_factory": fake_bot_factory,
        "bot_instance": fake_bot_instance,
    }


# --- Idempotency: the safety-critical path ------------------------------------


async def test_run_weekly_digest_already_sent_period_short_circuits_before_any_side_effect(
    mocked_dependencies,
):
    """The core guarantee A4 requires: a second trigger for a period
    that already has a `DigestLog` row must NOT re-query transactions,
    re-call the LLM, or re-send to Telegram -- not just skip the
    commit at the end."""
    session = _FakeSession(digest_log_exists=True)

    result = await job_module.run_weekly_digest(session)

    assert result["sent"] is False
    assert result["reason"] == "digest already sent for this period"
    assert "period_start" in result and "period_end" in result

    mocked_dependencies["get_transactions"].assert_not_awaited()
    mocked_dependencies["get_account_summary"].assert_not_awaited()
    mocked_dependencies["run_weekly_triage"].assert_not_awaited()
    mocked_dependencies["bot_factory"].assert_not_called()
    mocked_dependencies["bot_instance"].send_message.assert_not_awaited()
    assert session.added == []
    assert session.committed is False


async def test_run_weekly_digest_fresh_period_queries_sends_and_logs(mocked_dependencies):
    """The complementary fresh-period path: every step actually runs
    exactly once, and a `DigestLog` row is staged and committed."""
    session = _FakeSession(digest_log_exists=False)

    result = await job_module.run_weekly_digest(session)

    assert result["sent"] is True
    assert "period_start" in result and "period_end" in result

    mocked_dependencies["get_transactions"].assert_awaited_once()
    mocked_dependencies["get_account_summary"].assert_awaited_once()
    mocked_dependencies["run_weekly_triage"].assert_awaited_once()
    mocked_dependencies["bot_instance"].send_message.assert_awaited_once()
    assert len(session.added) == 1
    logged = session.added[0]
    assert logged.period_start is not None
    assert logged.period_end is not None
    assert session.committed is True


async def test_run_weekly_digest_sends_the_triage_text_to_telegram(mocked_dependencies):
    session = _FakeSession(digest_log_exists=False)

    await job_module.run_weekly_digest(session)

    _, kwargs = mocked_dependencies["bot_instance"].send_message.call_args
    assert kwargs["text"] == "Weekly summary text."


async def test_run_weekly_digest_truncates_oversized_triage_text_before_sending(
    mocked_dependencies,
):
    mocked_dependencies["run_weekly_triage"].return_value = "x" * 5000
    session = _FakeSession(digest_log_exists=False)

    await job_module.run_weekly_digest(session)

    _, kwargs = mocked_dependencies["bot_instance"].send_message.call_args
    assert len(kwargs["text"]) == job_module._TELEGRAM_MAX_CHARS


# --- _already_sent -------------------------------------------------------------


async def test_already_sent_true_when_digest_log_row_exists():
    session = _FakeSession(digest_log_exists=True)
    period = DigestPeriod(start=date(2026, 9, 20), end=date(2026, 9, 27))

    assert await job_module._already_sent(session, period) is True


async def test_already_sent_false_when_no_digest_log_row():
    session = _FakeSession(digest_log_exists=False)
    period = DigestPeriod(start=date(2026, 9, 20), end=date(2026, 9, 27))

    assert await job_module._already_sent(session, period) is False


# --- _current_period ------------------------------------------------------------


def test_current_period_is_a_rolling_seven_days_ending_on_today():
    today = date(2026, 9, 27)

    period = job_module._current_period(today)

    assert period.end == today
    assert period.start == today - timedelta(days=7)


def test_current_period_defaults_to_todays_utc_date_when_not_given():
    period = job_module._current_period()

    assert period.end - period.start == timedelta(days=7)


# --- _annotate_utilization (30% threshold, A4) ---------------------------------


def test_annotate_utilization_flags_accounts_strictly_over_threshold():
    accounts = [
        {"account_id": "a", "utilization": 0.5},
        {"account_id": "b", "utilization": 0.1},
    ]

    annotated = job_module._annotate_utilization(accounts)

    assert annotated[0]["over_utilization_threshold"] is True
    assert annotated[1]["over_utilization_threshold"] is False


def test_annotate_utilization_treats_none_utilization_as_not_flagged():
    accounts = [{"account_id": "a", "utilization": None}]

    annotated = job_module._annotate_utilization(accounts)

    assert annotated[0]["over_utilization_threshold"] is False


def test_annotate_utilization_at_exactly_30_percent_is_not_flagged():
    """A4 confirms 30% as the threshold; the implementation flags
    strictly-over, not at-or-over -- guards against a future edit
    silently switching the comparison operator."""
    accounts = [{"account_id": "a", "utilization": 0.30}]

    annotated = job_module._annotate_utilization(accounts)

    assert annotated[0]["over_utilization_threshold"] is False


def test_annotate_utilization_preserves_original_account_fields():
    accounts = [{"account_id": "a", "utilization": 0.9, "institution_name": "Chase"}]

    annotated = job_module._annotate_utilization(accounts)

    assert annotated[0]["account_id"] == "a"
    assert annotated[0]["institution_name"] == "Chase"


# --- _fit_to_telegram_limit (R2/A4) --------------------------------------------


def test_fit_to_telegram_limit_passes_short_text_through_unchanged():
    text = "short summary"

    assert job_module._fit_to_telegram_limit(text) == text


def test_fit_to_telegram_limit_truncates_oversized_text_to_the_hard_limit():
    text = "x" * 5000

    fitted = job_module._fit_to_telegram_limit(text)

    assert len(fitted) == job_module._TELEGRAM_MAX_CHARS
    assert fitted.endswith(job_module._TRUNCATION_SUFFIX)


def test_fit_to_telegram_limit_boundary_at_exactly_the_limit_is_unchanged():
    text = "x" * job_module._TELEGRAM_MAX_CHARS

    assert job_module._fit_to_telegram_limit(text) == text
