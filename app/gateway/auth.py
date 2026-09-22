"""Single-user HTTP Basic Auth dependency (D4, per A2a).

Not a session/login system — see A2a's "Auth model" section for why
that's a deliberate scope decision, not an oversight. Must only ever
be exposed over HTTPS in any non-local deployment (A2a's DevOps note).
"""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.config import settings

_security = HTTPBasic()


def require_admin(
    credentials: Annotated[HTTPBasicCredentials, Depends(_security)],
) -> str:
    username_ok = secrets.compare_digest(credentials.username, settings.admin_username)
    password_ok = secrets.compare_digest(credentials.password, settings.admin_password)
    if not (username_ok and password_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username
