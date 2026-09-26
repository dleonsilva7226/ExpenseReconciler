"""`app/gateway/router.py` endpoint tests: admin auth-gating on the
`/link-account*` routes (priority 3) and webhook auth on
`/webhooks/plaid` + `/webhooks/telegram` (priority 4) -- Plaid
signature verification rejection, the Telegram chat-ID allowlist (both
"wrong chat silently dropped" and "right chat processed"), and
Telegram's own `secret_token` header rejection.

Uses the `client` fixture (a `TestClient` built without running the
app's lifespan, so no real Postgres connection is attempted -- see
`tests/conftest.py`). Module-level singletons `router.py` builds at
import time (`_plaid_client`, `_bank_connector`, `async_session_factory`)
are monkeypatched per-test wherever a route would otherwise need a real
Plaid/Postgres round trip; nothing here contacts a live service.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import app.gateway.router as router_module

# --- /link-account (GET) : admin auth gating --------------------------------


def test_link_account_page_requires_auth(client):
    response = client.get("/link-account")
    assert response.status_code == 401


def test_link_account_page_rejects_wrong_credentials(client):
    response = client.get("/link-account", auth=("wrong", "creds"))
    assert response.status_code == 401


def test_link_account_page_accepts_correct_credentials(client, admin_auth):
    response = client.get("/link-account", auth=admin_auth)
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


# --- /link-account/token (POST) : admin auth gating -------------------------


def test_create_link_token_requires_auth(client):
    response = client.post("/link-account/token")
    assert response.status_code == 401


def test_create_link_token_accepts_correct_credentials(client, admin_auth, monkeypatch):
    fake_response = type("FakeLinkTokenResponse", (), {"link_token": "link-sandbox-abc123"})()
    monkeypatch.setattr(
        router_module._plaid_client, "link_token_create", lambda request: fake_response
    )

    response = client.post("/link-account/token", auth=admin_auth)

    assert response.status_code == 200
    assert response.json() == {"link_token": "link-sandbox-abc123"}


# --- /link-account/callback (POST) : admin auth gating + per-account insert -


def _callback_body(*account_ids: str) -> dict:
    return {
        "public_token": "public-sandbox-abc123",
        "institution_name": "Chase",
        "accounts": [
            {"id": account_id, "name": f"Account {account_id}", "mask": "1234", "type": "credit"}
            for account_id in account_ids
        ],
    }


def test_link_account_callback_requires_auth(client):
    response = client.post("/link-account/callback", json=_callback_body("acct-1"))
    assert response.status_code == 401


def test_link_account_callback_rejects_wrong_credentials(client):
    response = client.post(
        "/link-account/callback", json=_callback_body("acct-1"), auth=("wrong", "creds")
    )
    assert response.status_code == 401


def test_link_account_callback_inserts_one_row_per_account(
    client, admin_auth, monkeypatch, fake_async_session, fake_async_session_factory
):
    """End-to-end confirmation (through the actual route, complementing
    the connector-level tests) of the item/account identity fix: a
    Link session covering 2 accounts under one Item must insert 2
    rows, not just the first."""
    fake_linked_account = type(
        "FakeLinkedAccount", (), {"item_id": "item-xyz", "access_token": "access-xyz"}
    )()
    monkeypatch.setattr(
        router_module._bank_connector,
        "exchange_public_token",
        lambda public_token: fake_linked_account,
    )
    monkeypatch.setattr(router_module, "async_session_factory", fake_async_session_factory)

    response = client.post(
        "/link-account/callback",
        json=_callback_body("plaid-acct-checking", "plaid-acct-credit"),
        auth=admin_auth,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["accounts_linked"] == 2
    assert body["item_id"] == "item-xyz"
    assert len(fake_async_session.executed) == 2
    assert fake_async_session.committed is True


def test_link_account_callback_rejects_empty_accounts_list(client, admin_auth):
    response = client.post(
        "/link-account/callback", json=_callback_body(), auth=admin_auth
    )
    assert response.status_code == 400


# --- /webhooks/plaid : signature verification -------------------------------


def test_plaid_webhook_rejects_missing_signature_header(client):
    response = client.post(
        "/webhooks/plaid",
        json={"webhook_type": "TRANSACTIONS", "webhook_code": "SYNC_UPDATES_AVAILABLE", "item_id": "item-1"},
    )
    assert response.status_code == 401


def test_plaid_webhook_rejects_invalid_signature(client, monkeypatch):
    monkeypatch.setattr(router_module, "verify_plaid_webhook", lambda client, header, body: False)

    response = client.post(
        "/webhooks/plaid",
        json={"webhook_type": "TRANSACTIONS", "webhook_code": "SYNC_UPDATES_AVAILABLE", "item_id": "item-1"},
        headers={"Plaid-Verification": "not-a-real-jwt"},
    )
    assert response.status_code == 401


def test_plaid_webhook_accepts_valid_signature_and_schedules_sync(client, monkeypatch):
    monkeypatch.setattr(router_module, "verify_plaid_webhook", lambda client, header, body: True)
    fake_run_sync = AsyncMock()
    monkeypatch.setattr(router_module, "_run_plaid_sync", fake_run_sync)

    response = client.post(
        "/webhooks/plaid",
        json={"webhook_type": "TRANSACTIONS", "webhook_code": "SYNC_UPDATES_AVAILABLE", "item_id": "item-42"},
        headers={"Plaid-Verification": "a-valid-looking-jwt"},
    )

    assert response.status_code == 200
    assert response.json() == {"acknowledged": True}
    fake_run_sync.assert_awaited_once_with("item-42")


def test_plaid_webhook_ignores_non_sync_webhook_codes(client, monkeypatch):
    """Only SYNC_UPDATES_AVAILABLE should trigger a background sync --
    other Plaid webhook codes should still ack 200 without scheduling
    one."""
    monkeypatch.setattr(router_module, "verify_plaid_webhook", lambda client, header, body: True)
    fake_run_sync = AsyncMock()
    monkeypatch.setattr(router_module, "_run_plaid_sync", fake_run_sync)

    response = client.post(
        "/webhooks/plaid",
        json={"webhook_type": "TRANSACTIONS", "webhook_code": "HISTORICAL_UPDATE", "item_id": "item-42"},
        headers={"Plaid-Verification": "a-valid-looking-jwt"},
    )

    assert response.status_code == 200
    fake_run_sync.assert_not_awaited()


# --- /webhooks/telegram : secret-token + chat-ID allowlist ------------------


def _telegram_update(chat_id: int, update_id: int = 1) -> dict:
    return {
        "update_id": update_id,
        "message": {
            "message_id": 100,
            "chat": {"id": chat_id},
            "text": "/status",
        },
    }


def test_telegram_webhook_rejects_missing_secret_header(client):
    response = client.post("/webhooks/telegram", json=_telegram_update(555000111))
    assert response.status_code == 401


def test_telegram_webhook_rejects_wrong_secret_token(client):
    response = client.post(
        "/webhooks/telegram",
        json=_telegram_update(555000111),
        headers={"X-Telegram-Bot-Api-Secret-Token": "wrong-secret"},
    )
    assert response.status_code == 401


def test_telegram_webhook_right_chat_id_is_processed(client):
    from app.config import settings

    response = client.post(
        "/webhooks/telegram",
        json=_telegram_update(settings.telegram_allowed_chat_id),
        headers={"X-Telegram-Bot-Api-Secret-Token": settings.telegram_webhook_secret_token},
    )
    assert response.status_code == 200
    assert response.json() == {"acknowledged": True}


def test_telegram_webhook_wrong_chat_id_is_silently_dropped(client):
    """Per A2's authorization model: a valid, correctly-signed request
    from any chat other than the allowlisted one still gets a 200 ack
    (so Telegram doesn't retry it), it's just not acted on. Dispatch to
    the agent (A3/D5) isn't built yet, so there's no further observable
    side effect to assert on beyond "doesn't error and doesn't 401" --
    this guards the allowlist-check branch itself, which does exist in
    the merged code."""
    from app.config import settings

    response = client.post(
        "/webhooks/telegram",
        json=_telegram_update(chat_id=999999999),
        headers={"X-Telegram-Bot-Api-Secret-Token": settings.telegram_webhook_secret_token},
    )
    assert response.status_code == 200
    assert response.json() == {"acknowledged": True}


def test_telegram_webhook_update_with_no_message_does_not_crash(client):
    """e.g. an edited_message/channel_post-only update -- `message` is
    optional in `TelegramUpdate`; the allowlist check must not raise
    on a None message."""
    from app.config import settings

    response = client.post(
        "/webhooks/telegram",
        json={"update_id": 2},
        headers={"X-Telegram-Bot-Api-Secret-Token": settings.telegram_webhook_secret_token},
    )
    assert response.status_code == 200
    assert response.json() == {"acknowledged": True}
