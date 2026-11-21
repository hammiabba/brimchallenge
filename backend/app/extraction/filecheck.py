"""
Is this file something we can read at all? Checked before any text extraction or LLM call.

Owner: Person A.
Input: file bytes + original filename. Output: None when readable, else one plain-English sentence a
clerk can act on ("The PDF is password-protected; ask the vendor for an unprotected copy.").

The file type comes from its first bytes, not its name, so a Word document renamed to .pdf is caught
here instead of failing deep inside the PDF parser with a stack trace.
"""
from __future__ import annotations

import io
from pathlib import Path

from app.extraction.text_layer import IMAGE_EXTS

# First bytes of each format we accept (and of the usual impostors, for a better message).
_SIGNATURES = [
    (b"%PDF", "pdf"),
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpeg"),
    (b"GIF87a", "gif"), (b"GIF89a", "gif"),
    (b"II*\x00", "tiff"), (b"MM\x00*", "tiff"),
    (b"BM", "bmp"),
    (b"PK\x03\x04", "zip"),           # .docx / .xlsx / .zip
    (b"\xd0\xcf\x11\xe0", "ole"),     # old .doc / .xls
]
_NAMES = {"zip": "a Word/Excel document or ZIP archive", "ole": "an old-format Word/Excel document"}


def sniff(data: bytes) -> str | None:
    """The real file type from its first bytes, or None if unknown."""
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    # Some generators put a few bytes (BOM, whitespace) before %PDF; readers accept up to 1 KB.
    if b"%PDF" in data[:1024]:
        return "pdf"
    return next((kind for sig, kind in _SIGNATURES if data.startswith(sig)), None)


def problem(data: bytes, filename: str) -> str | None:
    ext = Path(filename).suffix.lower()
    if not data:
        return "The file is empty (0 bytes); ask the sender to resend it."
    if ext != ".pdf" and ext not in IMAGE_EXTS:
        return f"Unsupported file type {ext or '(no extension)'}; send the invoice as a PDF or an image."
    kind = sniff(data)
    if kind is None or kind in _NAMES:
        expected = "a PDF" if ext == ".pdf" else "an image"
        found = _NAMES.get(kind or "", "not a format we can read")
        return f"{filename} is named like {expected} but is {found}; ask the sender for the original PDF."
    # A PDF named .png (or a scan named .pdf) is still readable: real_name() routes it by content.
    return _pdf_problem(data) if kind == "pdf" else _image_problem(data)


def real_name(data: bytes, filename: str) -> tuple[str, str | None]:
    """`filename` with the extension its content actually has, plus a warning when they differ."""
    kind = sniff(data)
    ext = Path(filename).suffix.lower()
    if kind == "pdf" and ext != ".pdf":
        return f"{filename}.pdf", f"{filename} is a PDF despite its name; read as a PDF"
    if kind not in (None, "pdf", *_NAMES) and ext == ".pdf":
        return f"{filename}.{kind}", f"{filename} is a {kind.upper()} image despite its name; read as an image"
    return filename, None


def _pdf_problem(data: bytes) -> str | None:
    import pdfplumber

    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            if not pdf.pages:
                return "The PDF has no pages; ask the sender to resend it."
            pdf.pages[0].extract_text()
    except Exception as exc:
        if "password" in f"{type(exc).__name__} {exc!r}".lower():
            return "The PDF is password-protected; ask the vendor for an unprotected copy."
        return "The PDF is damaged and can't be opened; ask the sender to resend it."
    return None


def _image_problem(data: bytes) -> str | None:
    from PIL import Image

    try:
        with Image.open(io.BytesIO(data)) as img:
            img.load()
    except Exception:
        return "The image is damaged and can't be opened; ask the sender to resend it."
    return None
