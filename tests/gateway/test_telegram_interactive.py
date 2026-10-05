"""D7 delivery behavior, with Telegram and the engine mocked."""
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.gateway.router as gateway


@pytest.fixture
def delivery(monkeypatch):
    bot = AsyncMock()
    context = AsyncMock()
    context.__aenter__.return_value = bot
    monkeypatch.setattr(gateway, "Bot", MagicMock(return_value=context))
    engine = AsyncMock(return_value="Your balance is <100> & steady.")
    monkeypatch.setattr(gateway, "run_interactive_query", engine)
    return bot, engine


@pytest.mark.asyncio
async def test_plain_text_reply(delivery):
    bot, engine = delivery
    await gateway._reply_to_telegram(42, "How much did I spend?")
    engine.assert_awaited_once_with("How much did I spend?")
    bot.send_message.assert_awaited_once_with(
        chat_id=42, text="Your balance is <100> & steady.", parse_mode=None
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["/help", "/start", "/digest", "/help@another_bot"])
async def test_commands_skip_agent(delivery, command):
    bot, engine = delivery
    await gateway._reply_to_telegram(42, command)
    engine.assert_not_awaited()
    assert "finance question" in bot.send_message.call_args.kwargs["text"]


@pytest.mark.asyncio
async def test_agent_failure_sends_generic_reply(delivery, caplog):
    bot, engine = delivery
    engine.side_effect = RuntimeError("private finance data")
    await gateway._reply_to_telegram(42, "question")
    assert bot.send_message.call_args.kwargs["text"] == gateway._AGENT_ERROR_REPLY
    assert "private finance data" not in caplog.text


@pytest.mark.asyncio
async def test_delivery_failure_is_contained(delivery, caplog):
    bot, engine = delivery
    bot.send_message.side_effect = RuntimeError("sensitive token URL")
    await gateway._reply_to_telegram(42, "question")
    engine.assert_awaited_once()
    assert "delivery failed" in caplog.text
    assert "sensitive token URL" not in caplog.text


@pytest.mark.asyncio
async def test_empty_answer_has_fallback(delivery):
    bot, engine = delivery
    engine.return_value = "  "
    await gateway._reply_to_telegram(42, "question")
    assert "rephrasing" in bot.send_message.call_args.kwargs["text"]


@pytest.mark.parametrize("text", ["a" * 4096, "a" * 4097, "😀" * 2048, "😀" * 2049])
def test_reply_length_boundaries(text):
    reply = gateway._fit_telegram_reply(text)
    assert len(reply.encode("utf-16-le")) <= 4096 * 2
    if len(text.encode("utf-16-le")) <= 4096 * 2:
        assert reply == text
    else:
        assert reply.endswith("[truncated]")
