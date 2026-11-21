# extraction/

**Owner:** Person A. Feature 2: turn an invoice file (PDF, scan, French, credit note, USD) into a `DraftBill`.

## Public API
| Function | Returns |
|---|---|
| `pipeline.extract(data, filename, email_id=None, sender=None, repo=None, client=None)` | `DraftBill`; raises `LLMUnavailableError` / `ExtractionIncomplete` |
| `pipeline.extract_outcome(...)` | `ExtractionOutcome(status="ok" \| "llm_skipped" \| "failed", draft, text, warnings, error)`; never raises |
| `text_layer.get_text(data, filename)` | `TextResult(text, was_ocr, method, warnings)` |
| `vendor_match.resolve(vendor_on_invoice, sender, repo)` | `(VendorOnInvoice, warnings)` |
| `selfcheck.check(bill, was_ocr=..)` | `(field_confidence, warnings)` |

## Steps
1. **text_layer**: pdfplumber (layout) → `pdftotext -layout` → tesseract OCR (`eng+fra`). Below 50 letters/digits counts as "no text".
2. **llm_parser**: the prompt in `prompts/extract_invoice.md` plus structured outputs → `RawInvoice` (every value **as printed**).
   With no usable text, the image/PDF itself goes to the vision model.
   The API is sent `WireInvoice` (plain strings, `""` = not printed) because structured outputs allow at most
   16 union-typed fields; `to_raw()` converts it to `RawInvoice` (`None` = absent). Add new fields to both models.
3. **cache**: `backend/.cache/llm/{sha256}_p{prompt_version}_{model}.json`. A cache hit works without an API key.
4. **normalize**: money (`$1,234.56`, `-$1,042.76`, `4 362,67 $`) → `Decimal`; dates (ISO/EN/FR); tax labels
   (GST/TPS, HST/TVH, QST/TVQ, PST) → `TaxCode`; ship-to province from the bill-to address; OCR fixes on
   GST/QST numbers and bank digits only, each logged as a warning.
5. **vendor_match**: GST no. → bank account → sender domain → fuzzy name ≥ 90. Contradicting GST numbers downgrade or reject a candidate.
6. **selfcheck**: line maths, Σlines = subtotal, subtotal + taxes = total, tax ≈ rate × base. **Printed values are never changed.**

## How to change it safely
- **Prompt:** edit `prompts/extract_invoice.md` and bump `PROMPT_VERSION` (invalidates the cache). Keep it
  generic: never mention a specific vendor or layout.
- **New number/date/tax convention:** add a test case in `tests/extraction/test_normalize.py`, then extend `normalize.py`.
- **New arithmetic check:** `selfcheck.py` plus a test. Report problems; don't fix them.
- Run `pytest` (no network) and `python scripts/eval_extraction.py` (uses the cache) before pushing.

## Known limits
- Tesseract isn't required. Without it, scans go to the vision model (needs an API key).
- `contract_id`, `department_id` and `requester_user_id` are not on invoices. They stay `None` unless the
  invoice prints a dataset-style contract ID (`C018`).
