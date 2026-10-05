---
role: manager
status: approved
depends_on: [docs/agent-artifacts/architect/2026-09-20-webhook-ingestion-contract.md, docs/agent-artifacts/architect/2026-09-20-agent-tool-execution-spec.md]
supersedes: []
---

Implement D7 from main 92741d9 per explicit user instruction. A2 and A3 headers are approved; Developer build gate is satisfied. Telegram remains the main interface; dashboard, deployment, scheduling and live digest delivery are deferred.

Developer: complete authenticated, chat-allowlisted Telegram text dispatch to the existing interactive engine and plain-text Bot reply, with defined commands, non-text and error behavior and Telegram message limits. Work inside existing approved module boundaries; report any genuine spec gap rather than inventing new modules/dependencies. Use a D7 feature branch in the existing checkout, preserve onboarding artifacts, and do not merge, deploy, or touch main. Implement and run relevant checks, then write a Developer status note. Do not publish the PR until QA review completes.

QA: after Manager routes Developer status, independently verify webhook-to-real-agent-engine-to-reply with mocked LLM/Telegram calls and any tool/database calls; cover auth rejection, chat isolation, non-text, commands, failure handling and length boundaries. Run full suite and lint and write report/bug artifact. Manager reviews results, routes fixes if needed, commits task artifacts and tests, and opens one D7 PR for review. Keep prior onboarding artifacts out of the PR.
