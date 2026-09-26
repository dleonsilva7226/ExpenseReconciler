"""`app/gateway/auth.py` unit tests (priority 3 of the Q1 ticket):
`require_admin` in isolation, wrong-credential rejection and
correct-credential acceptance, straight from A2a's Basic Auth spec.
(`tests/gateway/test_router.py` covers the same behavior end-to-end
through actual HTTP requests to the gated routes.)
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPBasicCredentials

from app.config import settings
from app.gateway.auth import require_admin


def test_require_admin_accepts_correct_credentials():
    credentials = HTTPBasicCredentials(
        username=settings.admin_username, password=settings.admin_password
    )

    assert require_admin(credentials) == settings.admin_username


def test_require_admin_rejects_wrong_password():
    credentials = HTTPBasicCredentials(username=settings.admin_username, password="wrong")

    with pytest.raises(HTTPException) as exc_info:
        require_admin(credentials)
    assert exc_info.value.status_code == 401


def test_require_admin_rejects_wrong_username():
    credentials = HTTPBasicCredentials(username="not-admin", password=settings.admin_password)

    with pytest.raises(HTTPException) as exc_info:
        require_admin(credentials)
    assert exc_info.value.status_code == 401


def test_require_admin_rejects_both_wrong():
    credentials = HTTPBasicCredentials(username="nope", password="nope")

    with pytest.raises(HTTPException) as exc_info:
        require_admin(credentials)
    assert exc_info.value.status_code == 401


def test_require_admin_rejection_carries_www_authenticate_challenge():
    # Standard Basic Auth behavior a browser/client relies on to know
    # to prompt for credentials again.
    credentials = HTTPBasicCredentials(username="nope", password="nope")

    with pytest.raises(HTTPException) as exc_info:
        require_admin(credentials)
    assert exc_info.value.headers.get("WWW-Authenticate") == "Basic"
