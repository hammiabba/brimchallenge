# Person A run log

Decisions, checkpoints and results from the end-to-end run of Person A's work (intake, extraction, coding, A's
endpoints). Newest section last.

## Step 0: Pre-flight (2026-11-21)

- `.env` at the repo root has one non-empty `ANTHROPIC_API_KEY` line; `.env` is not tracked.
- `get_settings().llm_enabled` is True; model `claude-opus-5-5`.
- One real call through `make_client()` (max_tokens 5): `end_turn`, 12 tokens in / 5 out. The key works.
- `origin/main` had moved (PRs #19 to #24: API UI support, inbox default department, history back-fill, controls
  polish). Merged into `a/extraction`.
  - One conflict, `backend/app/services/intake.py` `store_outcome`: main added `department_id` and
    `department_source` to the `bill.created` audit payload; our side had changed `else:` to
    `elif bill_id is None:` for the idempotency hook. Resolved by keeping both: main's payload, our `elif`.
  - Full suite after the merge: **978 passed**, 2 live deselected. `ruff check .` is now clean repo-wide
    (Person B fixed the `controls/` lint, so `ISSUES_FOR_B.md` item 1 is closed).
- **Decision:** main now has its own `GET /intake/emails` (API lane, `routes_intake_jobs.py`, paginated `EmailOut`).
  Step 6 will not add a second route with the same path; see Step 6.
- **Decision:** token usage is now recorded per file (`ExtractionOutcome.usage`, also stored in the cache entry),
  so `run_inbox.py` can report the cost of a run. Cache hits report nothing (they cost nothing).

## Step 1: Real extraction run 📝

**Live tests:** `RUN_LIVE_LLM=1 pytest -m live -v` → 2 passed (HA26-2766, Laurentian FA-002399) in 15 s.

**Inbox run** (`rm -rf backend/.cache/llm && python scripts/run_inbox.py`):

| | |
|---|---|
| Emails | 59: invoice 53, credit_note 2, statement 1, payment_inquiry 1, missing_attachment 1, not_ap 1 |
| Attachments | 56: **ok 56**, failed 0, llm_skipped 0 |
| Runtime | 254 s, sequential (about 4.5 s per file) |
| Tokens | 213,413 in / 25,670 out |
| Cost | ≈ $1.37 at Opus 5.5 list price ($4 / $20 per MTok), ≈ $0.024 per file. Reruns are free (cache). |

The two scans (`scan_8049.png`, `scan_8749.png`) went to the vision model: tesseract isn't installed on this machine
(and there is no Homebrew to install it), so the OCR step reports "OCR unavailable" and the pipeline sends the
image. Both were read exactly: GST and transit came back clean, so no OCR-fix warnings were needed. The OCR-fix
path stays covered by the offline test with noisy values (`test_scan_without_ocr_goes_to_vision_with_id_fixes`).

**Fixtures:** `python scripts/record_fixtures.py` → 56 files in `backend/tests/fixtures/raw/` (224 KB). The replay
helper is `FixtureClient` / `fake_client_from_fixtures` / `replay_extract` in `tests/conftest.py`: the real pipeline
runs, only the model call is answered from the fixture (picked by the file name in the request).

**Eval** (`python scripts/eval_extraction.py`, 11 golden files):

| field | accuracy | n |
|---|---|---|
| vendor_id | 100% | 11 |
| invoice_number | 100% | 11 |
| invoice_date | 100% | 11 |
| due_date | 100% | 11 |
| currency | 100% | 11 |
| is_credit_note | 100% | 11 |
| subtotal | 100% | 11 |
| total | 100% | 11 |
| ship_to_province | 100% | 11 |
| po_number | 100% | 11 |
| line_count | 100% | 11 |
| tax (per code) | 100% | 14 |
| **overall** | **100%** | 135 |

No mismatches, so no suspected golden-file errors. (The golden files are still `"verified": false`; their values
agree with the independent reference below on every field.)

**Batch expectations** (`tests/extraction/test_batch_expectations.py`, all 56 files, offline on the fixtures):
**176 passed.** Expected values were derived without our pipeline:
- a one-off regex reader over the pdfplumber text of the 54 PDFs (invoice number, dates, currency, totals, taxes,
  bill-to province, line count, blank PO labels), reviewed by hand;
- the two scans read by eye from the images;
- `vendor_id` from the printed GST number in `vendors.csv`; the three vendors with no GST printed (Riverbend V054,
  Sparkgrid V018, Tessera V016) by their master record; Blue Heron and Zephyr are not in the master (None);
- the arithmetic was recomputed from the PDF text: only Evergreen 000850 (total) and Northstar NO26-1773
  (line 1) are wrong on the document, which is exactly where our warnings fire.

Checked per file: vendor, number, dates, currency, province, credit note, subtotal, total, taxes by code, line
count, arithmetic warnings (only the two files above), blank-PO warning (exactly the 8 files that print an empty
PO label), USD at the invoice-date rate, credit notes negative, scan IDs.

Notes from the run, no fix needed:
- Hardhat 853 is a PO-required vendor but prints no PO label at all, so there is no "PO blank" warning;
  controls' `PO_REQUIRED_MISSING` works from `requires_po` + no PO, which still covers it.
- Summit 000809 is dated 2026-11-27, after the as-of date. Kept as printed; controls owns `DATE_ANOMALY`.

## Step 2: Fixes from the real run

Nothing to fix: 56/56 extracted, 100% on the golden eval and on all 56 expectation rows. Accuracy before = after =
100%. Remaining effort goes to unseen-layout robustness (Step 3), which is what the hidden batch tests.
