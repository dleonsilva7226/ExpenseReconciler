"""Agent engine (D5, per A3): the provider-agnostic tool-call loop.

Two entry points, per A3's real behavioral split rather than one
generic "call an LLM" function that silently picks a provider:

- `run_interactive_query` - GPT-4o-mini, on-demand Telegram questions,
  backed by the three read-only tools in `app/agent/tools.py`.
- `run_weekly_triage` - Gemini 1.5 Flash, the weekly digest job; the
  full week's transactions/accounts are handed to the model directly
  rather than through the tool round trip, leaning on Gemini's larger
  context window (R3) instead of needing to pre-summarize.

Neither writes to the database - this stays strictly read/reason/reply,
per A3.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any

from starlette.concurrency import run_in_threadpool

from app.agent.providers.base import LLMProvider, LLMResponse, Message, Tool
from app.agent.providers.gemini_provider import GeminiProvider
from app.agent.providers.openai_provider import OpenAIProvider
from app.agent.tools import TOOL_IMPLEMENTATIONS, TOOLS
from app.config import settings

# Read-only lookup tools are cheap and low-risk to retry, but the loop
# still needs a hard ceiling so a confused model can't spin forever.
_MAX_TOOL_TURNS = 4


def _json_default(value: Any) -> Any:
    """`Decimal`/`date` aren't JSON-serializable; tool results are
    fed back to the model as plain text, so stringify anything the
    default encoder can't handle."""
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


async def _run_tool_loop(
    provider: LLMProvider,
    prompt: str,
    tools: list[Tool],
    tool_impls: dict[str, Callable[..., Awaitable[Any]]],
) -> str:
    """The round-trip loop A3 assigns to `engine.py`: call the
    provider, execute any tool calls it asks for, re-prompt with the
    result, repeat until it returns a final text answer (or the turn
    ceiling is hit). Identical in shape regardless of provider -
    `provider` is the only thing that changes between the two entry
    points below.
    """
    history: list[Message] = []

    for _ in range(_MAX_TOOL_TURNS):
        response: LLMResponse = await run_in_threadpool(provider.run, prompt, tools, history)

        if not response.requires_tool_execution:
            return response.text or ""

        history.append(Message(role="assistant", content=response.text or ""))

        for call in response.tool_calls:
            impl = tool_impls.get(call.tool_name)
            if impl is None:
                result_text = f"Error: unknown tool '{call.tool_name}'"
            else:
                try:
                    result = await impl(**call.arguments)
                    result_text = json.dumps(result, default=_json_default)
                except Exception as exc:  # noqa: BLE001 - reported to the model, not raised
                    result_text = f"Error executing '{call.tool_name}': {exc}"
            history.append(Message(role="tool", name=call.tool_name, content=result_text))

    return "I wasn't able to finish answering that after several tool calls - try rephrasing."


async def run_interactive_query(user_message: str) -> str:
    """GPT-4o-mini path (A3): on-demand Telegram questions against the
    three read-only finance tools in `app/agent/tools.py`."""
    provider = OpenAIProvider(api_key=settings.openai_api_key)
    return await _run_tool_loop(provider, user_message, TOOLS, TOOL_IMPLEMENTATIONS)


async def run_weekly_triage(transactions: list[dict], accounts: list[dict]) -> str:
    """Gemini 1.5 Flash path (A3): the weekly digest job. The data is
    handed to the model directly (no tool round trip) - it's already
    been fetched by the caller (A4's digest job), and Gemini's larger
    context window means it doesn't need pre-summarizing first (R3)."""
    provider = GeminiProvider(api_key=settings.gemini_api_key)
    prompt = (
        "You are a personal finance triage assistant. Review the past "
        "week's credit accounts and transactions below and produce a "
        "short, plain-text summary: notable spending, any accounts "
        "approaching their credit limit, and anything that looks "
        "unusual. Be concise - this is sent as a single Telegram "
        "message.\n\n"
        f"Accounts:\n{json.dumps(accounts, default=_json_default)}\n\n"
        f"Transactions:\n{json.dumps(transactions, default=_json_default)}"
    )
    response = await run_in_threadpool(provider.run, prompt, [], [])
    return response.text or ""
