"""Independent D7 checks: real engine/adapter, mocked remote boundaries."""
import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.agent.providers.openai_provider as provider
import app.gateway.router as gateway
from app.agent import engine
from app.config import settings


@pytest.fixture
def remote_boundaries(monkeypatch):
    bot = AsyncMock()
    context = AsyncMock()
    context.__aenter__.return_value = bot
    monkeypatch.setattr(gateway, "Bot", MagicMock(return_value=context))
    create = MagicMock()
    sdk = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(provider, "OpenAI", MagicMock(return_value=sdk))
    return create, bot, context


def completion(text=None, calls=None):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
        content=text, tool_calls=calls or []
    ))])


def payload(text="How much did I spend?", chat_id=None):
    return {"update_id": 7, "message": {"message_id": 1, "date": 0,
            "chat": {"id": chat_id or settings.telegram_allowed_chat_id, "type": "private"},
            "text": text}}


def post(client, body):
    return client.post("/webhooks/telegram", json=body, headers={
        "X-Telegram-Bot-Api-Secret-Token": settings.telegram_webhook_secret_token})


def test_webhook_real_engine_and_adapter_tool_round_trip(client, monkeypatch, remote_boundaries):
    create, bot, context = remote_boundaries
    tool_call = SimpleNamespace(id="qa_call", function=SimpleNamespace(
        name="get_account_summary", arguments='{"account_id":"qa-account"}'))
    create.side_effect = [completion(calls=[tool_call]), completion("Balance <123.45> & steady.")]
    lookup = AsyncMock(return_value=[{"balance": Decimal("123.45")}])
    monkeypatch.setattr(engine, "TOOL_IMPLEMENTATIONS", {"get_account_summary": lookup})
    response = post(client, payload("  Check my balance  "))
    assert response.status_code == 200
    assert response.json() == {"acknowledged": True}
    lookup.assert_awaited_once_with(account_id="qa-account")
    assert create.call_count == 2
    first, second = [call.kwargs for call in create.call_args_list]
    assert first["model"] == "gpt-4o-mini"
    assert first["messages"] == [{"role": "user", "content": "Check my balance"}]
    assert {tool["function"]["name"] for tool in first["tools"]} == {
        "get_account_summary", "get_transactions", "get_spending_by_category"}
    assert second["messages"][1]["tool_calls"][0]["id"] == "qa_call"
    assert second["messages"][2]["tool_call_id"] == "qa_call"
    assert json.loads(second["messages"][2]["content"]) == [{"balance": "123.45"}]
    bot.send_message.assert_awaited_once_with(chat_id=settings.telegram_allowed_chat_id,
                                            text="Balance <123.45> & steady.", parse_mode=None)
    context.__aexit__.assert_awaited_once()


@pytest.mark.asyncio
async def test_asgi_acknowledgment_sent_before_llm(monkeypatch, remote_boundaries):
    from app.main import app

    create, bot, _ = remote_boundaries
    events = []

    def llm(**kwargs):
        assert events == ["http.response.start", "http.response.body"]
        events.append("llm")
        return completion("Done")

    create.side_effect = llm
    raw = json.dumps(payload()).encode()
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
             "method": "POST", "scheme": "http", "path": "/webhooks/telegram",
             "raw_path": b"/webhooks/telegram", "query_string": b"",
             "headers": [(b"content-type", b"application/json"),
                         (b"x-telegram-bot-api-secret-token",
                          settings.telegram_webhook_secret_token.encode())],
             "client": ("127.0.0.1", 123), "server": ("test", 80), "root_path": ""}

    async def receive():
        return {"type": "http.request", "body": raw, "more_body": False}

    async def send(message):
        events.append(message["type"])
        if message["type"] == "http.response.start":
            assert message["status"] == 200
        else:
            assert json.loads(message["body"]) == {"acknowledged": True}
            assert not message.get("more_body", False)

    await app(scope, receive, send)
    assert events[-1] == "llm"
    bot.send_message.assert_awaited_once()


@pytest.mark.parametrize("body", [payload(chat_id=settings.telegram_allowed_chat_id + 1),
                                  payload(" \n\t "), payload(None),
                                  {"update_id": 8, "callback_query": {"data": "secret"}}])
def test_ignored_updates_never_reach_remote_calls(client, remote_boundaries, body):
    create, bot, context = remote_boundaries
    assert post(client, body).status_code == 200
    create.assert_not_called()
    bot.send_message.assert_not_awaited()
    context.__aenter__.assert_not_awaited()


def test_auth_precedes_malformed_body(client, remote_boundaries):
    create, bot, _ = remote_boundaries
    assert client.post("/webhooks/telegram", content=b"{").status_code == 401
    malformed = client.post("/webhooks/telegram", content=b"{", headers={
        "X-Telegram-Bot-Api-Secret-Token": settings.telegram_webhook_secret_token
    })
    assert malformed.status_code == 422
    assert malformed.json() == {"detail": "Invalid Telegram update"}
    invalid = post(client, {"update_id": "not-an-integer"})
    assert invalid.status_code == 422
    assert invalid.json() == {"detail": "Invalid Telegram update"}
    create.assert_not_called()
    bot.send_message.assert_not_awaited()


def test_real_provider_failure_is_generic_and_closes_bot(client, remote_boundaries, caplog):
    create, bot, context = remote_boundaries
    create.side_effect = RuntimeError("private bank balance and token URL")
    assert post(client, payload()).status_code == 200
    assert bot.send_message.call_args.kwargs["text"] == gateway._AGENT_ERROR_REPLY
    assert "private bank balance" not in caplog.text
    context.__aexit__.assert_awaited_once()


def test_send_failure_still_closes_bot(client, remote_boundaries, caplog):
    create, bot, context = remote_boundaries
    create.return_value = completion("answer")
    bot.send_message.side_effect = RuntimeError("private token URL")
    assert post(client, payload()).status_code == 200
    assert create.call_count == 1
    context.__aexit__.assert_awaited_once()
    assert "private token URL" not in caplog.text


@pytest.mark.parametrize("command,unknown", [("/start", False), ("/help more", False),
                                            ("/digest", True), ("/help@bot", True)])
def test_webhook_commands_skip_llm(client, remote_boundaries, command, unknown):
    create, bot, context = remote_boundaries
    assert post(client, payload(command)).status_code == 200
    create.assert_not_called()
    reply = bot.send_message.call_args.kwargs["text"]
    assert reply.startswith("Unknown command.") == unknown
    assert "finance question" in reply
    context.__aexit__.assert_awaited_once()


@pytest.mark.parametrize("text", ["a" * 4096, "a" * 4097, "😀" * 2048,
                                  "a😀" * 2000, "e\u0301" * 3000])
def test_webhook_real_llm_reply_unicode_limits(client, remote_boundaries, text):
    create, bot, _ = remote_boundaries
    create.return_value = completion(text)
    assert post(client, payload()).status_code == 200
    reply = bot.send_message.call_args.kwargs["text"]
    assert len(reply.encode("utf-16-le")) <= 8192
    assert bot.send_message.call_args.kwargs["parse_mode"] is None
    if len(text.encode("utf-16-le")) <= 8192:
        assert reply == text
    else:
        assert reply.endswith("[truncated]")


def test_empty_configured_secret_fails_closed(client, monkeypatch, remote_boundaries):
    create, bot, _ = remote_boundaries
    monkeypatch.setattr(settings, "telegram_webhook_secret_token", "")
    response = client.post("/webhooks/telegram", json=payload(), headers={
        "X-Telegram-Bot-Api-Secret-Token": ""})
    assert response.status_code == 401
    create.assert_not_called()
    bot.send_message.assert_not_awaited()
