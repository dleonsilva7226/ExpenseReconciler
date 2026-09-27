"""`OpenAIProvider` adapter tests (D5, per A3): request/response
translation to/from the canonical `Tool`/`ToolCall`/`Message`/
`LLMResponse` shapes. The OpenAI SDK's `OpenAI` client is entirely
mocked at construction time -- no real API calls anywhere here.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from app.agent.providers.base import Message, Tool
from app.agent.providers.openai_provider import OpenAIProvider


def _make_provider(monkeypatch) -> tuple[OpenAIProvider, MagicMock]:
    fake_client = MagicMock()
    monkeypatch.setattr(
        "app.agent.providers.openai_provider.OpenAI", lambda api_key: fake_client
    )
    provider = OpenAIProvider(api_key="test-key")
    return provider, fake_client


def _fake_completion(content=None, tool_calls=None):
    message = MagicMock()
    message.content = content
    message.tool_calls = tool_calls
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


def _fake_tool_call(call_id, name, arguments):
    tool_call = MagicMock()
    tool_call.id = call_id
    tool_call.function.name = name
    tool_call.function.arguments = json.dumps(arguments)
    return tool_call


def test_to_openai_tool_wire_format():
    tool = Tool(
        name="get_transactions",
        description="desc",
        parameters={"type": "object", "properties": {}},
    )

    assert OpenAIProvider._to_openai_tool(tool) == {
        "type": "function",
        "function": {
            "name": "get_transactions",
            "description": "desc",
            "parameters": {"type": "object", "properties": {}},
        },
    }


def test_run_plain_text_response_has_no_tool_calls(monkeypatch):
    provider, fake_client = _make_provider(monkeypatch)
    fake_client.chat.completions.create.return_value = _fake_completion(content="hello there")

    response = provider.run("hi", tools=[], history=[])

    assert response.text == "hello there"
    assert response.tool_calls == []
    assert response.requires_tool_execution is False


def test_run_includes_tools_in_request_when_provided(monkeypatch):
    provider, fake_client = _make_provider(monkeypatch)
    fake_client.chat.completions.create.return_value = _fake_completion(content="ok")
    tool = Tool(name="t", description="d", parameters={"type": "object", "properties": {}})

    provider.run("hi", tools=[tool], history=[])

    _, kwargs = fake_client.chat.completions.create.call_args
    assert kwargs["tools"] == [OpenAIProvider._to_openai_tool(tool)]


def test_run_omits_tools_key_when_no_tools_given(monkeypatch):
    provider, fake_client = _make_provider(monkeypatch)
    fake_client.chat.completions.create.return_value = _fake_completion(content="ok")

    provider.run("hi", tools=[], history=[])

    _, kwargs = fake_client.chat.completions.create.call_args
    assert "tools" not in kwargs


def test_run_parses_tool_calls_into_canonical_shape(monkeypatch):
    provider, fake_client = _make_provider(monkeypatch)
    fake_client.chat.completions.create.return_value = _fake_completion(
        content=None,
        tool_calls=[
            _fake_tool_call(
                "call_1",
                "get_transactions",
                {"start_date": "2026-09-01", "end_date": "2026-09-26"},
            )
        ],
    )

    response = provider.run("what did I spend?", tools=[], history=[])

    assert response.requires_tool_execution is True
    assert len(response.tool_calls) == 1
    call = response.tool_calls[0]
    assert call.tool_name == "get_transactions"
    assert call.arguments == {"start_date": "2026-09-01", "end_date": "2026-09-26"}


def test_run_parses_tool_call_with_empty_arguments(monkeypatch):
    """`arguments` can be an empty JSON string on the wire (e.g.
    `get_account_summary` with no params) -- must parse to `{}`, not
    raise."""
    provider, fake_client = _make_provider(monkeypatch)
    fake_client.chat.completions.create.return_value = _fake_completion(
        content=None,
        tool_calls=[_fake_tool_call("call_1", "get_account_summary", {})],
    )
    # Simulate the SDK sending an empty string rather than "{}".
    fake_client.chat.completions.create.return_value.choices[0].message.tool_calls[
        0
    ].function.arguments = ""

    response = provider.run("what's my balance?", tools=[], history=[])

    assert response.tool_calls[0].arguments == {}


def test_history_round_trip_reconstructs_tool_call_id_correlation(monkeypatch):
    """OpenAI requires the assistant turn preceding a "tool" message to
    carry a `tool_calls` array with the same id the tool result's
    `tool_call_id` refers back to. The canonical `ToolCall`/`Message`
    (A3) deliberately don't carry that id -- `openai_provider.py` must
    reconstruct it itself from the most recently seen turn (per the D5
    status note's documented implementation choice)."""
    provider, fake_client = _make_provider(monkeypatch)
    fake_client.chat.completions.create.return_value = _fake_completion(
        content=None,
        tool_calls=[_fake_tool_call("call_abc", "get_account_summary", {})],
    )

    # First turn: model asks for the tool call.
    first = provider.run("what's my balance?", tools=[], history=[])
    assert first.requires_tool_execution is True

    # Second turn: engine.py appends an assistant turn + the tool
    # result to history and calls run() again.
    fake_client.chat.completions.create.return_value = _fake_completion(
        content="Your balance is $42."
    )
    history = [
        Message(role="assistant", content=""),
        Message(role="tool", name="get_account_summary", content='{"balance": 42}'),
    ]
    second = provider.run("what's my balance?", tools=[], history=history)

    assert second.text == "Your balance is $42."
    _, kwargs = fake_client.chat.completions.create.call_args
    sent_messages = kwargs["messages"]
    # sent_messages[0] is the fresh user prompt, [1] the reconstructed
    # assistant turn, [2] the tool result correlated back to call_abc.
    assistant_message = sent_messages[1]
    tool_message = sent_messages[2]
    assert assistant_message["tool_calls"][0]["id"] == "call_abc"
    assert tool_message["role"] == "tool"
    assert tool_message["tool_call_id"] == "call_abc"


def test_plain_user_and_assistant_messages_pass_through_without_tool_calls(monkeypatch):
    provider, fake_client = _make_provider(monkeypatch)
    fake_client.chat.completions.create.return_value = _fake_completion(content="ok")

    history = [Message(role="assistant", content="earlier reply")]
    provider.run("hi again", tools=[], history=history)

    _, kwargs = fake_client.chat.completions.create.call_args
    sent_messages = kwargs["messages"]
    assert sent_messages[1] == {"role": "assistant", "content": "earlier reply"}
