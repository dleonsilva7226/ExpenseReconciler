Authorized Telegram text messages previously stopped after webhook checks. D7 now acknowledges those updates, runs the interactive finance agent in a background task, and sends its plain-text answer to the same allowlisted chat.

Preserves webhook-secret and chat-ID checks, adds /start and /help guidance, ignores non-text updates, contains agent/delivery failures, and bounds Unicode replies to Telegram's message limit. Unknown commands return guidance; /digest does not trigger the weekly job.

Validation covers the real engine and OpenAI adapter with mocked LLM, tool, and Telegram calls, including a tool-call round trip, acknowledgment before the LLM call, chat isolation, failures, resource cleanup, and reply-length boundaries. Full test and lint results are recorded in the QA report.

Background work remains in-process without durable delivery, retries, or update deduplication. Live integrations are untested. Dashboard work and weekly-digest deployment, scheduling, credentials, and linked bank data remain outside this PR.

Validation: 138 tests passed; ruff check . passed.
