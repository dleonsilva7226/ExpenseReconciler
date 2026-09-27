"""`GeminiProvider` adapter tests (D5, per A3): request/response
translation to/from the canonical `Tool`/`ToolCall`/`Message`/
`LLMResponse` shapes. The `google.generativeai` module is entirely
mocked -- no real API calls anywhere here.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.agent.providers.base import Message, Tool
from app.agent.providers.gemini_provider import GeminiProvider


@pytest.fixture
def fake_genai(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr("app.agent.providers.gemini_provider.genai", fake)
    return fake


def _fake_response(parts):
    candidate = MagicMock()
    candidate.content.parts = parts
    response = MagicMock()
    response.candidates = [candidate]
    return response


def _text_part(text):
    part = MagicMock()
    part.text = text
    part.function_call = None
    return part


def _function_call_part(name, args):
    part = MagicMock()
    part.text = None
    part.function_call.name = name
    part.function_call.args = args
    return part


def test_init_configures_sdk_with_api_key(fake_genai):
    GeminiProvider(api_key="test-key")

    fake_genai.configure.assert_called_once_with(api_key="test-key")


def test_to_gemini_tools_wire_format():
    tool = Tool(
        name="get_transactions",
        description="desc",
        parameters={"type": "object", "properties": {}},
    )

    assert GeminiProvider._to_gemini_tools([tool]) == {
        "function_declarations": [
            {
                "name": "get_transactions",
                "description": "desc",
                "parameters": {"type": "object", "properties": {}},
            }
        ]
    }


def test_run_plain_text_response(fake_genai):
    model_instance = MagicMock()
    model_instance.generate_content.return_value = _fake_response([_text_part("hi there")])
    fake_genai.GenerativeModel.return_value = model_instance

    provider = GeminiProvider(api_key="test-key")
    response = provider.run("hello", tools=[], history=[])

    assert response.text == "hi there"
    assert response.tool_calls == []
    assert response.requires_tool_execution is False


def test_run_includes_tools_kwarg_when_tools_provided(fake_genai):
    model_instance = MagicMock()
    model_instance.generate_content.return_value = _fake_response([_text_part("ok")])
    fake_genai.GenerativeModel.return_value = model_instance
    tool = Tool(name="t", description="d", parameters={"type": "object", "properties": {}})

    provider = GeminiProvider(api_key="test-key")
    provider.run("hi", tools=[tool], history=[])

    _, kwargs = fake_genai.GenerativeModel.call_args
    assert kwargs["tools"] == [GeminiProvider._to_gemini_tools([tool])]


def test_run_omits_tools_kwarg_when_no_tools_given(fake_genai):
    model_instance = MagicMock()
    model_instance.generate_content.return_value = _fake_response([_text_part("ok")])
    fake_genai.GenerativeModel.return_value = model_instance

    provider = GeminiProvider(api_key="test-key")
    provider.run("hi", tools=[], history=[])

    _, kwargs = fake_genai.GenerativeModel.call_args
    assert "tools" not in kwargs


def test_run_parses_function_call_part_into_canonical_tool_call(fake_genai):
    model_instance = MagicMock()
    model_instance.generate_content.return_value = _fake_response(
        [_function_call_part("get_account_summary", {"account_id": "acct-1"})]
    )
    fake_genai.GenerativeModel.return_value = model_instance

    provider = GeminiProvider(api_key="test-key")
    response = provider.run("what's my balance?", tools=[], history=[])

    assert response.requires_tool_execution is True
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].tool_name == "get_account_summary"
    assert dict(response.tool_calls[0].arguments) == {"account_id": "acct-1"}


def test_run_collects_multiple_text_parts_joined_by_newline(fake_genai):
    model_instance = MagicMock()
    model_instance.generate_content.return_value = _fake_response(
        [_text_part("line one"), _text_part("line two")]
    )
    fake_genai.GenerativeModel.return_value = model_instance

    provider = GeminiProvider(api_key="test-key")
    response = provider.run("hi", tools=[], history=[])

    assert response.text == "line one\nline two"


@pytest.mark.parametrize(
    ("role", "expected_role"),
    [("user", "user"), ("assistant", "model")],
)
def test_to_gemini_content_role_mapping(role, expected_role):
    message = Message(role=role, content="hi")

    content = GeminiProvider._to_gemini_content(message)

    assert content["role"] == expected_role
    assert content["parts"] == ["hi"]


def test_to_gemini_content_tool_message_maps_to_function_role_and_response_shape():
    message = Message(role="tool", name="get_account_summary", content='{"balance": 1}')

    content = GeminiProvider._to_gemini_content(message)

    assert content["role"] == "function"
    function_response = content["parts"][0]["function_response"]
    assert function_response["name"] == "get_account_summary"
    assert function_response["response"]["result"] == '{"balance": 1}'
