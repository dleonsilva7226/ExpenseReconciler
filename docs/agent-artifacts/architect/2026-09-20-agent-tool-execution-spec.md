---
role: architect
status: approved
depends_on: [docs/agent-artifacts/researcher/2026-09-20-openai-gemini-tool-calling.md, docs/agent-artifacts/architect/2026-09-20-finance-schema-spec.md]
supersedes: []
---

**Approved by user, 2026-09-20** — explicitly endorsing fixed,
deterministic parameterized queries over any text-to-SQL tool.

# Spec (A3): Agent Tool-Execution Interface

## Input

R3 recommends: one canonical internal tool schema, two thin
provider adapters (OpenAI, Gemini) translating to/from it, and two
distinct entry points on the engine reflecting a real behavioral split
(interactive/small-context vs. weekly/large-context), not a single
generic "call an LLM" function.

## Module boundaries

```text
app/agent/
├── engine.py          # run_interactive_query(), run_weekly_triage()
├── tools.py            # canonical Tool definitions + the read-only SQL functions
└── providers/
    ├── base.py         # canonical Tool / ToolCall dataclasses, LLMProvider Protocol
    ├── openai_provider.py
    └── gemini_provider.py
```

`providers/` is new relative to `PLAN.md`'s tree, mirroring
`app/integrations/bank/` from A2 — same reasoning: keep vendor-specific
wire formats out of `engine.py` and `tools.py` entirely.

## Canonical types (`providers/base.py`)

```python
class Tool(BaseModel):
    name: str
    description: str
    parameters: dict  # JSON Schema

class ToolCall(BaseModel):
    tool_name: str
    arguments: dict

class LLMProvider(Protocol):
    def run(self, prompt: str, tools: list[Tool], history: list[Message]) -> LLMResponse: ...
```

`LLMResponse` carries either a final text answer or one/more
`ToolCall`s for `engine.py` to execute and feed back — the round-trip
loop (call → execute → re-prompt with result) lives in `engine.py`,
identical in shape regardless of provider; only `openai_provider.py`
and `gemini_provider.py` know about `tools=[{"type":"function",...}]`
vs. `tools=[{"function_declarations":[...]}]` wire formats.

## Tools exposed (`tools.py`)

**All tools are read-only.** No tool executes arbitrary SQL or accepts
free-text-to-SQL from the model — each is a fixed, named, parameterized
query function. This is a deliberate security boundary: an LLM-driven
arbitrary-SQL tool against a database holding real financial data and
(per A1) an encrypted secret column is not an acceptable risk for the
value it'd add here.

| tool | parameters | returns |
|---|---|---|
| `get_transactions` | `account_id?`, `start_date`, `end_date`, `category?` | list of transactions matching filters |
| `get_account_summary` | `account_id?` | balance/limit/utilization per `CreditAccount` (or all accounts if omitted) |
| `get_spending_by_category` | `start_date`, `end_date` | aggregated totals per category |

Each is a plain async function over `app/domains/finance/service.py`
(read paths only — no ingestion functions exposed as tools), wrapped
with a `Tool` schema for the provider adapters to advertise.

## Engine entry points

- **`run_interactive_query(user_message: str) -> str`** — GPT-4o-mini,
  used for on-demand Telegram questions (small context, low latency
  appropriate).
- **`run_weekly_triage(transactions: list[...], accounts: list[...]) -> str`**
  — Gemini 1.5 Flash, used by the weekly digest job (A4), leaning on
  the larger context window to reason over a fuller week of data at
  once rather than needing to pre-summarize before handing it to the
  model.

Both return plain text (the response to send back over Telegram);
neither writes to the database — this stays strictly read/reason/reply.

## Requires User Approval

None — design only.
