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
    if is_image(filename):
        return _ocr_image_bytes(data)
    if Path(filename).suffix.lower() != ".pdf" and not data.startswith(b"%PDF"):
        return TextResult("", warnings=[f"Unsupported file type: {filename}"])

    warnings: list[str] = []
    text = _pdfplumber_text(data, warnings)
    if meaningful_chars(text) >= MIN_MEANINGFUL_CHARS:
        return TextResult(text, method="pdfplumber", warnings=warnings)

    text = _pdftotext(data, warnings)
    if meaningful_chars(text) >= MIN_MEANINGFUL_CHARS:
        return TextResult(text, method="pdftotext", warnings=warnings)

    ocr = _ocr_pdf(data)
    ocr.warnings[:0] = warnings
    return ocr


def _pdfplumber_text(data: bytes, warnings: list[str]) -> str:
    try:
        import pdfplumber

        with pdfplumber.open(io.BytesIO(data)) as pdf:
            pages = [p.extract_text(layout=True) or "" for p in pdf.pages]
        return _clean("\n\n".join(pages))
    except Exception as exc:  # corrupt PDFs must not crash the batch
        warnings.append(f"pdfplumber failed: {exc}")
        return ""


def _pdftotext(data: bytes, warnings: list[str]) -> str:
    exe = shutil.which("pdftotext")
    if not exe:
        return ""
    with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
        tmp.write(data)
        tmp.flush()
        try:
            out = subprocess.run([exe, "-layout", tmp.name, "-"], capture_output=True, timeout=60, check=True)
        except (subprocess.SubprocessError, OSError) as exc:
            warnings.append(f"pdftotext failed: {exc}")
            return ""
    return _clean(out.stdout.decode("utf-8", errors="replace"))


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
    text = "\n\n".join(pytesseract.image_to_string(img, lang=lang, config="--psm 6") for img in images)
    warnings = [] if lang == "eng+fra" else ["French OCR data not installed; using English only"]
    return TextResult(_clean(text), was_ocr=True, method="ocr", warnings=warnings)


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
