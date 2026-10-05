---
role: qa
status: in-review
depends_on: [docs/agent-artifacts/manager/2026-10-05-d7-qa-handoff.md, docs/agent-artifacts/developer/2026-10-05-d7-status-note.md, docs/agent-artifacts/architect/2026-09-20-webhook-ingestion-contract.md, docs/agent-artifacts/architect/2026-09-20-agent-tool-execution-spec.md]
supersedes: []
---

# D7 independent QA test report

Validated Developer commit 355e67e on the shared dev/d7-telegram-interactive checkout. No application files, infrastructure, branch, commits, or pushes changed by QA. Added 19 independently executed cases in tests/gateway/test_d7_flow_qa.py. Ready for Manager review and Developer integration into the D7 PR.

## Actual results

`/workspace/cloud-setup/venv/bin/python -m pytest -q`: **138 passed**, 2 warnings (1.69 seconds).

`/workspace/cloud-setup/venv/bin/ruff check .`: **All checks passed**.

QA corrected an import ordering lint finding in its own test file before the final checks. No D7 application defects found; no bug-report required.

## Evidence

- HTTP webhook traverses the real gateway background handler, real run_interactive_query, real engine tool loop and real OpenAI adapter. Only external SDK, finance tool and Telegram Bot boundaries are mocked. The first mocked SDK completion requests get_account_summary; the async tool receives its exact account argument, its Decimal result is serialized back to a second model request, OpenAI assistant/tool call correlation is verified, and the final plain text reaches exactly the inbound allowlisted chat with parse_mode=None. Advertised tools are exactly the three approved read-only tools, and the model is gpt-4o-mini.
- Direct ASGI send recording proves both HTTP 200 response start and final acknowledgment body have been sent before the first LLM SDK call. This specifically avoids drawing acknowledgment timing conclusions from TestClient, which waits for background work.
- Unauthorized requests reject malformed bodies with 401 before parsing. Authenticated malformed JSON and schema-invalid JSON produce generic 422. Empty configured webhook secret fails closed. Other chat IDs, blank messages, non-text messages and callback-only updates invoke neither LLM nor Bot.
- /start and /help (with additional arguments) produce guidance without model calls; /digest and addressed /help commands produce unknown-command guidance, following the Manager-accepted command policy.
- A real provider SDK exception produces only generic retry-later text, never sensitive exception data in logs. A Telegram send exception is contained without a second model request. Both cases verify Bot context exit, as does successful delivery.
- Replies through the actual HTTP/engine/delivery path respect 4096 UTF-16 units for exact and overflowing ASCII, emoji and combining-character inputs, preserve unchanged in-range replies and mark truncation. Existing Developer tests additionally cover empty model answers and other gateway failure cases.

## Limits and operational boundaries

Remote Telegram/OpenAI/Plaid calls and DB reads were mocked; no credentials, linked bank data, scheduling, live delivery or deployment validated. No dashboard work or weekly digest changes. The process-local BackgroundTasks durability/retry/deduplication limits remain as documented by Developer and accepted for this scope.

The existing deprecated google.generativeai import warns during collection; FastAPI's legacy HTTP_422_UNPROCESSABLE_ENTITY symbol warns in the malformed-input check. Neither causes failures. No dependency or application change made by QA.

Unrelated untracked onboarding artifacts preserved. Only QA's new test and this report are intended for D7 integration.
