"""
LLM step: invoice text (or the file itself) → RawInvoice, with every value as printed.

Owner: Person A.
Input: text from text_layer, or raw image/PDF bytes when there is no usable text.
Output: RawInvoice (strings, not typed values). normalize.py does the typing.

Why strings: the model copies, the code parses. That keeps rounding and "helpful"
corrections out of the model, and puts number/date parsing in tested Python.

Structured outputs (`messages.parse` with a Pydantic `output_format`) guarantee
the response matches the schema, so there's no JSON-in-text scraping.

Two models on purpose: the API rejects schemas with more than 16 union-typed
parameters, so the model fills WireInvoice (plain strings, "" = not printed) and
`to_raw()` converts it to RawInvoice (None = absent), which the rest of the app uses.

To change the prompt: edit prompts/extract_invoice.md and bump PROMPT_VERSION.
That changes the cache key, so old results are not reused.
Tests must never reach the network: pass a fake `client` (see tests/extraction/test_pipeline.py).
"""
from __future__ import annotations

import base64
import re
from functools import cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from app.config import get_settings

PROMPT_PATH = Path(__file__).parent / "prompts" / "extract_invoice.md"
MAX_ATTEMPTS = 3


class LLMUnavailableError(RuntimeError):
    """No API key configured. Callers can still use the text layer and classification."""


class LLMExtractionError(RuntimeError):
    """The model answered but not with a usable invoice (refusal, truncation, repeated failure)."""


# ---------------------------------------------------------------- intermediate model

class RawLine(BaseModel):
    description: str
    quantity: str | None
    unit_price: str | None
    amount: str | None
    line_type: Literal["goods", "services"]


class RawTax(BaseModel):
    label: str
    rate: str | None
    amount: str


class RawInvoice(BaseModel):
    """Everything as printed on the document. Field docs live in the prompt file."""

    document_type: Literal["invoice", "credit_note", "statement", "other"]
    vendor_name: str
    vendor_address: str | None
    vendor_gst_number: str | None
    vendor_qst_number: str | None
    vendor_email: str | None
    invoice_number: str | None
    invoice_date: str | None
    due_date: str | None
    payment_terms: str | None
    currency: str | None
    bill_to_name: str | None
    bill_to_address: str | None
    ship_to_address: str | None
    po_number: str | None
    po_field_present: bool
    contract_reference: str | None
    lines: list[RawLine] = Field(description="One entry per billed line, in document order")
    subtotal: str | None
    taxes: list[RawTax]
    total: str | None
    bank_institution: str | None
    bank_transit: str | None
    bank_account: str | None


# ---------------------------------------------------------------- wire model (what the API fills)
# Same fields as the Raw* models, but union-free: "" means "not printed on the document".
# Keep both in sync when adding a field; to_raw() fails loudly if they drift.

_ABSENT = 'Empty string "" if not printed'


class WireLine(BaseModel):
    description: str
    quantity: str = Field(description=_ABSENT)
    unit_price: str = Field(description=_ABSENT)
    amount: str = Field(description=_ABSENT)
    line_type: Literal["goods", "services"]


class WireTax(BaseModel):
    label: str
    rate: str = Field(description=_ABSENT)
    amount: str


class WireInvoice(BaseModel):
    document_type: Literal["invoice", "credit_note", "statement", "other"]
    vendor_name: str
    vendor_address: str
    vendor_gst_number: str
    vendor_qst_number: str
    vendor_email: str
    invoice_number: str
    invoice_date: str
    due_date: str
    payment_terms: str
    currency: str = Field(description='ISO code from the totals line, e.g. "CAD" or "USD"; "" if no code is printed')
    bill_to_name: str
    bill_to_address: str
    ship_to_address: str
    po_number: str = Field(description='PO number as printed; "" if absent or the PO field is blank')
    po_field_present: bool
    contract_reference: str
    lines: list[WireLine] = Field(description="One entry per billed line, in document order")
    subtotal: str
    taxes: list[WireTax]
    total: str
    bank_institution: str
    bank_transit: str
    bank_account: str


def _opt(s: str) -> str | None:
    s = s.strip()
    return s or None


def to_raw(wire: WireInvoice) -> RawInvoice:
    """Wire → internal model: strip strings; "" / whitespace-only become None for optional fields."""
    required = {"document_type", "vendor_name", "po_field_present", "lines", "taxes"}
    data = {k: (v.strip() if isinstance(v, str) else v) if k in required else _opt(v)
            for k, v in wire.model_dump(exclude={"lines", "taxes"}).items()}
    data["lines"] = [RawLine(description=ln.description.strip(), quantity=_opt(ln.quantity),
                             unit_price=_opt(ln.unit_price), amount=_opt(ln.amount), line_type=ln.line_type)
                     for ln in wire.lines]
    data["taxes"] = [RawTax(label=t.label.strip(), rate=_opt(t.rate), amount=t.amount.strip())
                     for t in wire.taxes]
    return RawInvoice(**data)


# ---------------------------------------------------------------- prompt

@cache
def load_prompt() -> tuple[str, str]:
    """Returns (version, prompt body). The version is part of the cache key."""
    text = PROMPT_PATH.read_text(encoding="utf-8")
    m = re.match(r"PROMPT_VERSION:\s*(\S+)\s*\n", text)
    if not m:
        raise ValueError(f"{PROMPT_PATH} must start with 'PROMPT_VERSION: <n>'")
    return m[1], text[m.end():].strip()


def prompt_version() -> str:
    return load_prompt()[0]


# ---------------------------------------------------------------- client

def make_client():
    s = get_settings()
    if not s.llm_enabled:
        raise LLMUnavailableError(
            "ANTHROPIC_API_KEY is not set. Add it to .env to enable LLM extraction "
            "(classification and the text layer work without it)."
        )
    import anthropic

    return anthropic.Anthropic(api_key=s.anthropic_api_key)


_MEDIA_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".gif": "image/gif", ".webp": "image/webp", ".pdf": "application/pdf"}


def _content(text: str | None, file_bytes: bytes | None, filename: str) -> list[dict]:
    if text:
        return [{"type": "text", "text": f"Document text (file: {filename}):\n\n{text}"}]
    if file_bytes is None:
        raise ValueError("Need either text or file bytes")
    media = _MEDIA_TYPES.get(Path(filename).suffix.lower())
    if media is None:
        raise LLMExtractionError(f"No text and unsupported file type for vision: {filename}")
    data = base64.standard_b64encode(file_bytes).decode("ascii")
    block_type = "document" if media == "application/pdf" else "image"
    return [
        {"type": block_type, "source": {"type": "base64", "media_type": media, "data": data}},
        {"type": "text", "text": f"Extract the document above (file: {filename})."},
    ]


def parse_invoice(text: str | None, *, file_bytes: bytes | None = None, filename: str = "",
                  client=None) -> RawInvoice:
    """Call the LLM and return a validated RawInvoice.

    Pass `text` when the text layer worked, otherwise `file_bytes` for vision.
    `client` is injectable for tests; by default one is built from settings.
    """
    import anthropic

    s = get_settings()
    client = client or make_client()
    _, system = load_prompt()
    content = _content(text, file_bytes, filename)

    last_error: Exception | None = None
    for _attempt in range(MAX_ATTEMPTS):
        try:
            resp = client.messages.parse(
                model=s.llm_model,
                max_tokens=16000,
                system=system,
                messages=[{"role": "user", "content": content}],
                output_format=WireInvoice,
                output_config={"effort": s.llm_effort},
            )
        except (anthropic.APIConnectionError, anthropic.RateLimitError, anthropic.InternalServerError) as exc:
            # The SDK already retries these with backoff; one more round here covers longer blips.
            last_error = exc
            continue
        if resp.stop_reason == "refusal":
            raise LLMExtractionError(f"Model declined to extract {filename}")
        if resp.stop_reason == "max_tokens":
            last_error = LLMExtractionError(f"Output truncated for {filename}")
            continue
        if resp.parsed_output is not None:
            return to_raw(resp.parsed_output)
        last_error = LLMExtractionError(f"No parsed output for {filename}")
    raise LLMExtractionError(f"LLM extraction failed for {filename}: {last_error}") from last_error
