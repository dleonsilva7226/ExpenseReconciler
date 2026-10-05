"""Optional real Chromium checks; install Playwright in an external QA runner.

The app's actual HTML/CSS/JS, routes, sessions, request guards and callback
transaction execute. Only Plaid's CDN/provider and the database boundary are
mocked. No browser test dependency is added to application requirements.
Set PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH to select a browser explicitly;
otherwise use Chromium/Chrome on PATH or Playwright's installed Chromium.
"""

from __future__ import annotations

import os
import shutil
import socket
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

playwright = pytest.importorskip("playwright.sync_api", reason="optional Chromium QA runner")

from playwright.sync_api import expect

from app.config import settings
from app.gateway import router as gateway
from app.main import app

MOCK_PLAID = """
window.__plaidOpened = 0; window.__plaidDestroyed = 0;
window.Plaid = {create(options) {
  window.__link = options;
  return {open() {window.__plaidOpened++;},
    destroy() {window.__plaidDestroyed++;}};
}};
"""
METADATA = {
    "institution": {"name": "Mock Bank"},
    "accounts": [
        {"id": "mock-checking", "name": "Checking", "mask": "0001", "type": "depository", "subtype": "checking"},
        {"id": "mock-savings", "name": "Savings", "mask": "0002", "type": "depository", "subtype": "savings"},
    ],
}


@pytest.fixture
def browser_app(monkeypatch, fake_async_session):
    import uvicorn

    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(
        gateway._plaid_client, "link_token_create",
        lambda _: SimpleNamespace(link_token="mock-link-token"),
    )
    monkeypatch.setattr(
        gateway._bank_connector, "exchange_public_token",
        lambda _: SimpleNamespace(item_id="mock-item", access_token="mock-access"),
    )
    monkeypatch.setattr(gateway, "async_session_factory", lambda: fake_async_session)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, lifespan="off", log_level="error", access_log=False))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        thread.join(0.01)
    assert server.started
    try:
        yield f"http://127.0.0.1:{port}", fake_async_session
    finally:
        server.should_exit = True
        thread.join(10)
        sock.close()
        assert not thread.is_alive()


@pytest.fixture
def page(browser_app):
    base_url, _ = browser_app
    with playwright.sync_playwright() as runner:
        executable = (
            os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH")
            or shutil.which("chromium")
            or shutil.which("chromium-browser")
            or shutil.which("google-chrome")
        )
        browser = runner.chromium.launch(executable_path=executable, args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        browser_page = context.new_page()
        errors = []
        browser_page.on("pageerror", lambda error: errors.append(str(error)))
        browser_page.route("https://cdn.plaid.com/**", lambda route: route.fulfill(content_type="application/javascript", body=MOCK_PLAID))
        browser_page.goto(base_url + "/link-account")
        expect(browser_page.locator("#verify-panel")).to_be_visible()
        yield browser_page
        assert errors == []
        context.close()
        browser.close()


def verify(page):
    page.get_by_label("Username", exact=True).fill(settings.admin_username)
    page.get_by_label("Password", exact=True).fill(settings.admin_password)
    page.get_by_label("Password", exact=True).press("Enter")
    expect(page.locator("#connect-panel")).to_be_visible()
    assert page.get_by_label("Password", exact=True).input_value() == ""


def open_link(page):
    page.locator("#connect-button").click()
    page.wait_for_function("window.__plaidOpened === 1")


def succeed(page):
    page.evaluate("metadata => {void window.__link.onSuccess('mock-public-token', metadata);}", METADATA)


def test_keyboard_verification_cookie_session_resume_and_logout(page):
    assert page.locator("h1").count() == 1
    assert page.locator("#status").get_attribute("aria-live") == "polite"
    page.get_by_label("Username", exact=True).fill(settings.admin_username)
    page.get_by_label("Password", exact=True).fill("wrong")
    page.get_by_label("Password", exact=True).press("Enter")
    expect(page.locator("#status")).to_contain_text("couldn't verify those details")
    assert page.get_by_label("Username", exact=True).input_value() == settings.admin_username
    assert page.get_by_label("Password", exact=True).input_value() == ""
    assert page.evaluate("document.activeElement.id") == "password"
    verify(page)
    assert page.evaluate("document.activeElement.id") == "connect-heading"
    assert page.evaluate("typeof window.Plaid") == "undefined"
    assert page.evaluate("localStorage.length + sessionStorage.length") == 0
    assert "jarvis_link_session" not in page.evaluate("document.cookie")
    cookies = page.context.cookies()
    assert len(cookies) == 1 and cookies[0]["httpOnly"]
    assert cookies[0]["sameSite"] == "Lax" and cookies[0]["path"] == "/link-account"
    page.reload()
    expect(page.locator("#connect-panel")).to_be_visible()
    page.locator("#connect-panel .signout-button").click()
    expect(page.locator("#verify-panel")).to_be_visible()
    expect(page.locator("#status")).to_have_text("You've signed out.")
    assert page.context.cookies() == []


def test_actual_browser_plaid_callback_encrypted_two_account_success(page, browser_app):
    _, session = browser_app
    verify(page)
    open_link(page)
    expect(page.locator("#connect-button")).to_be_disabled()
    succeed(page)
    expect(page.locator("#success-panel")).to_be_visible()
    assert session.committed and len(session.executed) == 2
    for index, (statement, params) in enumerate(session.executed):
        assert "pgp_sym_encrypt(:token, :key)" in str(statement)
        assert params["account_id"] == METADATA["accounts"][index]["id"]
        assert params["institution_name"] == "Mock Bank"
        assert params["token"] == "mock-access"
    assert page.evaluate("window.__plaidDestroyed") == 1
    expect(page.locator("#success-panel")).to_contain_text("Return to Telegram")
    page.locator("#another-button").click()
    expect(page.locator("#connect-panel")).to_be_visible()


def test_cancellation_then_provider_error_are_retryable(page):
    verify(page)
    open_link(page)
    page.evaluate("window.__link.onExit(null)")
    expect(page.locator("#status")).to_contain_text("Connection cancelled")
    expect(page.locator("#connect-button")).to_be_enabled()
    page.locator("#connect-button").click()
    page.wait_for_function("window.__plaidOpened === 2")
    page.evaluate("window.__link.onExit({error_message:'<script>private</script>'})")
    expect(page.locator("#status")).to_have_text("We couldn't connect to your bank. Please try again.")
    assert page.evaluate("window.__plaidDestroyed") == 2


@pytest.mark.parametrize("status", [401, 403, 502])
def test_token_failure_expiry_and_reverification(page, status):
    verify(page)
    page.route("**/link-account/token", lambda route: route.fulfill(status=status, json={"detail": "private"}))
    page.locator("#connect-button").click()
    if status == 401:
        expect(page.locator("#verify-panel")).to_be_visible()
        expect(page.locator("#status")).to_contain_text("verification expired")
    elif status == 403:
        expect(page.locator("#reverify-button")).to_be_visible()
        page.locator("#reverify-button").click()
        expect(page.locator("#verify-panel")).to_be_visible()
    else:
        expect(page.locator("#status")).to_contain_text("couldn't start")
        expect(page.locator("#connect-button")).to_be_enabled()
    assert page.evaluate("typeof window.Plaid") == "undefined"


def test_logout_failure_never_claims_signed_out(page):
    verify(page)
    page.route("**/link-account/logout", lambda route: route.fulfill(status=500, json={"detail": "mock failure"}))
    page.locator("#connect-panel .signout-button").click()
    expect(page.locator("#status")).to_contain_text("couldn't sign you out")
    expect(page.locator("#connect-panel")).to_be_visible()
    assert page.context.cookies()


def test_inflight_callback_cannot_revive_expired_flow(page, browser_app):
    _, session = browser_app
    page.clock.install(time=datetime.now(UTC))
    verify(page)
    open_link(page)
    callbacks = []
    page.route("**/link-account/callback", lambda route: callbacks.append(route))
    succeed(page)
    expect(page.locator("#status")).to_have_text("Connecting your account…")
    page.wait_for_timeout(20)
    assert len(callbacks) == 1
    page.clock.fast_forward(901_000)
    expect(page.locator("#verify-panel")).to_be_visible()
    expect(page.locator("#status")).to_contain_text("verification expired")
    callbacks[0].fulfill(json={"linked": True, "accounts_linked": 2})
    page.wait_for_timeout(50)
    expect(page.locator("#verify-panel")).to_be_visible()
    expect(page.locator("#success-panel")).to_be_hidden()
    assert not session.committed


def test_lazy_sdk_failure_can_be_retried(page):
    verify(page)
    page.route("https://cdn.plaid.com/**", lambda route: route.abort())
    page.locator("#connect-button").click()
    expect(page.locator("#status")).to_contain_text("couldn't start")
    expect(page.locator("#connect-button")).to_be_enabled()
    page.unroute("https://cdn.plaid.com/**")
    page.route("https://cdn.plaid.com/**", lambda route: route.fulfill(content_type="application/javascript", body=MOCK_PLAID))
    open_link(page)


def test_callback_persistence_error_never_shows_success(page):
    verify(page)
    open_link(page)
    page.route("**/link-account/callback", lambda route: route.fulfill(status=500, json={"detail": "private database details"}))
    succeed(page)
    expect(page.locator("#status")).to_have_text("We couldn't connect your account. Please try again.")
    expect(page.locator("#connect-panel")).to_be_visible()
    expect(page.locator("#success-panel")).to_be_hidden()
    expect(page.locator("#connect-button")).to_be_enabled()


def test_mobile_layout_accessible_focus_and_clean_screenshots(page, tmp_path: Path):
    output = tmp_path / "verification-screenshots"
    output.mkdir()
    page.screenshot(path=str(output / "verify-desktop.png"), full_page=True)
    for width in [320, 390]:
        page.set_viewport_size({"width": width, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        button = page.locator("#continue-button").bounding_box()
        assert button["height"] >= 44
        page.get_by_label("Username", exact=True).focus()
        page.keyboard.press("Tab")
        assert page.evaluate("document.activeElement.id") == "password"
        page.keyboard.press("Tab")
        assert page.evaluate("document.activeElement.id") == "continue-button"
    page.screenshot(path=str(output / "verify-mobile.png"), full_page=True)
    verify(page)
    page.screenshot(path=str(output / "connect-mobile.png"), full_page=True)
    page.set_viewport_size({"width": 1280, "height": 900})
    page.screenshot(path=str(output / "connect-desktop.png"), full_page=True)
    for name in ("verify-desktop.png", "verify-mobile.png", "connect-mobile.png", "connect-desktop.png"):
        assert (output / name).read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
