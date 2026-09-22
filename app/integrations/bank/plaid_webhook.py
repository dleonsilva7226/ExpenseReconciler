"""Plaid webhook JWT signature verification (D4, per A2).

Verifies the `Plaid-Verification` header on inbound Plaid webhooks
against Plaid's rotating verification keys, per Plaid's documented
algorithm: fetch the signing key for the JWT's `kid`, verify the ES256
signature, check freshness, and confirm the payload hash matches the
raw request body.

Not exercised against a live Plaid webhook (no real credentials are
available yet) — flagged in the D1-D4 status note as needing a
sanity-check once real Plaid sandbox credentials exist.
"""

from __future__ import annotations

import hashlib
import time

import jwt
from plaid.api import plaid_api
from plaid.model.webhook_verification_key_get_request import (
    WebhookVerificationKeyGetRequest,
)

_verification_key_cache: dict[str, dict] = {}

_MAX_WEBHOOK_AGE_SECONDS = 5 * 60


def verify_plaid_webhook(client: plaid_api.PlaidApi, jwt_header: str, raw_body: bytes) -> bool:
    if not jwt_header:
        return False

    try:
        unverified_header = jwt.get_unverified_header(jwt_header)
    except jwt.InvalidTokenError:
        return False

    key_id = unverified_header.get("kid")
    if not key_id:
        return False

    jwk_dict = _verification_key_cache.get(key_id)
    if jwk_dict is None:
        response = client.webhook_verification_key_get(
            WebhookVerificationKeyGetRequest(key_id=key_id)
        )
        jwk_dict = response.key.to_dict()
        _verification_key_cache[key_id] = jwk_dict

    try:
        signing_key = jwt.PyJWK(jwk_dict).key
        payload = jwt.decode(jwt_header, signing_key, algorithms=["ES256"])
    except jwt.InvalidTokenError:
        return False

    issued_at = payload.get("iat")
    if issued_at is None or (time.time() - issued_at) > _MAX_WEBHOOK_AGE_SECONDS:
        return False

    expected_hash = payload.get("request_body_sha256")
    actual_hash = hashlib.sha256(raw_body).hexdigest()
    return expected_hash == actual_hash
