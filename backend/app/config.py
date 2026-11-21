"""
Runtime settings, read from environment variables and the repo-root `.env`.

Owner: shared (any change here affects everyone; mention it in the team chat).
Use `get_settings()` everywhere instead of reading os.environ directly, so tests
can override values in one place.

Why AS_OF_DATE lives here: the dataset is frozen at 2026-11-02. Business logic
(overdue, "future-dated invoice", contract expiry) must compare against that date,
never against the machine clock, or results change depending on when the demo runs.
"""
from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    as_of_date: date = date(2026, 11, 2)
    dataset_dir: Path = REPO_ROOT / "dataset" / "brim_ap_dataset"

    anthropic_api_key: str | None = None
    llm_model: str = "claude-opus-5-5"
    llm_effort: str = "medium"

    database_url: str = f"sqlite:///{BACKEND_DIR / 'ap.db'}"

    cache_dir: Path = BACKEND_DIR / ".cache"
    output_dir: Path = BACKEND_DIR / "output"
    files_dir: Path = BACKEND_DIR / "files"  # original invoice files by sha256 (intake/files.py)

    # An empty value in .env (DATASET_DIR=) should mean "use the default", not "current directory".
    @field_validator("dataset_dir", "cache_dir", "output_dir", "files_dir", mode="before")
    @classmethod
    def _empty_path_means_default(cls, v, info):
        if v in (None, ""):
            return cls.model_fields[info.field_name].default
        return v

    @field_validator("anthropic_api_key", mode="before")
    @classmethod
    def _empty_key_means_none(cls, v):
        return v or None

    @property
    def llm_enabled(self) -> bool:
        return bool(self.anthropic_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
