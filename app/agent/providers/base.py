"""Canonical agent types + `LLMProvider` Protocol (D5, per A3).

`Tool` / `ToolCall` / `Message` / `LLMResponse` are the only shapes
`app/agent/engine.py` and `app/agent/tools.py` ever see. Only
`openai_provider.py` and `gemini_provider.py` know about each vendor's
own wire format (`tools=[{"type": "function", ...}]` vs.
`tools=[{"function_declarations": [...]}]`, per R3) - translating to
and from these canonical types is the entire job of a provider
adapter; none of that vendor-specific shape leaks past this module.
"""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, Field


class Tool(BaseModel):
    """One callable the model may invoke, advertised in its own
    JSON-schema `parameters` shape (A3)."""

    name: str
    description: str
    parameters: dict  # JSON Schema, e.g. {"type": "object", "properties": {...}}


class ToolCall(BaseModel):
    """One invocation the model asked for, in canonical form (A3)."""

    tool_name: str
    arguments: dict


class Message(BaseModel):
    """One turn of the conversation `engine.py`'s round-trip loop
    re-prompts a provider with, including a tool's result being
    reported back (`role="tool"`).

    A3 references `history: list[Message]` on `LLMProvider.run` but
    doesn't spell out `Message` itself beyond that name - this is the
    minimal shape that supports it: a role plus content, with
    `tool_call_id`/`name` present only on `role="tool"` messages so a
    provider adapter can address a result back to the call it answers
    (OpenAI needs a `tool_call_id`; Gemini correlates by `name`
    instead - each adapter handles that translation internally, per
    A3's module boundary).
    """

    role: Literal["user", "assistant", "tool"]
    content: str
    tool_call_id: str | None = None
    name: str | None = None


class LLMResponse(BaseModel):
    """Either a final text answer, or one/more tool calls for
    `engine.py` to execute and feed back (A3: "LLMResponse carries
    either a final text answer or one/more ToolCalls")."""

    text: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)

    @property
    def requires_tool_execution(self) -> bool:
        return bool(self.tool_calls)


class LLMProvider(Protocol):
    """Implemented by `OpenAIProvider` (openai_provider.py) and
    `GeminiProvider` (gemini_provider.py). `engine.py`'s round-trip
    loop is identical in shape regardless of which one it's holding."""

    def run(
        self, prompt: str, tools: list[Tool], history: list[Message]
    ) -> LLMResponse: ...
