---
role: researcher
status: draft
depends_on: []
supersedes: []
---

# Findings: OpenAI vs. Gemini Tool-Calling for the Agent Engine (R3)

**Task:** how `gpt-4o-mini` and `gemini-1.5-flash` should split responsibilities in `app/agent/engine.py`, and what each SDK's tool-calling contract looks like — feeds A3.

## Mechanics

Both providers support the same basic shape (a JSON-schema tool/function declaration, the model emits a structured call, the app executes it and feeds the result back) but with different wire formats:

- **OpenAI (`gpt-4o-mini`):** `tools=[{"type": "function", "function": {name, description, parameters}}]`. Response includes `tool_calls`; the app must execute the named function itself and send a follow-up message with the result — there is no built-in auto-execution for custom functions.
- **Gemini (`gemini-1.5-flash`):** `tools=[{"function_declarations": [{name, description, parameters}]}]`. Response includes `tool_use`/function-call parts that must similarly be parsed and executed manually.

Some marketing material implies OpenAI "auto-executes" tools — that's not accurate for custom function tools on the standard Chat Completions API (it may refer to OpenAI's separately hosted built-in tools like web search, not applicable here). Treat both providers as requiring the same manual call → execute → feed-back-result loop; don't build engine.py assuming one is more automatic than the other.

## Why the plan splits them this way (confirmed, not just assumed)

`PLAN.md` assigns `gpt-4o-mini` to "tool execution/ingest" and `gemini-1.5-flash` to "high-context analytical triage." This holds up:

- **Context window:** Gemini 1.5 Flash supports up to ~1M tokens vs. GPT-4o-mini's 128K. For the weekly digest — which may want to reason over a large batch of transaction history at once — that's a real, material advantage, not a marginal one.
- **Cost:** Gemini Flash runs roughly 1.5x cheaper per token than GPT-4o-mini for both input and output — reinforces using it for the larger-context, less latency-sensitive weekly job rather than the more interactive/on-demand path.
- **On-demand tool execution** (e.g. answering an ad-hoc Telegram question against the read-only SQL tools) fits GPT-4o-mini's smaller-context, lower-latency profile fine — no need for a 1M-token window for a single question.

## Recommendation (non-binding)

1. Define one **canonical internal tool schema** (name, description, JSON-schema parameters, a Python callable) in `app/agent/tools.py` — this is what the read-only SQL tools actually are.
2. Two thin adapters translate that canonical schema into each provider's wire format and parse each provider's response back into one canonical `ToolCall` shape the engine's execution loop runs against. This mirrors the same "no hardcoded per-vendor logic in the core loop" pattern already used for `BankConnector` in A2 — same shape of problem, same fix.
3. `app/agent/engine.py` exposes something like `run_interactive_query(...)` (GPT-4o-mini path, used for Telegram on-demand questions) and `run_weekly_triage(...)` (Gemini path, used by the digest job) rather than one generic "call an LLM" function that silently picks a provider — the split is a real behavioral difference (context budget, latency, cost), not an implementation detail to hide.

Formalizing this belongs to Architect ticket **A3**.

## Sources

- [GPT-4o mini & Gemini 1.5 Flash: The Real Math Behind Slashing LLM Inference Costs](https://dev.to/unfiltered_anshul/gpt-4o-mini-gemini-15-flash-the-real-math-behind-slashing-llm-inference-costs-504h)
- [Gemini function calling vs OpenAI function calling: Key differences and examples](https://theneuralbase.com/gemini/qna/gemini-function-calling-vs-openai-function-calling/)
- [GPT-4o Mini vs Gemini 1.5 Flash (002) - Detailed Performance & Feature Comparison](https://docsbot.ai/models/compare/gpt-4o-mini/gemini-1-5-flash-002)
