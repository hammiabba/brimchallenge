"""
File types intake accepts, by extension (the real type is checked from the bytes by extraction.filecheck).

Owner: Person A. Used by services/intake.queue_submission to refuse a file before it's queued.
"""
from __future__ import annotations

from app.extraction.text_layer import IMAGE_EXTS

ALLOWED_EXTS = {".pdf", *IMAGE_EXTS}
