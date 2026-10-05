"""Production proxy regression using the deployed Uvicorn configuration."""

from __future__ import annotations

import json
import re
import shlex
from http.cookies import SimpleCookie
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from uvicorn import Config

import app.gateway.router as gateway
from app.config import settings
from app.gateway import auth
from app.main import app

_ROOT = Path(__file__).resolve().parents[2]
_HOST = "expense-reconciler.onrender.com"
_ORIGIN = f"https://{_HOST}"
_PEER = ("10.42.0.8", 43210)


def _deployed_environment():
    # Only the Blueprint's explicit single-line scalar values are needed;
    # secret references are never read, and no YAML dependency is introduced.
    entries = re.findall(
        r"^\s+- key: (\w+)\n\s+value: ([^\n]+)$",
        (_ROOT / "render.yaml").read_text(),
        re.MULTILINE,
    )
    return {name: value.strip().strip("\"'") for name, value in entries}


@pytest.fixture
def proxy_client_factory(monkeypatch):
    environment = _deployed_environment()
    monkeypatch.setattr(settings, "environment", environment["ENVIRONMENT"])
    assert settings.environment == "production"
    command_line = next(
        line for line in (_ROOT / "Dockerfile").read_text().splitlines()
        if line.startswith("CMD ")
    )
    command = json.loads(command_line.removeprefix("CMD "))
    assert command[:2] == ["sh", "-c"]
    uvicorn_args = shlex.split(command[2])
    assert uvicorn_args[:2] == ["uvicorn", "app.main:app"]

    def make_client(*, render_trust=True):
        if render_trust:
            monkeypatch.setenv("FORWARDED_ALLOW_IPS", environment["FORWARDED_ALLOW_IPS"])
        else:
            monkeypatch.delenv("FORWARDED_ALLOW_IPS", raising=False)

        observed_schemes = []

        async def observe_scope(scope, receive, send):
            if scope["type"] == "http":
                observed_schemes.append(scope["scheme"])
            await app(scope, receive, send)

        config = Config(
            observe_scope,
            proxy_headers="--proxy-headers" in uvicorn_args,
            lifespan="off",
            log_config=None,
        )
        config.load()
        # Neither the TestClient URL nor its socket peer supplies HTTPS.
        # The real Config-loaded middleware must trust the non-loopback peer
        # and process X-Forwarded-Proto for the application's guard to pass.
        client = TestClient(
            config.loaded_app, base_url=f"http://{_HOST}", client=_PEER
        )
        return client, observed_schemes

    return make_client


def _login(client, admin_auth, headers):
    return client.post(
        "/link-account/session",
        json={"username": admin_auth[0], "password": admin_auth[1]},
        headers=headers,
    )


def _browser_cookie(response):
    cookie = SimpleCookie()
    cookie.load(response.headers["set-cookie"])
    session = cookie[auth.COOKIE_NAME]
    assert session["secure"]
    # A real HTTPS browser sends this cookie to Render; our client sees the
    # internal HTTP hop, so explicitly emulate that browser Cookie header.
    return f"{auth.COOKIE_NAME}={session.value}"


def test_render_forwarded_https_verifies_and_reaches_protected_plaid(
    proxy_client_factory, admin_auth, monkeypatch
):
    provider = Mock(return_value=SimpleNamespace(link_token="mock-link-token"))
    monkeypatch.setattr(gateway._plaid_client, "link_token_create", provider)
    client, observed = proxy_client_factory()
    headers = {"X-Forwarded-Proto": "https", "Origin": _ORIGIN}

    response = client.get("/link-account/session", headers=headers)
    assert response.status_code == 200
    assert response.json() == {"authenticated": False}
    response = _login(client, admin_auth, headers)
    assert response.status_code == 200
    verified = response.json()
    assert verified["authenticated"] is True
    headers["Cookie"] = _browser_cookie(response)
    status = client.get("/link-account/session", headers=headers)
    assert status.status_code == 200
    assert status.json() == verified
    headers["X-CSRF-Token"] = verified["csrf_token"]
    response = client.post("/link-account/token", json={}, headers=headers)
    assert response.status_code == 200
    assert response.json() == {"link_token": "mock-link-token"}
    provider.assert_called_once()
    assert observed == ["https"] * 4


@pytest.mark.parametrize(
    "render_trust,forwarded_scheme", [(False, "https"), (True, "http")]
)
def test_untrusted_peer_and_forwarded_http_cannot_bypass_transport(
    proxy_client_factory, admin_auth, monkeypatch, render_trust, forwarded_scheme
):
    provider = Mock(side_effect=AssertionError("Plaid must not be reached"))
    monkeypatch.setattr(gateway._plaid_client, "link_token_create", provider)
    client, observed = proxy_client_factory(render_trust=render_trust)
    token, claims = auth.create_session()
    headers = {
        "X-Forwarded-Proto": forwarded_scheme,
        "Origin": _ORIGIN,
        "Cookie": f"{auth.COOKIE_NAME}={token}",
        "X-CSRF-Token": claims["csrf"],
    }
    responses = [
        client.get("/link-account/session", headers=headers),
        _login(client, admin_auth, headers),
        client.post("/link-account/token", json={}, headers=headers),
    ]
    for response in responses:
        assert response.status_code == 403
        assert "set-cookie" not in response.headers
        assert response.headers["cache-control"] == "no-store"
    assert observed == ["http"] * 3
    provider.assert_not_called()


@pytest.mark.parametrize("invalid_guard", ["origin", "csrf"])
def test_trusted_https_still_requires_origin_and_csrf(
    proxy_client_factory, admin_auth, monkeypatch, invalid_guard
):
    provider = Mock(side_effect=AssertionError("Plaid must not be reached"))
    monkeypatch.setattr(gateway._plaid_client, "link_token_create", provider)
    client, observed = proxy_client_factory()
    headers = {"X-Forwarded-Proto": "https", "Origin": _ORIGIN}
    login = _login(client, admin_auth, headers)
    assert login.status_code == 200
    headers["Cookie"] = _browser_cookie(login)
    headers["X-CSRF-Token"] = login.json()["csrf_token"]
    if invalid_guard == "origin":
        headers["Origin"] = "https://other.example.com"
    else:
        headers["X-CSRF-Token"] = "incorrect"
    response = client.post("/link-account/token", json={}, headers=headers)
    assert response.status_code == 403
    assert observed == ["https", "https"]
    provider.assert_not_called()
