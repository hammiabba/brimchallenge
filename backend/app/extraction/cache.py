"""
Disk cache for LLM extraction results.

Owner: Person A.
Key: sha256 of the file bytes + prompt version + model name. The same file with the
same prompt and model never hits the API twice, which keeps the demo fast, cheap
and reproducible. Editing the prompt (and bumping PROMPT_VERSION) or switching
models changes the key automatically.

Location: settings.cache_dir/llm/ (gitignored). Delete the folder to force re-extraction.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from app.config import get_settings


def file_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _path(file_hash: str, prompt_version: str, model: str) -> Path:
    safe_model = re.sub(r"[^A-Za-z0-9._-]", "_", model)
    return get_settings().cache_dir / "llm" / f"{file_hash}_p{prompt_version}_{safe_model}.json"


def get(file_hash: str, prompt_version: str, model: str) -> dict | None:
    p = _path(file_hash, prompt_version, model)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None  # a half-written file from a crash: treat as a miss


def put(file_hash: str, prompt_version: str, model: str, payload: dict) -> None:
    p = _path(file_hash, prompt_version, model)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)  # atomic, so readers never see a partial file
