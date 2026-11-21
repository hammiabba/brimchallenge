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
| 18 | DB | Money as INTEGER cents (`*_cents`) beside `currency`; rates, quantities and unit prices as exact-decimal TEXT | SQLite stores `Numeric` as float; cents and text keep money and rates exact. |
| 19 | DB | Timestamps stored as naive UTC; an ORM hook converts aware datetimes | SQLite drops the offset silently (15:00-05:00 is stored as 15:00). |
| 20 | DB | One `bills` table for history and app bills, IDs continuing `AP-#####`; no UNIQUE on (vendor, invoice number) or `payments.bill_id` | The duplicate checks must see the history's repeats: 5 repeated numbers, 3 double payments. |
| 21 | DB | Named CHECK constraints through a naming convention | Errors name the rule that failed, and SQLite batch migrations can only alter named constraints. |
| 22 | DB | `audit_events` is append-only via BEFORE UPDATE / DELETE triggers, with an AUTOINCREMENT `seq` and no FK or CHECK on the actor | The database itself guarantees the log can't be rewritten, and it never rejects an event. |
| 23 | DB | Vendor bank details versioned in `vendor_bank_accounts`, with a partial unique index allowing one open account per vendor | Bank changes are controlled actions, and each payment records which version it paid. |
| 24 | DB | users ↔ departments foreign keys are deferrable; the baseline is SQLite-only | The cycle needs deferred checks to seed. A Postgres port needs its own trigger and a separate FK step. |
| 25 | DB | Separation of duties also enforced as CHECKs: bank-change verifier ≠ requester, payment releaser ≠ preparer, delegate ≠ actor | Defense in depth under the controls rules. |
| 26 | DB | Relative SQLite URLs resolve against the repo root | `.env.example`'s `./backend/ap.db` then works from any working directory. |
| 27 | DB | `bills.draft_json` is the frozen extraction snapshot; the current bill state is rebuilt from columns and line tables | Corrections stay auditable as 'extracted vs corrected'; one source of truth for controls input. |
| 28 | DB | `approval_decisions` stores both `actor_role` (user role) and `step_role` (route step) | The dataset uses step names as roles; one mixed column would make role queries ambiguous. |
| 29 | DB | The seed is insert-only: ON CONFLICT DO NOTHING on the primary key, natural-key checks for autoincrement tables | A re-seed never overwrites app edits to vendors, users, policies or bills; a second run inserts 0 rows. |
| 30 | DB | The seed pre-flight checks every row against rules read from the schema (NOT NULL, CHECKs, FKs) and writes nothing if any fails | Every violation is reported at once, and the Python rules can't drift from the migration. |
| 31 | DB | Money with more than 2 decimals is rejected at seed time, never rounded | Silent rounding would change amounts that controls checks to the cent. |
| 32 | DB | History `bill_taxes` built with controls' `_history_taxes`, and `norm_invoice_number` with `norm_invoice_no` | The database and the controls engine agree on tax codes and duplicate keys by construction. |
| 33 | DB | History `actor_role` taken from users.csv at seed time | approvals.csv records only the step name; the user's role at the time isn't in the dataset. |
| 34 | DB | BC-009 seeded as `pending_verification` while V004's open account is already the new one | That's what happened: the change was applied without a callback, which is exactly what controls must flag. |
