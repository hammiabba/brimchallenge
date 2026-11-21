"""
Signed session cookie: `base64url(payload_json) + "." + base64url(hmac_sha256(secret, payload))`.

Stdlib only (hmac + hashlib), so no new dependency. The cookie holds the user id, an issue time, an expiry and a
random session id; it holds no role or permissions. The user row is re-read on every request (see deps.py), so a
role change or termination takes effect on the user's next call.

Trade-off: the session is stateless, so logout clears the cookie but can't revoke a copy of it before it expires.
Server-side revocation needs a sessions table.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass

from app.auth.settings import get_auth_settings, session_secret


@dataclass(frozen=True)
class SessionData:
    user_id: str
    issued_at: int
    expires_at: int
    session_id: str


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(payload: bytes, secret: bytes) -> str:
    return _b64(hmac.new(secret, payload, hashlib.sha256).digest())


def issue(user_id: str, *, now: int | None = None, secret: bytes | None = None) -> str:
    """A signed cookie value for `user_id`, valid for SESSION_TTL_HOURS."""
    now = int(time.time()) if now is None else now
    ttl = get_auth_settings().session_ttl_hours * 3600
    payload = json.dumps({"uid": user_id, "iat": now, "exp": now + ttl, "sid": secrets.token_urlsafe(12)},
                         separators=(",", ":"), sort_keys=True).encode()
    return f"{_b64(payload)}.{_sign(payload, secret or session_secret())}"


def verify(token: str | None, *, now: int | None = None, secret: bytes | None = None) -> SessionData | None:
    """The session in `token`, or None if it is missing, malformed, tampered with or expired."""
    if not token or token.count(".") != 1:
        return None
    body, signature = token.split(".")
    try:
        payload = _unb64(body)
    except (ValueError, TypeError):
        return None
    # Constant-time comparison, so the signature can't be guessed byte by byte from response timing.
    if not hmac.compare_digest(signature, _sign(payload, secret or session_secret())):
        return None
    try:
        data = json.loads(payload)
        session = SessionData(user_id=str(data["uid"]), issued_at=int(data["iat"]),
                              expires_at=int(data["exp"]), session_id=str(data["sid"]))
    except (ValueError, KeyError, TypeError):
        return None
    now = int(time.time()) if now is None else now
    if session.expires_at <= now:
        return None
    return session
