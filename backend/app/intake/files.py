"""
The original files behind bills, kept by content hash so a reviewer can see the document next to the bill.

Owner: Person A.
- keep(data): called by the extraction pipeline for every file it reads; writes <files_dir>/<sha256> once.
- load(db, file_hash): (bytes, content type, file name) for GET /intake/files/{file_hash}, or None. Falls back
  to the dataset inbox folder for files read before keep() existed, checking the hash so a renamed file can't
  stand in for another.

The content type comes from the file's first bytes, never from its name. Only PDFs and images are served for
display; anything else is served as a download (application/octet-stream).
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import models
from app.extraction.filecheck import sniff

_HASH = re.compile(r"[0-9a-f]{64}")
CONTENT_TYPES = {"pdf": "application/pdf", "png": "image/png", "jpeg": "image/jpeg", "gif": "image/gif",
                 "tiff": "image/tiff", "bmp": "image/bmp", "webp": "image/webp"}


def _dir() -> Path:
    return get_settings().files_dir


def keep(data: bytes) -> str:
    """Store the bytes under their sha256 (idempotent) and return the hash."""
    h = hashlib.sha256(data).hexdigest()
    path = _dir() / h
    if not path.exists() and data:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)  # atomic, so a reader never sees half a file
    return h


def content_type(data: bytes) -> str:
    return CONTENT_TYPES.get(sniff(data) or "", "application/octet-stream")


def load(db: Session, file_hash: str) -> tuple[bytes, str, str] | None:
    if not _HASH.fullmatch(file_hash or ""):
        return None  # also rules out paths like ../../.env
    items = list(db.scalars(select(models.IntakeItem).where(models.IntakeItem.file_hash == file_hash)
                            .order_by(models.IntakeItem.item_id)))
    if not items:
        return None  # only files that came through intake are served
    name = items[0].file_name
    stored = _dir() / file_hash
    if stored.exists():
        data = stored.read_bytes()
    else:
        data = _from_inbox(items, file_hash)
        if data is None:
            return None
    return data, content_type(data), name


def _from_inbox(items: list[models.IntakeItem], file_hash: str) -> bytes | None:
    inbox = get_settings().dataset_dir / "incoming_invoices"
    for item in items:
        path = inbox / Path(item.file_name).name
        if path.is_file():
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() == file_hash:
                return data
    return None
