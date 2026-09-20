"""Pydantic schemas for the finance domain (D2, per A2).

Inbound webhook payload shapes only. `NormalizedTransaction` lives in
`app/integrations/bank/base.py` per A2's module boundaries, not here —
this module must not import anything Plaid-specific.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class PlaidWebhookPayload(BaseModel):
    """Validates the fields this app actually acts on. `extra="allow"`
    because Plaid's webhook bodies carry additional fields per
    webhook_type that aren't needed here."""

    model_config = ConfigDict(extra="allow")

    webhook_type: str
    webhook_code: str
    item_id: str


class TelegramChat(BaseModel):
    id: int


class TelegramMessage(BaseModel):
    model_config = ConfigDict(extra="allow")

    message_id: int
    chat: TelegramChat
    text: str | None = None


class TelegramUpdate(BaseModel):
    """Standard Telegram Bot API update shape, scoped to what the
    gateway needs to check the chat-ID allowlist. Command-specific
    fields belong to A4/D6, not here."""

    model_config = ConfigDict(extra="allow")

    update_id: int
    message: TelegramMessage | None = None
