"""
Auth settings, read from environment variables and the repo-root `.env`.

These live here rather than in app/config.py so the auth lane doesn't change the shared settings file. Same
loading rules as app/config.py: env vars win over `.env`, unknown keys are ignored.

SESSION_SECRET signs the session cookie. If it's empty, a random secret is generated at startup: everything still
works, but sessions end whenever the server restarts. Set it in `.env` for a stable demo.
"""
from __future__ import annotations

import logging
import secrets
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config import REPO_ROOT

log = logging.getLogger(__name__)


class AuthSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    session_secret: str | None = None
    session_cookie_name: str = "brim_session"
    session_ttl_hours: int = 8
    # None means "decide from the frontend origin": Secure everywhere except plain-http localhost.
    cookie_secure: bool | None = None
    # Comma-separated list. The Vite dev server by default.
    frontend_origins: str = "http://localhost:5173"
    # Largest request body accepted (uploads included).
    max_body_bytes: int = 10 * 1024 * 1024

    @field_validator("session_secret", "cookie_secure", mode="before")
    @classmethod
    def _empty_means_none(cls, v):
        return v if v not in ("", None) else None

    @property
    def origins(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.frontend_origins.split(",") if o.strip()]

    @property
    def secure_cookie(self) -> bool:
        if self.cookie_secure is not None:
            return self.cookie_secure
        local = ("http://localhost", "http://127.0.0.1")
        return not all(o.startswith(local) for o in self.origins)


@lru_cache
def get_auth_settings() -> AuthSettings:
    return AuthSettings()


@lru_cache
def session_secret() -> bytes:
    configured = get_auth_settings().session_secret
    if configured:
        return configured.encode()
    log.warning("SESSION_SECRET is not set: using a random secret, so sessions end when the server restarts.")
    return secrets.token_bytes(32)
