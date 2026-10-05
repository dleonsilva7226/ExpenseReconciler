"""Credential-bound session and browser security regression checks."""

from __future__ import annotations

import hashlib
import hmac
import json
import time

import jwt
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.gateway import auth
from app.main import app


def test_non_ascii_credentials_and_key_contract(monkeypatch):
    monkeypatch.setattr(settings, "admin_username", "管理者")
    monkeypatch.setattr(settings, "admin_password", "café🔐")
    assert auth.credentials_match("管理者", "café🔐")
    assert not auth.credentials_match("管理者", "wrong")
    expected = hmac.digest(
        settings.token_encryption_key.encode(),
        b"jarvis/link-account/session/v1\0"
        + json.dumps(
            [settings.admin_username, settings.admin_password],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode(),
        hashlib.sha256,
    )
    assert auth._session_key() == expected
    token, claims = auth.create_session()
    assert auth.decode_session(token) == claims
    monkeypatch.setattr(settings, "admin_password", "changed")
    assert auth.decode_session(token) is None


def test_both_credentials_compared(monkeypatch):
    calls = []
    monkeypatch.setattr(
        auth.secrets,
        "compare_digest",
        lambda left, right: calls.append((left, right)) or False,
    )
    assert not auth.credentials_match("bad", "bad")
    assert len(calls) == 2


@pytest.mark.parametrize(
    "change",
    [
        {"sub": "other"},
        {"purpose": "other"},
        {"csrf": ""},
        {"csrf": None},
        {"iat": True},
        {"exp": True},
        {"iat": "1"},
        {"exp": 1.5},
        {"iat": int(time.time()) + 500},
        {"exp": int(time.time()) + 800},
        {"iat": int(time.time()) - 1000, "exp": int(time.time()) - 100},
    ],
)
def test_invalid_claims_rejected(change):
    _, claims = auth.create_session()
    claims.update(change)
    token = jwt.encode(claims, auth._session_key(), algorithm="HS256")
    assert auth.decode_session(token) is None


@pytest.mark.parametrize("claim", ["sub", "purpose", "iat", "exp", "csrf"])
def test_missing_claims_rejected(claim):
    _, claims = auth.create_session()
    claims.pop(claim)
    assert (
        auth.decode_session(jwt.encode(claims, auth._session_key(), algorithm="HS256"))
        is None
    )


def test_bad_signature_algorithm_and_malformed_session():
    token, claims = auth.create_session()
    assert auth.decode_session(token + "tamper") is None
    assert (
        auth.decode_session(jwt.encode(claims, b"different" * 8, algorithm="HS256"))
        is None
    )
    assert (
        auth.decode_session(
            jwt.encode(claims, auth._session_key() * 2, algorithm="HS512")
        )
        is None
    )
    assert auth.decode_session("broken") is None


def test_login_cookie_status_refresh_and_logout(client, admin_auth):
    body = {"username": admin_auth[0], "password": admin_auth[1]}
    response = client.post(
        "/link-account/session", json=body, headers={"Origin": "http://localhost"}
    )
    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    for attribute in ["HttpOnly", "Max-Age=900", "Path=/link-account", "SameSite=lax"]:
        assert attribute in cookie
    assert "Domain=" not in cookie and "Secure" not in cookie
    first = response.json()
    assert client.get("/link-account/session").json() == first
    refreshed = client.post(
        "/link-account/session", json=body, headers={"Origin": "http://localhost"}
    )
    assert refreshed.json()["csrf_token"] != first["csrf_token"]
    response = client.post(
        "/link-account/logout",
        json={},
        headers={
            "Origin": "http://localhost",
            "X-CSRF-Token": refreshed.json()["csrf_token"],
        },
    )
    assert response.status_code == 200
    assert "Max-Age=0" in response.headers["set-cookie"]
    assert client.get("/link-account/session").json() == {"authenticated": False}


@pytest.mark.parametrize(
    "base_url,environment,expected",
    [
        ("https://localhost", "development", 200),
        ("https://example.com", "production", 200),
        ("http://localhost", "production", 403),
        ("http://example.com", "development", 403),
        ("http://127.0.0.1", "development", 200),
        ("http://[::1]", "development", 200),
    ],
)
def test_transport_and_secure_cookie(
    base_url, environment, expected, admin_auth, monkeypatch
):
    monkeypatch.setattr(settings, "environment", environment)
    local_client = TestClient(app, base_url=base_url)
    response = local_client.post(
        "/link-account/session",
        json={
            "username": admin_auth[0],
            "password": admin_auth[1],
        },
        headers={"Origin": base_url, "X-Forwarded-Proto": "https"},
    )
    assert response.status_code == expected
    if expected == 200:
        assert ("Secure" in response.headers["set-cookie"]) == base_url.startswith(
            "https:"
        )
    else:
        assert "set-cookie" not in response.headers


@pytest.mark.parametrize(
    "origin",
    [
        None,
        "null",
        "https://localhost",
        "http://localhost:81",
        "http://localhost:0",
        "http://evil.localhost",
        "http://user@localhost",
        "http://localhost/path",
        "http://localhost?query=1",
        "http://localhost#fragment",
        "http://localhost:notaport",
    ],
)
def test_login_origin_guard(client, origin, admin_auth):
    headers = {} if origin is None else {"Origin": origin}
    response = client.post(
        "/link-account/session",
        json={"username": admin_auth[0], "password": admin_auth[1]},
        headers=headers,
    )
    assert response.status_code == 403
    assert "set-cookie" not in response.headers
    assert response.headers["cache-control"] == "no-store"
    assert "www-authenticate" not in response.headers


def test_validation_and_wrong_credentials_never_echo_password(client, admin_auth):
    password = admin_auth[1]
    for body in [
        {"username": "", "password": password},
        {"username": "bad", "password": password, "extra": password},
        {"username": "bad", "password": password},
    ]:
        response = client.post(
            "/link-account/session", json=body, headers={"Origin": "http://localhost"}
        )
        assert response.status_code in {401, 422}
        assert password not in response.text
        assert "www-authenticate" not in response.headers
        assert "set-cookie" not in response.headers
    response = client.post(
        "/link-account/session",
        content="{",
        headers={"Origin": "http://localhost", "Content-Type": "application/json"},
    )
    assert response.status_code == 422
    assert response.headers["cache-control"] == "no-store"
    assert (
        client.post(
            "/link-account/session",
            content="username=x",
            headers={"Origin": "http://localhost", "Content-Type": "text/plain"},
        ).status_code
        == 415
    )


def test_invalid_cookie_cleared(client):
    client.cookies.set(auth.COOKIE_NAME, "bad", path="/link-account")
    response = client.get("/link-account/session")
    assert response.json() == {"authenticated": False}
    assert "Max-Age=0" in response.headers["set-cookie"]


@pytest.mark.parametrize("endpoint", ["token", "callback", "logout"])
def test_mutations_require_session_before_origin(client, admin_auth, endpoint):
    response = client.post(f"/link-account/{endpoint}", auth=admin_auth, json={})
    assert response.status_code == 401
    assert response.headers["cache-control"] == "no-store"
    assert "www-authenticate" not in response.headers


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Origin": "null"},
        {"Origin": "http://localhost"},
        {"Origin": "http://localhost", "X-CSRF-Token": "wrong"},
        {"Origin": "http://localhost", "Sec-Fetch-Site": "cross-site"},
    ],
)
def test_guard_failure_does_not_call_plaid(client, admin_session, monkeypatch, headers):
    import app.gateway.router as router_module

    calls = []
    monkeypatch.setattr(
        router_module._plaid_client,
        "link_token_create",
        lambda request: calls.append(request),
    )
    response = client.post("/link-account/token", json={}, headers=headers)
    assert response.status_code == 403
    assert calls == []


def test_json_guard_and_public_assets(client, admin_session, monkeypatch):
    import app.gateway.router as router_module

    calls = []
    monkeypatch.setattr(
        router_module._plaid_client,
        "link_token_create",
        lambda request: calls.append(request),
    )
    assert (
        client.post(
            "/link-account/token", content="x", headers=admin_session
        ).status_code
        == 415
    )
    assert calls == []
    for path, media_type in [
        ("/link-account", "text/html"),
        ("/link-account/assets/link_account.css", "text/css"),
        ("/link-account/assets/link_account.js", "application/javascript"),
    ]:
        response = client.get(path)
        assert response.status_code == 200
        assert media_type in response.headers["content-type"]
        assert response.headers["cache-control"] == "no-store"
        assert "www-authenticate" not in response.headers
    assert client.get("/link-account").headers["referrer-policy"] == "no-referrer"
    assert client.get("/link-account/assets/auth.py").status_code == 404
    assert client.get("/link-account/assets/../auth.py").status_code == 404
