---
role: qa
status: in-review
depends_on: [docs/agent-artifacts/developer/2026-09-26-d5-pr.md, docs/agent-artifacts/developer/2026-09-27-d6-pr.md, docs/agent-artifacts/architect/2026-09-20-agent-tool-execution-spec.md, docs/agent-artifacts/architect/2026-09-20-weekly-triage-job-spec.md]
supersedes: []
---

# Test Report: Q2 — D5 (agent engine) / D6 (weekly digest job) coverage

**Branch:** `qa/d5-d6-tests`.
**Scope:** `app/agent/**` (D5) and `app/jobs/**` (D6) had zero test
coverage before this ticket — everything in `tests/` predated Q1
(D1-D4 only). This closes that gap.

## Files added / changed

New:
- `tests/agent/__init__.py`, `tests/agent/providers/__init__.py`, `tests/jobs/__init__.py`
- `tests/agent/test_tools.py` — 9 tests
- `tests/agent/test_engine.py` — 9 tests
- `tests/agent/providers/test_openai_provider.py` — 8 tests
- `tests/agent/providers/test_gemini_provider.py` — 10 tests
- `tests/jobs/test_weekly_finance_audit.py` — 15 tests

Modified (appended to, not restructured — same file, same
conventions):
- `tests/gateway/test_router.py` — +6 tests (`/jobs/weekly-digest/trigger`)
- `tests/domains/finance/test_models.py` — +3 tests (`DigestLog`)

No changes to `requirements.txt` — `pytest`, `pytest-asyncio`,
`pytest-mock`, `httpx2` (from Q1) were sufficient; `openai` and
`google-generativeai` (D5) and `python-telegram-bot` (D6) were already
present for the app code these tests exercise.

## Why prioritized this way

Per the ticket, this is the riskiest untested code in the app: real
money categorization going to an LLM, and real Telegram sends to the
user's own chat. Priority order followed the ticket's own ranking:

1. **`weekly_finance_audit.py`'s idempotency check** (highest — a bug
   here means double-spending real API quota/Telegram sends on a
   duplicate cron fire). Both the already-sent short-circuit and the
   fresh-period path are covered, with explicit `assert_not_awaited()`
   checks on every expensive dependency (transaction query, account
   summary, `run_weekly_triage`, `Bot.send_message`) in the
   already-sent case — not just "the DigestLog row wasn't written
   twice," but that none of the *work* re-ran either.
2. **`POST /jobs/weekly-digest/trigger`** — auth (missing header,
   wrong bearer token, wrong scheme) and response pass-through (both
   the `sent: true` and `sent: false` shapes), matching the existing
   `tests/gateway/test_router.py` conventions (`client` fixture,
   `router_module` monkeypatching, `fake_async_session_factory`).
3. **`engine.py`'s tool-call loop`** — `_run_tool_loop` tested directly
   with a stub `LLMProvider` (no-tool-call path, tool-call-then-final
   round trip, unknown-tool handling, tool-exception handling, and the
   `_MAX_TOOL_TURNS` ceiling), plus both entry points
   (`run_interactive_query`/`run_weekly_triage`) with `OpenAIProvider`/
   `GeminiProvider` swapped for stubs.
4. **`tools.py`'s three tools** — each confirmed to call the right
   `finance_service` read path with parsed dates/passed-through
   filters, and to return the shape its own `Tool` schema promises
   (including `get_transactions`'s dict-shaping of ORM rows).
5. **Provider adapters** (`openai_provider.py`/`gemini_provider.py`) —
   wire-format translation both directions, with the OpenAI/Gemini SDK
   objects entirely mocked (`OpenAI`/`genai` swapped for `MagicMock`s).
   Includes the documented tricky bit: OpenAI's `tool_call_id`
   correlation reconstruction across a two-turn history round trip.
6. **`DigestLog`'s uniqueness constraint** — same style as Q1's D2
   model checks (introspecting `__table__`, no engine/DB needed).

## Verification (actually run, not assumed)

- Environment: this environment's default `python3` is 3.8 (same
  constraint the D5/D6 status notes flagged — pydantic v2's `X | None`
  syntax needs 3.10+). Built a throwaway venv against
  `/opt/homebrew/bin/python3.11` in this session's scratchpad
  directory (not `/tmp`, not committed) and installed
  `requirements.txt` as-is — resolved cleanly, no version changes
  needed.
- **Full suite: `pytest -q` → 107 passed, 0 failed** (47 pre-existing
  D1-D4 tests + 60 new). One pre-existing warning
  (`google.generativeai`'s deprecation `FutureWarning`, already flagged
  in the D5 status note — not something this ticket introduces or is
  scoped to fix).
- `ruff check tests/` → clean (two lint issues in my own new files —
  an unsorted import block in `test_engine.py`, an unnecessary `dict()`
  call in `test_tools.py` — fixed before commit).
- No real OpenAI/Gemini/Telegram/Postgres credentials or network calls
  anywhere in the new tests: `OpenAI`/`genai` SDK objects are replaced
  with `MagicMock`s at the call site the provider adapters construct
  them from; `Bot` is replaced with a `MagicMock` + `AsyncMock`
  `send_message`; every `AsyncSession` is a hand-rolled fake (matching
  `tests/conftest.py`'s existing `FakeAsyncSession` idiom, not a real
  engine) or, in `tests/agent/test_tools.py`/`test_engine.py`, the
  module's own `async_session_factory` is monkeypatched to a fake
  async-context-manager rather than left pointing at the real
  (fake-but-asyncpg-shaped) `DATABASE_URL` from `conftest.py`.

## Result

**All new and pre-existing tests pass. No bug-reports filed** — no
real defect was found in `app/agent/**` or `app/jobs/**` during this
pass. One thing worth the Manager's attention, not a bug:

- The `google.generativeai` deprecation warning (flagged by D5's
  status note, and visible again in this suite's run) is now also
  visible to CI/QA runs going forward — still not urgent for a
  personal project per that note, but a real one to eventually route
  to Architect/DevOps as a migration ticket to `google-genai`. Not
  filed as a bug-report since it isn't a defect in current behavior.

## Coverage notes / what's intentionally NOT covered

- `weekly_finance_audit.py`'s `_serialize_transaction` is exercised
  indirectly (via `run_weekly_digest`'s fresh-period test with empty
  transaction lists) but not with a populated, realistic transaction
  list asserting on serialized field values — the job-level tests
  focus on the idempotency/side-effect-ordering guarantees per the
  ticket's priority #1, not exhaustive serialization coverage. Low
  risk: the function is a straightforward dict literal with no
  branching.
- The real Telegram `Bot.send_message` call's own error handling (e.g.
  a network failure mid-send) isn't tested — out of scope per the
  ticket ("mock external calls"); would require Researcher/Architect
  input on what retry/failure behavior is even wanted before QA could
  test a specific contract.
- `OpenAIProvider`'s documented limitation (tool-call-id correlation
  only guarantees correctness for the most recently completed turn,
  not arbitrarily deep multi-round history — per the D5 status note)
  is exercised for the one-round-trip case the tools actually need,
  not stress-tested against a deeper multi-round history, since the
  status note already flags that as a known, accepted simplification
  rather than an open question QA needs to re-litigate.

## Requires User Approval

None. No schema change, no `app/**`/`main` write, no destructive
action — this PR is `tests/**` only, on QA's own branch, per Section
3.6's git carve-out.
