"""
Settings owned by the DB layer, read from environment variables and the repo-root `.env` (same file as config.py).

Owner: DB team. Kept separate from app/config.py (shared by the whole team) so DB-only secrets don't change the
shared settings class.

AUDIT_HMAC_KEY: the secret key for the audit log's bank-account fingerprints (HMAC-SHA256). It must be at least 32
characters of randomness, e.g. `python -c "import secrets; print(secrets.token_hex(32))"`. It is a SecretStr, so it
never shows up in reprs, logs or error messages. It is optional here on purpose: importing this module never fails,
and app.db.audit raises a clear error only when it actually needs a fingerprint.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config import REPO_ROOT


class DbSettings(BaseSettings):
    """DB-layer settings. Environment variables override `.env`; names have no prefix (AUDIT_HMAC_KEY)."""

    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", env_prefix="", extra="ignore")

    AUDIT_HMAC_KEY: SecretStr | None = None


@lru_cache
def get_db_settings() -> DbSettings:
    """The process-wide DbSettings, read once. Tests that change the environment call get_db_settings.cache_clear()."""
    return DbSettings()
