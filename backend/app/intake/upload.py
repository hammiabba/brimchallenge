"""
Manual upload: one file from the UI → DraftBill.

Owner: Person A.
Input: file bytes + original filename. Output: DraftBill (source.email_id = None).
Raises LLMUnavailableError (no API key and no cached result) or ExtractionIncomplete.
"""
from __future__ import annotations

from app.extraction.pipeline import extract
from app.extraction.text_layer import IMAGE_EXTS
from app.reference.repository import ReferenceRepository
from app.shared.schemas import DraftBill

ALLOWED_EXTS = {".pdf", *IMAGE_EXTS}


def process_upload(file_bytes: bytes, filename: str, *, repo: ReferenceRepository | None = None,
                   client=None) -> DraftBill:
    return extract(file_bytes, filename, repo=repo, client=client)
