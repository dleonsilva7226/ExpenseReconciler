"""`app/agent/engine.py` tests (D5, per A3): the provider-agnostic
tool-call round-trip loop (`_run_tool_loop`) and its two entry points
(`run_interactive_query`, `run_weekly_triage`). The LLM provider is
always a stub queueing canned `LLMResponse`s -- no real OpenAI/Gemini
SDK call anywhere in this file.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import app.agent.engine as engine_module
import app.agent.tools as tools_module
from app.agent.providers.base import LLMResponse, Tool, ToolCall


class _StubProvider:
    """A bare `LLMProvider`: a queue of canned `LLMResponse`s returned
    in order, one per `run()` call, so a test can script a multi-turn
    tool-call round trip without any real SDK. Records every call's
    args so a test can assert what the loop actually sent back."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def run(self, prompt, tools, history):
        self.calls.append({"prompt": prompt, "tools": tools, "history": list(history)})
        return self._responses.pop(0)


async def _noop_tool(**kwargs):
    return {"ok": True}


# --- _run_tool_loop -----------------------------------------------------------


async def test_run_tool_loop_returns_final_text_when_no_tool_call_requested():
    provider = _StubProvider([LLMResponse(text="the answer")])

    result = await engine_module._run_tool_loop(provider, "hi", [], {})

    assert result == "the answer"
    assert len(provider.calls) == 1


async def test_run_tool_loop_executes_requested_tool_and_feeds_result_back():
    """The core round-trip A3 requires: call -> execute -> re-prompt
    with the result -> return the provider's final text."""
    tool_call = ToolCall(tool_name="get_account_summary", arguments={"account_id": "acct-1"})
    provider = _StubProvider(
        [
            LLMResponse(text=None, tool_calls=[tool_call]),
            LLMResponse(text="Your balance is $42."),
        ]
    )
    tool_impl_calls = []

    async def fake_get_account_summary(**kwargs):
        tool_impl_calls.append(kwargs)
        return [{"account_id": "acct-1", "current_balance": "42.00"}]

    result = await engine_module._run_tool_loop(
        provider,
        "what's my balance?",
        [
            Tool(
                name="get_account_summary",
                description="d",
                parameters={"type": "object", "properties": {}},
            )
        ],
        {"get_account_summary": fake_get_account_summary},
    )

    assert result == "Your balance is $42."
    assert tool_impl_calls == [{"account_id": "acct-1"}]

    assert len(provider.calls) == 2
    second_call_history = provider.calls[1]["history"]
    assert second_call_history[0].role == "assistant"
    assert second_call_history[1].role == "tool"
    assert second_call_history[1].name == "get_account_summary"
    assert json.loads(second_call_history[1].content) == [
        {"account_id": "acct-1", "current_balance": "42.00"}
    ]


async def test_run_tool_loop_reports_unknown_tool_without_raising():
    tool_call = ToolCall(tool_name="not_a_real_tool", arguments={})
    provider = _StubProvider(
        [
            LLMResponse(text=None, tool_calls=[tool_call]),
            LLMResponse(text="done"),
        ]
    )

    result = await engine_module._run_tool_loop(provider, "hi", [], {})

    assert result == "done"
    second_call_history = provider.calls[1]["history"]
    assert "unknown tool" in second_call_history[1].content.lower()


async def test_run_tool_loop_reports_tool_exception_without_raising():
    tool_call = ToolCall(tool_name="boom", arguments={})

    async def failing_tool(**kwargs):
        raise ValueError("kaboom")

    provider = _StubProvider(
        [
            LLMResponse(text=None, tool_calls=[tool_call]),
            LLMResponse(text="done"),
        ]
    )

    result = await engine_module._run_tool_loop(provider, "hi", [], {"boom": failing_tool})

    assert result == "done"
    second_call_history = provider.calls[1]["history"]
    assert "kaboom" in second_call_history[1].content


async def test_run_tool_loop_stops_at_max_turns_if_model_never_finishes():
    tool_call = ToolCall(tool_name="noop", arguments={})
    # More tool-call responses queued than the loop's turn ceiling
    # allows, so hitting the ceiling (not exhausting the queue) is
    # what actually stops the loop.
    provider = _StubProvider(
        [LLMResponse(text=None, tool_calls=[tool_call]) for _ in range(10)]
    )

    result = await engine_module._run_tool_loop(provider, "hi", [], {"noop": _noop_tool})

    assert "try rephrasing" in result.lower()
    assert len(provider.calls) == engine_module._MAX_TOOL_TURNS


# --- run_interactive_query ----------------------------------------------------


async def test_run_interactive_query_uses_openai_provider_and_real_tools(monkeypatch):
    """Confirms `run_interactive_query` wires up `OpenAIProvider` plus
    the real `TOOLS`/`TOOL_IMPLEMENTATIONS` from `tools.py` -- not
    that the tools actually hit a database (that's `test_tools.py`'s
    job)."""
    stub_provider = _StubProvider([LLMResponse(text="final answer")])
    monkeypatch.setattr(engine_module, "OpenAIProvider", lambda api_key: stub_provider)

    result = await engine_module.run_interactive_query("what did I spend on coffee?")

    assert result == "final answer"
    assert stub_provider.calls[0]["prompt"] == "what did I spend on coffee?"
    assert stub_provider.calls[0]["tools"] == engine_module.TOOLS


class _FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


async def test_run_interactive_query_executes_a_real_tool_call_round_trip(monkeypatch):
    """End-to-end through the real `TOOL_IMPLEMENTATIONS` dict (not a
    stub tool), confirming the loop calls the tool the model asked
    for and feeds its result back before returning the final text.
    `finance_service.get_account_summary` and the tool's own session
    factory are mocked -- no real database connection."""
    tool_call = ToolCall(tool_name="get_account_summary", arguments={"account_id": None})
    stub_provider = _StubProvider(
        [
            LLMResponse(text=None, tool_calls=[tool_call]),
            LLMResponse(text="You have one account."),
        ]
    )
    monkeypatch.setattr(engine_module, "OpenAIProvider", lambda api_key: stub_provider)
    monkeypatch.setattr(tools_module, "async_session_factory", lambda: _FakeSession())

    fake_summary = [{"account_id": "acct-1", "current_balance": "0.00"}]
    monkeypatch.setattr(
        tools_module.finance_service,
        "get_account_summary",
        AsyncMock(return_value=fake_summary),
    )

    result = await engine_module.run_interactive_query("what's my balance?")

    assert result == "You have one account."
    assert len(stub_provider.calls) == 2


# --- run_weekly_triage ---------------------------------------------------------


async def test_run_weekly_triage_uses_gemini_provider_and_serializes_data_into_prompt(
    monkeypatch,
):
    stub_provider = _StubProvider([LLMResponse(text="weekly summary")])
    monkeypatch.setattr(engine_module, "GeminiProvider", lambda api_key: stub_provider)

    transactions = [{"account_id": "acct-1", "amount": "12.34"}]
    accounts = [{"account_id": "acct-1", "over_utilization_threshold": True}]

    result = await engine_module.run_weekly_triage(transactions, accounts)

    assert result == "weekly summary"
    call = stub_provider.calls[0]
    # No tool round trip for the weekly path (A3): the caller-supplied
    # data is serialized directly into the prompt instead.
    assert call["tools"] == []
    assert call["history"] == []
    assert "acct-1" in call["prompt"]
    assert "12.34" in call["prompt"]


async def test_run_weekly_triage_returns_empty_string_if_provider_returns_no_text(
    monkeypatch,
):
    stub_provider = _StubProvider([LLMResponse(text=None)])
    monkeypatch.setattr(engine_module, "GeminiProvider", lambda api_key: stub_provider)

    result = await engine_module.run_weekly_triage([], [])

    assert result == ""
