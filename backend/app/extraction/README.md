# extraction/

**Owner:** Person A. Feature 2: turn an invoice file (PDF, scan, French, credit note, USD) into a `DraftBill`.

## Public API
| Function | Returns |
|---|---|
| `pipeline.extract(data, filename, email_id=None, sender=None, repo=None, client=None)` | `DraftBill`; raises `LLMUnavailableError` / `ExtractionIncomplete` |
| `pipeline.extract_outcome(...)` | `ExtractionOutcome(status="ok" \| "llm_skipped" \| "failed", draft, text, warnings, error)`; never raises |
| `text_layer.get_text(data, filename)` | `TextResult(text, was_ocr, method, warnings)` |
| `vendor_match.resolve(vendor_on_invoice, sender, repo)` | `(VendorOnInvoice, warnings)` |
| `selfcheck.check(bill, was_ocr=.., penalties=..)` | `(field_confidence, warnings)` |
| `selfcheck.badly_inconsistent(bill)` / `arithmetic_problems(bill)` | decides and scores the vision second opinion |
| `filecheck.problem(data, filename)` | `None` or one plain sentence (empty, wrong type, encrypted, corrupt) |
| `recheck.recheck(draft, confirmed)` / `recheck_bill(db, bill, changes)` | confidence and warnings after a clerk's edit; audited as `bill.rechecked` |

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
7. **vision second opinion**: OCR text whose total doesn't add up (or lines miss the subtotal by > 1%) is re-read
   once from the image by the vision model; the read with fewer arithmetic problems wins, a warning says which.
   Cached under `<sha256>-vision`. Born-digital PDFs are never re-read.

Before step 1, `filecheck` refuses files that can't be read (0 bytes, a Word file named `.pdf`, encrypted or
corrupt PDFs) with a sentence a clerk can forward, and `intake.files.keep` stores the original.
Several invoices in one PDF are detected per page and reported ("document appears to contain N invoices"), with
low confidence on the number and total; they are not split.

## Tests and fixtures
- `tests/fixtures/raw/<stem>.json`: what the model really returned for each of the 56 incoming files (prompt v4).
  `tests/conftest.py` `FixtureClient` / `replay_extract` replay them through the real pipeline, offline.
  Refresh after a prompt change: `python scripts/run_inbox.py && python scripts/record_fixtures.py`.
- `tests/extraction/test_batch_expectations.py`: expected values for all 56 files, derived from the PDFs.
- `tests/fixtures/synthetic/`: one invoice in five unseen layouts, recorded too; `RUN_LIVE_LLM=1 pytest -m live`
  re-checks them against the real model.

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
