"""Independent request-guard and atomic bank persistence checks."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.exc import SQLAlchemyError

import app.gateway.router as gateway
from app.gateway import auth


def callback_body():
    return {
        "public_token": "mock-public-token",
        "institution_name": "Mock institution",
        "accounts": [
            {"id": "checking", "name": "Checking", "mask": "0001"},
            {"id": "savings", "name": "Savings", "mask": "0002"},
        ],
    }


@pytest.mark.parametrize("endpoint", ["callback", "logout"])
@pytest.mark.parametrize("failure", ["origin", "csrf", "json", "cross-site"])
def test_all_browser_mutation_guards_precede_effects(
    client, admin_session, monkeypatch, endpoint, failure
):
    exchange = Mock(side_effect=AssertionError("Provider must not be reached"))
    database = Mock(side_effect=AssertionError("Database must not be reached"))
    clear_cookie = Mock(side_effect=AssertionError("Cookie must not be deleted"))
    monkeypatch.setattr(gateway._bank_connector, "exchange_public_token", exchange)
    monkeypatch.setattr(gateway, "async_session_factory", database)
    monkeypatch.setattr(gateway, "clear_session_cookie", clear_cookie)
    headers = dict(admin_session)
    if failure == "origin":
        headers["Origin"] = "http://localhost:9999"
    elif failure == "csrf":
        headers["X-CSRF-Token"] = "wrong"
    elif failure == "cross-site":
        headers["Sec-Fetch-Site"] = "cross-site"
    kwargs = {"json": callback_body() if endpoint == "callback" else {}}
    if failure == "json":
        kwargs = {"content": "{}"}
        headers["Content-Type"] = "text/plain"
    response = client.post(f"/link-account/{endpoint}", headers=headers, **kwargs)
    assert response.status_code == (415 if failure == "json" else 403)
    assert response.headers["cache-control"] == "no-store"
    assert "www-authenticate" not in response.headers
    exchange.assert_not_called()
    database.assert_not_called()
    clear_cookie.assert_not_called()


def test_second_account_insert_failure_rolls_back_without_commit(
    client, admin_session, monkeypatch, fake_async_session
):
    monkeypatch.setattr(
        gateway._bank_connector,
        "exchange_public_token",
        lambda _: SimpleNamespace(item_id="mock-item", access_token="mock-access"),
    )
    fake_async_session.execute = AsyncMock(
        side_effect=[None, SQLAlchemyError("private database detail")]
    )
    fake_async_session.commit = AsyncMock()
    fake_async_session.rollback = AsyncMock()
    monkeypatch.setattr(gateway, "async_session_factory", lambda: fake_async_session)
    response = client.post(
        "/link-account/callback", json=callback_body(), headers=admin_session
    )
    assert response.status_code == 500
    assert "private database detail" not in response.text
    assert response.json().get("linked") is not True
    fake_async_session.commit.assert_not_awaited()
    fake_async_session.rollback.assert_awaited_once()
    assert fake_async_session.execute.await_count == 2
    for call in fake_async_session.execute.await_args_list:
        assert "pgp_sym_encrypt(:token, :key)" in str(call.args[0])


def test_empty_account_callback_never_exchanges_token(
    client, admin_session, monkeypatch
):
    exchange = Mock(side_effect=AssertionError("No provider calls for empty accounts"))
    monkeypatch.setattr(gateway._bank_connector, "exchange_public_token", exchange)
    body = callback_body()
    body["accounts"] = []
    assert client.post(
        "/link-account/callback", json=body, headers=admin_session
    ).status_code == 400
    exchange.assert_not_called()


def test_default_port_equivalence_and_old_csrf_after_reverification(
    client, admin_session, admin_auth
):
    response = client.post(
        "/link-account/session",
        json={"username": admin_auth[0], "password": admin_auth[1]},
        headers={"Origin": "http://LOCALHOST:80/"},
    )
    assert response.status_code == 200
    assert response.json()["csrf_token"] != admin_session["X-CSRF-Token"]
    assert client.post(
        "/link-account/logout", json={}, headers=admin_session
    ).status_code == 403


def test_logout_does_not_claim_stateless_global_revocation(client, admin_session):
    token = client.cookies.get(auth.COOKIE_NAME)
    assert client.post(
        "/link-account/logout", json={}, headers=admin_session
    ).status_code == 200
    assert client.get("/link-account/session").json() == {"authenticated": False}
    # Cookie deletion removes this browser's access; a copied bearer token is
    # intentionally valid for the remainder of the original fifteen minutes.
    assert auth.decode_session(token) is not None
