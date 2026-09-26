"""Gemini (`gemini-1.5-flash`) provider adapter (D5, per A3/R3).

Translates the canonical `Tool`/`Message` shapes to/from Gemini's
`tools=[{"function_declarations": [...]}]` wire format. Per R3: like
OpenAI, Gemini's custom function tools are not auto-executed - the
manual call -> execute -> re-prompt loop lives in `app/agent/engine.py`;
this module only translates shapes in both directions.
"""

from __future__ import annotations

import google.generativeai as genai

from app.agent.providers.base import LLMResponse, Message, Tool, ToolCall

_DEFAULT_MODEL = "gemini-1.5-flash"


class GeminiProvider:
    """`LLMProvider` implementation for the Gemini API."""

    def __init__(self, api_key: str, model: str = _DEFAULT_MODEL) -> None:
        genai.configure(api_key=api_key)
        self._model_name = model

    def run(self, prompt: str, tools: list[Tool], history: list[Message]) -> LLMResponse:
        model_kwargs: dict = {"model_name": self._model_name}
        if tools:
            model_kwargs["tools"] = [self._to_gemini_tools(tools)]
        model = genai.GenerativeModel(**model_kwargs)

        contents: list[dict] = [{"role": "user", "parts": [prompt]}]
        contents.extend(self._to_gemini_content(message) for message in history)

        response = model.generate_content(contents)
        candidate_parts = response.candidates[0].content.parts

        tool_calls: list[ToolCall] = []
        text_parts: list[str] = []
        for part in candidate_parts:
            function_call = getattr(part, "function_call", None)
            if function_call and function_call.name:
                tool_calls.append(
                    ToolCall(
                        tool_name=function_call.name,
                        arguments=dict(function_call.args),
                    )
                )
            elif getattr(part, "text", None):
                text_parts.append(part.text)

        return LLMResponse(text="\n".join(text_parts) or None, tool_calls=tool_calls)

    @staticmethod
    def _to_gemini_tools(tools: list[Tool]) -> dict:
        return {
            "function_declarations": [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                }
                for tool in tools
            ]
        }

    @staticmethod
    def _to_gemini_content(message: Message) -> dict:
        if message.role == "tool":
            return {
                "role": "function",
                "parts": [
                    {
                        "function_response": {
                            "name": message.name,
                            "response": {"result": message.content},
                        }
                    }
                ],
            }
        role = "model" if message.role == "assistant" else "user"
        return {"role": role, "parts": [message.content]}
