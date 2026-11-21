# Design decisions

One line per decision: **what** and **why**. Add to this file when you make a choice someone could ask about in the Q&A.

| # | Area | Decision | Why |
|---|---|---|---|
| 1 | Stack | FastAPI + Pydantic v2 | The contract is already Pydantic; FastAPI gives typed endpoints, `/docs` for free, and an OpenAPI spec to generate frontend types from. |
| 2 | Stack | One `backend/pyproject.toml` with a `[dev]` extra | A single source of dependencies; `pip install -e "backend[dev]"` works the same for all four of us. |
| 3 | Extraction | LLM maps text → fields, then deterministic code normalizes and self-checks | Templates/regex break on the hidden batch's unseen layouts. The LLM handles layout; code handles maths, and maths is checkable. |
| 4 | Extraction | The LLM returns values **as printed** (strings); Python parses money/dates into `Decimal`/`date` | Keeps the LLM from "helpfully" rounding or fixing numbers, and puts parsing in tested code. |
| 5 | Extraction | Structured outputs with a Pydantic schema (`messages.parse`) | Output always matches the schema; no fragile JSON-in-text parsing. |
| 6 | Extraction | Keep printed values even when the maths is wrong; record a warning | Wrong vendor maths is a finding for controls (TOTAL_MISMATCH, LINE_MATH_ERROR), not something to hide. |
| 7 | Extraction | Disk cache keyed by sha256(file) + prompt version + model | Reruns are free and deterministic for the demo; changing the prompt invalidates automatically. |
| 8 | Extraction | Text layer first, OCR if under ~50 meaningful chars, vision LLM if OCR is unavailable | The cheapest reliable source first; scans still work on a machine without tesseract. |
| 9 | Extraction | OCR fixes only on structured IDs (GST no., transit, account), each logged as a warning | Those have known shapes, so a fix is verifiable; free text is never "corrected". |
| 10 | Vendor | Match order: GST number → bank account → sender domain → fuzzy name ≥ 90 | The master has lookalikes (V026/V052, V002/V053). Names are the weakest evidence, so they come last, and the method is recorded. |
| 11 | Intake | Rules-first email classifier with EN+FR keywords; LLM only as a tie-break | Deterministic and explainable for the common cases; subject and body can be in different languages, so both are scored. |
| 12 | Coding | Vendor history → vendor default GL → global description similarity | History is the best predictor of how this company codes a vendor; each tier lowers confidence and says why. |
| 13 | Data | `ReferenceRepository` Protocol with a CSV implementation | Person A can build now without waiting for the DB; the DB team swaps in a SQL-backed class without touching callers. |
| 14 | Money | `Decimal` everywhere | Float rounding errors make arithmetic checks and duplicate matching unreliable. |
| 15 | Time | Fixed `AS_OF_DATE` from config | The dataset is frozen at 2026-11-02; using the real clock would make results drift. |
| 16 | Intake | Pipeline returns an `ExtractionOutcome` wrapper (ok / llm_skipped / failed) | `DraftBill` requires an invoice number and date, so a failed or skipped extraction can't be a DraftBill; no schema change needed. |
| 17 | Extraction | The LLM fills a union-free `WireInvoice` (plain strings, `""` = not printed); `to_raw()` converts it to `RawInvoice` (`None` = absent) | Structured outputs reject schemas with more than 16 union-typed parameters (we had 23 → HTTP 400). Keeping `None` inside the app means normalize/pipeline/cache don't change, and the wire schema has headroom for new fields. A test guards the count. |
