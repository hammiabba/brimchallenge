"""
Get readable text out of an invoice file.

Owner: Person A.
Input: file bytes + filename. Output: TextResult(text, was_ocr, method, warnings).

Order, cheapest reliable source first:
  1. PDF text layer via pdfplumber (layout kept, so columns stay aligned for the LLM)
  2. `pdftotext -layout` if pdfplumber found nothing and poppler is installed
  3. OCR with tesseract (eng+fra when the French data is installed) for scans and images
If no text can be produced (e.g. tesseract missing), `text` is empty and the pipeline
falls back to sending the file itself to the vision LLM.

Missing system binaries are reported as warnings, never raised, so the app runs on
machines without tesseract/poppler.
"""
from __future__ import annotations

import io
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

# Below this many letters/digits the "text layer" is really a scan with a stray header.
MIN_MEANINGFUL_CHARS = 50

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif", ".webp"}


@dataclass
class TextResult:
    text: str
    was_ocr: bool = False
    method: str = "none"           # "pdfplumber" | "pdftotext" | "ocr" | "none"
    warnings: list[str] = field(default_factory=list)
    pages: list[str] = field(default_factory=list)
    # Distinct invoice numbers found at the top of separate pages; more than one = several invoices in one file.
    invoice_numbers: list[str] = field(default_factory=list)


# "Invoice No: 000961", "INV NO : 853", "Facture n° FA-002399", "Credit note # CN-FA-000413".
_INVOICE_LABEL = re.compile(
    r"\b(?:invoice|inv|facture|credit\s+note|note\s+de\s+cr[ée]dit)\s*(?:no\b\.?|number|num[ée]ro|n[°º]|#)"
    r"\s*[:.]?\s*([A-Z0-9][A-Z0-9/-]*\d[A-Z0-9/-]*)",
    re.IGNORECASE,
)


def invoice_numbers_by_page(pages: list[str]) -> list[str]:
    """The first labelled invoice number on each page, de-duplicated in page order.

    Only the first label per page counts: a credit note's "original invoice no." further down the page
    must not look like a second invoice. A continuation page that repeats the header adds nothing.
    """
    found = []
    for page in pages:
        if m := _INVOICE_LABEL.search(page):
            number = m[1].upper()
            if number not in found:
                found.append(number)
    return found


def _with_invoice_check(result: TextResult) -> TextResult:
    result.invoice_numbers = invoice_numbers_by_page(result.pages)
    if len(result.invoice_numbers) > 1:
        result.warnings.append(
            f"document appears to contain {len(result.invoice_numbers)} invoices "
            f"({', '.join(result.invoice_numbers)}) on separate pages; only one draft is created from it, "
            f"so split the file and submit each invoice separately")
    return result


def meaningful_chars(text: str) -> int:
    return len(re.findall(r"[0-9A-Za-zÀ-ÿ]", text))


def _clean(text: str) -> str:
    # pdfplumber's layout mode pads every line to page width; trailing spaces and runs of
    # blank lines only cost tokens.
    lines = [ln.rstrip() for ln in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def is_image(filename: str) -> bool:
    return Path(filename).suffix.lower() in IMAGE_EXTS


def get_text(data: bytes, filename: str) -> TextResult:
    return _with_invoice_check(_get_text(data, filename))


def _get_text(data: bytes, filename: str) -> TextResult:
    if is_image(filename):
        return _ocr_image_bytes(data)
    if Path(filename).suffix.lower() != ".pdf" and not data.startswith(b"%PDF"):
        return TextResult("", warnings=[f"Unsupported file type: {filename}"])

    warnings: list[str] = []
    pages = _pdfplumber_pages(data, warnings)
    text = _clean("\n\n".join(pages))
    if meaningful_chars(text) >= MIN_MEANINGFUL_CHARS:
        return TextResult(text, method="pdfplumber", warnings=warnings, pages=pages)

    pages = _pdftotext_pages(data, warnings)
    text = _clean("\n\n".join(pages))
    if meaningful_chars(text) >= MIN_MEANINGFUL_CHARS:
        return TextResult(text, method="pdftotext", warnings=warnings, pages=pages)

    ocr = _ocr_pdf(data)
    ocr.warnings[:0] = warnings
    return ocr


def _pdfplumber_pages(data: bytes, warnings: list[str]) -> list[str]:
    try:
        import pdfplumber

        with pdfplumber.open(io.BytesIO(data)) as pdf:
            return [_clean(p.extract_text(layout=True) or "") for p in pdf.pages]
    except Exception as exc:  # corrupt PDFs must not crash the batch
        warnings.append(f"pdfplumber failed: {exc}")
        return []


def _pdftotext_pages(data: bytes, warnings: list[str]) -> list[str]:
    exe = shutil.which("pdftotext")
    if not exe:
        return []
    with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
        tmp.write(data)
        tmp.flush()
        try:
            out = subprocess.run([exe, "-layout", tmp.name, "-"], capture_output=True, timeout=60, check=True)
        except (subprocess.SubprocessError, OSError) as exc:
            warnings.append(f"pdftotext failed: {exc}")
            return []
    # pdftotext separates pages with a form feed.
    return [_clean(p) for p in out.stdout.decode("utf-8", errors="replace").split("\f") if p.strip()]


# ---------------------------------------------------------------- OCR

def ocr_available() -> bool:
    try:
        import pytesseract

        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def _ocr_lang() -> str:
    import pytesseract

    try:
        langs = set(pytesseract.get_languages(config=""))
    except Exception:
        return "eng"
    return "eng+fra" if "fra" in langs else "eng"


def _ocr_images(images) -> TextResult:
    if not ocr_available():
        msg = "OCR unavailable (tesseract not installed); file needs vision extraction"
        return TextResult("", method="none", warnings=[msg])
    import pytesseract

    lang = _ocr_lang()
    # psm 6 = "uniform block of text"; keeps table rows on one line better than the default.
    pages = [_clean(pytesseract.image_to_string(img, lang=lang, config="--psm 6")) for img in images]
    warnings = [] if lang == "eng+fra" else ["French OCR data not installed; using English only"]
    return TextResult(_clean("\n\n".join(pages)), was_ocr=True, method="ocr", warnings=warnings, pages=pages)


def _ocr_image_bytes(data: bytes) -> TextResult:
    from PIL import Image

    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception as exc:
        return TextResult("", warnings=[f"Could not open image: {exc}"])
    return _ocr_images([img.convert("L")])


def _ocr_pdf(data: bytes) -> TextResult:
    if not ocr_available():
        return _ocr_images([])  # produces the "OCR unavailable" result
    import pdfplumber

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        images = [p.to_image(resolution=300).original.convert("L") for p in pdf.pages]
    return _ocr_images(images)
