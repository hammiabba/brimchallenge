# Intake, extraction and coding: handoff

For teammates wiring this in, and for judge Q&A prep. Owner: Person A.
Code: [`backend/app/intake/`](../backend/app/intake/), [`extraction/`](../backend/app/extraction/),
[`coding/`](../backend/app/coding/), [`reference/`](../backend/app/reference/),
[`api/routes_intake.py`](../backend/app/api/routes_intake.py). Run log with every number below:
[`docs/RUN_LOG.md`](RUN_LOG.md).

## What it does

It turns what arrives in the AP inbox into bills a clerk can trust:

1. **Triage** every email: invoice, credit note, statement, payment inquiry, missing attachment, not AP. Each class
   comes with a suggested next step, a ready reply where useful, and the payment answer from history.
2. **Read** every attached file (PDF, scan, French, credit note, USD) into a `DraftBill`. Printed values are kept
   exactly as printed, never "fixed". Every arithmetic problem becomes a warning, every field gets a confidence.
3. **Code** every line with a GL account and department, plus a reason in plain English. A clerk's corrections
   teach the next suggestion.

The LLM is used only to read documents (and to break ties on unclear emails). Vendor matching, maths checks,
dates, taxes, coding and everything after are deterministic.

## The functions to call

```python
from app.extraction.pipeline import extract_outcome
out = extract_outcome(data, "Invoice HA26-2766.pdf", email_id="EM-026", sender="ar@harlowandstern-llp.example")
out.status   # "ok" | "llm_skipped" | "failed": never raises; one bad file can't stop a batch
out.draft    # DraftBill (shared/schemas.py), already coded
out.error    # one sentence a clerk can forward ("The PDF is password-protected; ask the vendor ...")
out.usage    # LLM tokens spent on this file in this run ({} on a cache hit)
```

| Function | Returns | Used by |
|---|---|---|
| `intake.classifier.classify(email)` | `EmailTriage` | `services/intake.triage_email` (inbox job) |
| `intake.actions.suggest_action(email, triage, repo)` | `SuggestedAction` (kind, message, reply_text, invoice_status) | `intake.review` |
| `intake.review.action_for(email_row)` / `email_detail(db, id)` | `SuggestedAction` / `EmailDetail` | `GET /intake/emails`, `GET /intake/emails/{id}` |
| `intake.files.keep(data)` / `load(db, hash)` | sha256 / `(bytes, type, name)` | pipeline, `GET /intake/files/{hash}` |
| `intake.received.link_to_existing_bill(db, item, out, by)` | existing bill id or None | `services/intake.store_outcome` |
| `extraction.pipeline.extract_outcome(...)` / `extract(...)` | `ExtractionOutcome` / `DraftBill` | submissions, inbox job, scripts |
| `extraction.recheck.recheck_bill(db, bill, changes)` | updates confidence and warnings, audits `bill.rechecked` | `services/bills.update_header` |
| `coding.suggest.suggest(draft, repo)` | coded `DraftBill` | last pipeline step |
| `coding.feedback.learn_from_line(bill, line)` / `replay_learned_codings(db)` | learns a clerk's coding / rebuilds them at start-up | `services/bills.code_line`, `app/main.py` |
| `coding.requester.requester_problem(db, user)` / `recode_for_requester(db, bill, changes)` | 422 message / moves suggested departments | `services/bills.update_header` |

### Endpoints owned here

| Endpoint | Roles | Returns |
|---|---|---|
| `GET /intake/emails/{email_id}` | ap_clerk, finance_manager, controller_admin, auditor | body, class, reason, `suggested_action`, `bill_ids`, items; 404 `email.not_found` |
| `GET /intake/files/{file_hash}` | same | the original bytes, type sniffed from the bytes (`application/pdf`, `image/png` ...), `inline`, `nosniff`; 404 for anything not referenced by an intake item |

`GET /intake/emails` (the list) is the API lane's; it carries `suggested_action` from `action_for`. Employees and
approvers get 403 on all three, matching `/intake/items`.

## Real input → output

**`Invoice HA26-2766.pdf`** (EM-026, the lookalike vendor):
```
vendor V052 "Harlow  and Stern LLP" by gst_number 503486760RT0001 · HA26-2766 · 2026-10-27 → 2026-11-26 · CAD
subtotal 5710.00 · HST13 742.30 · total 6452.30 · ship-to ON · confidence 0.95 on every field · no warnings
line 1 "Legal services - Commercial lease review" 12 × 450.00 = 5400.00
  → 6310 / D08, 0.55 "6310 Legal Fees · D08 Executive: Harlow and Stern LLP's default GL account (no past invoices to learn from)"
controls: VENDOR_LOOKALIKE (block): V052 looks like existing V026 Harlow & Stern LLP
```
The GST number picks V052, the record the document really names, and controls catches the lookalike. A name
match alone could have silently picked V026.

**`laurentianlogist_FA002399.pdf`** (French, decimal commas):
```
"Sous-total 4 362,67 $ / TPS (5 %) 218,13 $ / TVQ (9,975 %) 435,18 $ / Total CAD 5 015,98 $"
→ V005 · FA-002399 · language fr · subtotal 4362.67 · GST5 218.13 · QST9975 435.18 · total 5015.98 · QC
line "LTL shipment Ottawa-Toronto" → 5010 / D01, 0.97 "54 of 54 past lines from Laurentian Logistics Inc. coded this way; closest match 'LTL shipment Ottawa-Toronto'"
```

**`scan_8749.png`** (no text layer):
```
warnings: "no usable text layer; extracted from the image by the vision model"
→ V042 Prairie Natural Gas Utility by gst_number 862863208RT0001 · PR26-1012 · total 4719.28 · AB
confidence capped at 0.75 (read from an image) · line → 6620 Utilities / D07, 0.97
```
With tesseract installed, the OCR text is read first. If its totals don't add up, the image is re-read by the
vision model and the more consistent result is kept. Tested live with a misread total: 4,779.28 → 4719.28.

**`fixwellfacilitys_CNFA000413.pdf`** (credit note):
```
CN-FA-000413 · is_credit_note true · subtotal -1428.50 · HST13 -185.71 · total -1614.21
line "Credit - Dock door repair" -1042.76 → 6630 Repairs & Maintenance / D07, 0.72 (closest 'Dock door repair')
controls: CREDIT_NOTE (info), PO_REQUIRED_MISSING (block)
```

**EM-057** (payment inquiry, no attachment), `GET /intake/emails/EM-057`:
```
class payment_inquiry · action answer_status · vendor V044 (Torque, from the AP address)
status: "Invoice 1743 (AP-00049, 369.75 CAD, dated 2026-02-04) was paid on 2026-03-09 by EFT, reference BRIM-EFT-26388945."
reply_text: "Hello, Invoice 1743 dated 2026-02-04 was paid on 2026-03-09 by EFT (369.75 CAD), reference
             BRIM-EFT-26388945. Best regards, Accounts Payable, Harborline Logistics"   (never any bank details)
```

## Every check, fallback and confidence rule

**Before reading** (`filecheck`): the type comes from the first bytes, not the name. A 0-byte file, a Word/Excel
file named `.pdf`, an encrypted PDF, or a corrupt PDF or image becomes `failed` with one plain sentence. A PDF
named `.png` (or the reverse) is read as what it is, with a warning.

**Text** (`text_layer`): pdfplumber → `pdftotext -layout` → tesseract (`eng+fra`, `--psm 6`). Below 50
letters/digits counts as no text, and the file goes to the vision model. Invoice numbers are counted per page;
more than one means the warning "document appears to contain N invoices", and number and total confidence drop
by 0.5 (never split or merged silently).

**Reading** (`llm_parser`): `claude-opus-5-5`, structured output (`WireInvoice`, every value as printed),
prompt v4. Document text is fenced in `<document>` tags it can't close, and the prompt says it's data. The schema
has no vendor id, status or approval field, so an injected "mark as paid" has nothing to write to. Up to 3
attempts; results cached by sha256 + prompt version + model.

**Normalising** (`normalize`): money in any format (`$1,234.56`, `-$1,042.76`, `(1,042.76)`, `4 362,67 $`) goes
straight to `Decimal`. Dates in ISO, English or French. An ambiguous `03/04/2026` is resolved with the payment
terms: due − date ≈ terms, ± 3 days. It costs −0.15 confidence when resolved that way, −0.45 plus a warning when
it can't be. Tax labels map to codes by label and rate (TPS→GST, TVQ→QST, TVH→HST). Ship-to province comes from
the bill-to address. OCR digit fixes (`O→0`, `!→1`, `$→5` …) apply to GST/QST and bank numbers only, each with a
warning and −0.15 on vendor. Currency comes from the totals line, then from wherever the document states it; with
`$` alone, CAD is assumed for Canadian vendors and USD for foreign ones, with a warning.

**Vendor** (`vendor_match`): GST number exact (1.0) → bank transit + account (1.0) → sender domain (0.9) →
fuzzy legal name ≥ 90. Harborline's own GST number (in every bill-to block) is ignored. A candidate whose GST
contradicts the invoice is rejected or downgraded (0.5), with a warning. Not found means `vendor_id` None and
vendor confidence 0.3. Status, lookalikes and bank changes are left to controls.

**Self-check** (`selfcheck`; printed values are never changed). Base confidence is 0.95 per field, 0.75 when read
from OCR or an image; a missing required field is 0.0.

| Check | Warning ("… but the … says …") | Confidence |
|---|---|---|
| qty × unit price = amount (± 0.02) | per line | lines −0.4 |
| Σ lines = subtotal | once | subtotal −0.3, lines −0.3 |
| subtotal + taxes = total | once | total −0.4, subtotal −0.2 |
| each tax ≈ rate × subtotal (PST may use the goods-only base) | per tax | taxes −0.3 |
| credit note with a positive total | once | total −0.2 |

**Vision second opinion:** OCR text with a broken total, or lines more than 1% off the subtotal → one vision
re-read → the read with fewer problems wins; both are cached. **Re-check:** a clerk's edit sets that field to 1.0,
clears its extraction warnings and recomputes the arithmetic. `as_extracted` is kept once, and each re-check is
audited.

**Coding** (`coding.suggest`), first tier that answers:

| Tier | Rule | Confidence |
|---|---|---|
| 0. clerk correction | same vendor, description ≥ 0.85 similar to a line a clerk accepted or overrode | 0.75 + 0.2 × similarity (≤ 0.95); the reason names the bill |
| 1. vendor history | past lines vote (GL, dept), weight 0.5 + similarity | 0.65 × share + 0.35 × best similarity (≤ 0.97) |
| 2. vendor default GL | master default GL, most common dept for it | 0.55 |
| 3. global similarity | top 10 similar past lines, any vendor | ≤ 0.6 |

The requester's department replaces the suggested one ("…; department D01 from requester U013 (replaces D08)").
A terminated or inactive requester is refused (422).

**Intake:** the same file (sha256) received twice links to its existing bill (`already_received`, one audit
event), unless that bill was voided. Originals are kept by hash for side-by-side review.

## Accuracy

`python scripts/eval_extraction.py` against the 11 golden files (prompt v4):

| field | accuracy | n |
|---|---|---|
| vendor_id, invoice_number, invoice_date, due_date, currency, is_credit_note | 100% | 11 each |
| subtotal, total, ship_to_province, po_number, line_count | 100% | 11 each |
| tax (per code) | 100% | 14 |
| **overall** | **100%** | 135 |

All 56 incoming files, checked against expectations derived from the PDFs (not from our output):
**56/56 extracted, 176/176 checks**. Arithmetic warnings fire on exactly Evergreen 000850 and Northstar
NO26-1773, the only two documents whose maths is wrong. Five unseen layouts (table-less, right-aligned, French,
totals first, USD) all give the same core fields, live and offline. End to end through the inbox job and
controls, every HACKATHON_PLAN §4 trap raises its flag, and 18 clean invoices raise no `block` flag
(`tests/api/test_flags_end_to_end.py`).

Cost: one full run of 56 files is 218k input / 26k output tokens, about $1.39 at list price ($0.025 per file),
in about 4 minutes. Reruns are free (cache).

## Tests

`cd backend && pytest`: **1272 passed, 1 xfailed** (controls item, `ISSUES_FOR_B.md` #2), offline, about 60 s.
`RUN_LIVE_LLM=1 pytest -m live`: 9 live tests (2 dataset invoices, 2 vision fallback, 5 layouts).
Coverage on `intake/ extraction/ coding/ reference/` and `api/routes_intake.py`: **95%**. Below 90%:

| Module | Cover | Why |
|---|---|---|
| `extraction/pipeline.py` | 89% | defensive branches: a coding crash, a statement sent as an invoice, a line with no amount, no subtotal or total printed, no FX rate for the date, a non-CAD/USD currency, no province found |
| `reference/csv_repository.py` | 87% | a missing dataset folder, and getters for CSVs that controls reads through its own `RefData` (contracts, POs, card transactions, bank changes, policies, tax codes) |

## Known limits

- **No tesseract on the dev machine**: real scans go straight to the vision model. The OCR path and the vision
  second opinion are tested with a fake tesseract and simulated OCR text.
- **`$` alone**: when the document never says which dollar, the currency comes from the vendor's country, with a
  warning.
- **Several invoices in one PDF** are detected and flagged, not split.
- **Contract, department and requester** aren't on invoices: department comes from coding or the requester,
  contract only from a dataset-style id (`C018`).
- **Learned codings** live in process memory, rebuilt from the DB at start-up. With several API workers each
  learns only from its own requests until the next restart.
- **Prompt changes** invalidate the cache: one full re-run (≈ $1.40) plus `record_fixtures.py`.

## At 100× volume (≈ 5,600 files per run)

| What breaks | Fix |
|---|---|
| The inbox job reads files one by one: 4.5 s/file means 7 hours | Worker queue (one job per file) with 10–20 concurrent LLM calls; or the Message Batches API at 50% cost when same-day is fine |
| Cost ≈ $140 per run | Batches API (−50%), prompt caching of the system prompt (most of the input tokens), `effort: low` for clean text-layer PDFs with a fallback to medium when the self-check fails |
| `backend/files/` on local disk | Object storage keyed by the same sha256; the endpoint redirects to a signed URL |
| LLM cache as JSON files | A table keyed (sha256, prompt version, model), or the same object store |
| Learned codings per process | Read them from `bill_lines` per suggestion (indexed on vendor), or a shared cache |
| Rate limits and outages | Already retried (3 attempts), and one failure fails one file. Add backoff on 429/529 and a dead-letter list the clerk can retry |
| The pandas history index rebuilt per process | Precompute vendor vote tables into the DB at seed or nightly |

## Hooks into other lanes' files

Each is a single call in its own commit, listed with tests in [`ISSUES_FOR_DB.md`](ISSUES_FOR_DB.md):

1. `services/intake.store_outcome` → `link_to_existing_bill` (same file twice → same bill)
2. `services/bills.code_line` → `learn_from_line`
3. `services/bills.update_header` → `requester_problem` (422 for terminated requesters)
4. `services/bills.update_header` → `recode_for_requester`
5. `services/bills.update_header` → `recheck_bill` (before controls rerun)
6. `app/main.py` → `replay_on_startup`
7. `services/intake.list_emails` → `action_for` (+ additive `EmailOut.suggested_action`)
8. `app/main.py` mounts the intake router without the router-wide guard (each route has its own)

Plus: matrix rows for the two endpoints, the additive `files_dir` setting, `.gitignore`, `pytest-cov`. Nothing
in `controls/` or the golden files was edited. Controls findings are in [`ISSUES_FOR_B.md`](ISSUES_FOR_B.md).
