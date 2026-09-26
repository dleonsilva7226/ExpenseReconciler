"""OpenAI (`gpt-4o-mini`) provider adapter (D5, per A3/R3).

Translates the canonical `Tool`/`Message` shapes to/from OpenAI's Chat
Completions wire format (`tools=[{"type": "function", "function":
{...}}]`). Per R3: custom function tools are not auto-executed by
OpenAI on the standard API - the manual call -> execute -> re-prompt
loop lives in `app/agent/engine.py`; this module only translates
shapes in both directions.
"""

from __future__ import annotations

import json

from openai import OpenAI

from app.agent.providers.base import LLMResponse, Message, Tool, ToolCall

_DEFAULT_MODEL = "gpt-4o-mini"


class OpenAIProvider:
    """`LLMProvider` implementation for OpenAI's Chat Completions API."""

    def __init__(self, api_key: str, model: str = _DEFAULT_MODEL) -> None:
        self._client = OpenAI(api_key=api_key)
        self._model = model
        # OpenAI's wire format correlates a tool result back to the
        # call that requested it via a `tool_call_id` the canonical
        # `ToolCall` (A3) deliberately doesn't carry. Tracked here,
        # keyed by tool name, from the most recently seen assistant
        # turn - engine.py's loop always executes every call from one
        # turn before calling `run()` again, so this is a safe,
        # OpenAI-only implementation detail, invisible to engine.py.
        self._pending_tool_calls: list[dict] = []

    def run(self, prompt: str, tools: list[Tool], history: list[Message]) -> LLMResponse:
        messages: list[dict] = [{"role": "user", "content": prompt}]
        messages.extend(self._to_openai_message(message) for message in history)

        request_kwargs: dict = {"model": self._model, "messages": messages}
        if tools:
            request_kwargs["tools"] = [self._to_openai_tool(tool) for tool in tools]

        response = self._client.chat.completions.create(**request_kwargs)
        choice_message = response.choices[0].message

        if choice_message.tool_calls:
            self._pending_tool_calls = [
                {
                    "id": tool_call.id,
                    "type": "function",
                    "function": {
                        "name": tool_call.function.name,
                        "arguments": tool_call.function.arguments,
                    },
                }
                for tool_call in choice_message.tool_calls
            ]
            return LLMResponse(
                text=choice_message.content,
                tool_calls=[
                    ToolCall(
                        tool_name=tool_call.function.name,
                        arguments=json.loads(tool_call.function.arguments or "{}"),
                    )
                    for tool_call in choice_message.tool_calls
                ],
            )

        return LLMResponse(text=choice_message.content or "")

    @staticmethod
    def _to_openai_tool(tool: Tool) -> dict:
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            },
        }

    def _to_openai_message(self, message: Message) -> dict:
        if message.role == "tool":
            call_id = self._call_id_for(message.name)
            return {
                "role": "tool",
                "tool_call_id": call_id,
                "content": message.content,
            }

        if message.role == "assistant" and self._pending_tool_calls:
            # Reconstruct the tool_calls array OpenAI requires on the
            # assistant turn that precedes any "tool" role messages
            # (see `_pending_tool_calls` above).
            return {
                "role": "assistant",
                "content": message.content or None,
                "tool_calls": self._pending_tool_calls,
            }

        return {"role": message.role, "content": message.content}

    def _call_id_for(self, tool_name: str | None) -> str:
        for call in self._pending_tool_calls:
            if call["function"]["name"] == tool_name:
                return call["id"]
        return tool_name or ""
