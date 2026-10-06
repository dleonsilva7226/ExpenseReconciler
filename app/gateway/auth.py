"""Single-admin browser verification, signed session, and request guards."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from typing import Annotated
from urllib.parse import urlsplit

import jwt
from fastapi import Depends, HTTPException, Request, Response

from app.config import settings

COOKIE_NAME = "jarvis_link_session"
SESSION_SECONDS = 900
PURPOSE = "jarvis-link-account-v1"
_LOOPBACK = {"localhost", "127.0.0.1", "::1"}


def credentials_match(username: str, password: str) -> bool:
    username_ok = secrets.compare_digest(
        username.encode(), settings.admin_username.encode()
    )
    password_ok = secrets.compare_digest(
        password.encode(), settings.admin_password.encode()
    )
    return username_ok and password_ok


def _session_key() -> bytes:
    credentials = json.dumps(
        [settings.admin_username, settings.admin_password],
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hmac.digest(
        settings.token_encryption_key.encode("utf-8"),
        b"jarvis/link-account/session/v1\0" + credentials,
        hashlib.sha256,
    )


def create_session() -> tuple[str, dict]:
    issued = int(time.time())
    claims = {
        "sub": "admin",
        "purpose": PURPOSE,
        "iat": issued,
        "exp": issued + SESSION_SECONDS,
        "csrf": secrets.token_urlsafe(32),
    }
    return jwt.encode(claims, _session_key(), algorithm="HS256"), claims


def decode_session(token: str | None) -> dict | None:
    if not token:
        return None
    try:
        claims = jwt.decode(
            token,
            _session_key(),
            algorithms=["HS256"],
            options={"require": ["sub", "purpose", "iat", "exp", "csrf"]},
        )
        if (
            claims["sub"] != "admin"
            or claims["purpose"] != PURPOSE
            or type(claims["iat"]) is not int
            or type(claims["exp"]) is not int
            or claims["iat"] > time.time()
            or claims["exp"] - claims["iat"] != SESSION_SECONDS
            or not isinstance(claims["csrf"], str)
            or not claims["csrf"]
        ):
            return None
        return claims
    except (jwt.PyJWTError, ValueError, TypeError):
        return None


def require_transport(request: Request) -> None:
    if request.url.scheme == "https":
        return
    if settings.environment == "development" and request.url.hostname in _LOOPBACK:
        return
    raise HTTPException(403, "A secure HTTPS connection is required to verify access.")


def _origin_parts(value: str) -> tuple[str, str, int] | None:
    try:
        parts = urlsplit(value)
        if (
            parts.scheme not in {"http", "https"}
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
            or parts.path not in {"", "/"}
            or parts.query
            or parts.fragment
            or any(character.isspace() for character in value)
        ):
            return None
        return (
            parts.scheme,
            parts.hostname.lower(),
            parts.port
            if parts.port is not None
            else (443 if parts.scheme == "https" else 80),
        )
    except ValueError:
        return None


def require_origin(request: Request) -> None:
    origin = _origin_parts(request.headers.get("origin", ""))
    authority = _origin_parts(str(request.url.replace(path="", query="", fragment="")))
    if (
        origin is None
        or origin != authority
        or request.headers.get("sec-fetch-site") == "cross-site"
    ):
        raise HTTPException(403, "Please refresh and verify again.")


def require_json(request: Request) -> None:
    if (
        request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        != "application/json"
    ):
        raise HTTPException(415, "Please submit this request as JSON.")


def require_login_request(request: Request) -> None:
    require_transport(request)
    require_origin(request)
    require_json(request)


def require_session(request: Request) -> dict:
    require_transport(request)
    claims = decode_session(request.cookies.get(COOKIE_NAME))
    if claims is None:
        raise HTTPException(401, "Your verification expired. Verify again to continue.")
    return claims


def require_admin(
    request: Request, claims: Annotated[dict, Depends(require_session)]
) -> str:
    require_origin(request)
    supplied = request.headers.get("x-csrf-token", "")
    if not secrets.compare_digest(supplied.encode(), claims["csrf"].encode()):
        raise HTTPException(403, "Please refresh and verify again.")
    require_json(request)
    return settings.admin_username


def session_status(claims: dict) -> dict:
    return {
        "authenticated": True,
        "csrf_token": claims["csrf"],
        "expires_at": claims["exp"],
    }


def set_session_cookie(response: Response, request: Request, token: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=SESSION_SECONDS,
        path="/link-account",
        httponly=True,
        secure=settings.environment == "production" or request.url.scheme == "https",
        samesite="lax",
    )


def clear_session_cookie(response: Response, request: Request) -> None:
    response.delete_cookie(
        COOKIE_NAME,
        path="/link-account",
        httponly=True,
        secure=settings.environment == "production" or request.url.scheme == "https",
        samesite="lax",
    )


AdminUser = Annotated[str, Depends(require_admin)]
