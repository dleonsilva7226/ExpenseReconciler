---
role: researcher
status: draft
depends_on: []
supersedes: []
---

# Findings: Telegram Bot API Delivery Patterns (R2)

**Task:** webhook setup, message formatting/length limits, rate limits relevant to the weekly digest — feeds A4.

## Webhook requirements

Telegram webhooks require HTTPS on one of a fixed set of ports (443,
80, 88, 8443) — no plaintext HTTP is possible. Render's free web
service provides HTTPS automatically on its `*.onrender.com` subdomain
via standard port 443, so this is compatible with the R5 hosting
decision with no extra TLS setup needed.

## Message limits (directly relevant to the digest format)

- **4,096 characters** max per text message.
- **1,024 characters** max per media caption.
- 64-byte limit on `callback_data` (relevant only if the digest ever
  uses inline buttons — not currently planned).

**Implication for A4:** the weekly digest content must either fit
within 4,096 characters, or be deliberately split into multiple
messages if a week's transaction summary could run long. Given this is
a personal account (not tracking hundreds of transactions/week), a
single message is very likely sufficient, but A4 should decide this
explicitly (e.g. "summarize, don't enumerate every transaction") rather
than risk an unhandled Telegram API error if the message ever exceeds
the limit.

## Rate limits

~30 messages/sec to different users, ~1 message/sec per chat. Not a
meaningful constraint at this project's scale (one chat, one message a
week) — noting for completeness, not because it changes any design
decision.

## Library

`python-telegram-bot` is a standard, actively maintained choice (also
already assumed in A5/O2's dependency notes) — confirms rather than
changes that assumption.

## `allowed_updates`

The webhook registration (`setWebhook`) can restrict which update
types get delivered (e.g. just `message`) rather than receiving every
event type Telegram supports. Minor implementation detail for D4 to
apply, not significant enough to warrant reopening the already-approved
A2 spec.

## Recommendation (non-binding)

1. Digest content should be composed as a single message where
   possible, with an explicit summarization strategy (e.g., top N
   categories/merchants, not a line per transaction) rather than
   assuming length is a non-issue.
2. `setWebhook` should pass `allowed_updates=["message"]` to reduce
   unnecessary webhook traffic (helps slightly with Render's
   spin-down/cold-start pattern too — fewer wake-ups from irrelevant
   update types like `edited_message` or `chat_member`).

Formalizing the digest format belongs to Architect ticket **A4**.

## Sources

- [Telegram Bot API](https://core.telegram.org/bots/api)
- [Telegram Bot API Limits 2026: Rate, Size & Length](https://www.conferbot.com/limits/telegram)
- [Marvin's Marvellous Guide to All Things Webhook](https://core.telegram.org/bots/webhooks)
