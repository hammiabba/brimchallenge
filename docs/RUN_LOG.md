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

## Step 3: Robustness

### Vision second opinion
`pipeline._vision_second_opinion`: when the text came from **OCR** and the draft is badly inconsistent
(`selfcheck.badly_inconsistent`: total ≠ subtotal + taxes, or the lines miss the subtotal by more than 1%), the
image is sent once to the vision model. The result with fewer arithmetic problems wins (OCR on a tie), and a
warning names the one used. Both reads are cached (the vision read under `<sha256>-vision`). Born-digital PDFs are
never re-read: a re-read can't fix a total that is wrong on the document (Evergreen).
- **Decision:** tesseract isn't installed here and can't be (no Homebrew), so the real scans already go straight
  to vision. The fallback is tested with simulated OCR text: what tesseract would return, with one digit of the
  total misread.
- Offline: `tests/extraction/test_vision_fallback.py`, 7 tests (vision wins, both cached, vision no better → OCR
  kept, vision call fails → OCR kept with a warning, consistent OCR not re-read, a <1% line slip not re-read,
  text-layer PDFs never re-read).
- Live: `test_live_vision_second_opinion_fixes_misread_ocr[scan_8049.png|scan_8749.png]` → **2 passed**. The
  model read the misread total from the text, the check fired, and vision returned 6693.69 / 4719.28.

### Unseen layouts
`tests/fixtures/synthetic/make_layouts.py` renders one Laurentian invoice (V005, Montreal, GST + QST, 3 lines) as:
no table (prose), right-aligned totals, French labels with decimal commas and written-out dates, totals before the
lines; plus a Tessera USD invoice with a US address. `tests/extraction/test_synthetic_layouts.py`.

| layout | first run (prompt v3) | after the fixes (prompt v4) |
|---|---|---|
| table_less | core fields right; warning "currency not printed; assumed CAD" though the text says "Canadian dollars" | right, no warnings |
| right_aligned | right | right |
| french | right; "currency assumed CAD" (correct: only `$` is printed) | same (kept, it's true) |
| totals_first | right | right |
| usd | right; "unrecognised tax line 'Sales tax' $0.00" | right, no warnings |

All five extracted the same core fields (vendor, number, dates, currency, subtotal, taxes, total, province, line
count) on the first try. Two general fixes came out of it (Step 2 proper):
1. **Prompt v4:** currency is taken from the totals line when it shows one, otherwise from wherever the document
   states it in words ("Canadian dollars", "Amounts in US dollars", "dollars canadiens").
2. **A zero-amount tax line with an unknown label is dropped quietly** ("Sales tax $0.00" on a US invoice); an
   unknown label with a real amount still warns.

After the bump, all 56 files were re-extracted (246 s, 218,173 in / 25,711 out tokens, ≈ $1.39) and re-recorded,
plus the 5 layouts. Eval: still **100%** (135/135); batch expectations: 176/176; live synthetic: **5 passed**.
Offline, the layouts replay from `tests/fixtures/synthetic/raw/` on every `pytest`.

## Step 4: Flags end to end 📝

`tests/api/test_flags_end_to_end.py`: `POST /intake/inbox/jobs` on a fresh seeded DB, extraction replayed from
the fixtures, bills stored by the DB lane, controls run with the whole batch, flags read back via `GET /bills/{id}`.
One run per module (about 4 s). 46 passed, 1 xfailed.

| File | Expected | Actual | Result |
|---|---|---|---|
| Invoice HA26-2766 | VENDOR_LOOKALIKE | VENDOR_LOOKALIKE (block) | pass |
| Invoice 4443 (Blue Heron) | VENDOR_NOT_FOUND | VENDOR_NOT_FOUND (block) | pass |
| zephyrdataservic_7590 | VENDOR_NOT_FOUND | VENDOR_NOT_FOUND (block) | pass |
| cascadiacartagel_1625 | BANK_CHANGE_UNVERIFIED | BANK_CHANGE_UNVERIFIED (block), POSSIBLE_SPLIT | pass |
| scan_8049 (Cascadia 1624) | BANK_CHANGE_UNVERIFIED | BANK_CHANGE_UNVERIFIED, BANK_DETAILS_MISMATCH (block), POSSIBLE_SPLIT | pass |
| Invoice 000964 (Polar) | OVER_FUEL_SURCHARGE_CAP | OVER_FUEL_SURCHARGE_CAP (warn) | pass |
| northboundcourie_000639 | TAX_WRONG_FOR_PROVINCE | TAX_WRONG_FOR_PROVINCE (warn) | pass |
| beaumontrivieres_FA000557 | TAX_MISSING | TAX_MISSING (warn) | pass |
| signalsparrowcre_000970 | PST_ON_SERVICES | PST_ON_SERVICES (warn) | pass |
| ironwoodpalletco-inv-048 | a missing-tax flag | TAX_MISSING, PO_REQUIRED_MISSING | pass |
| evergreenenergyu_000850 | TOTAL_MISMATCH | TOTAL_MISMATCH (warn) | pass |
| northstarmediabu_NO261773 | LINE_MATH_ERROR | LINE_MATH_ERROR (warn) | pass |
| Summit 000809, Hardhat 853, Alpenglow, Brightline, Fixwell FA-000415 + CN, Ironwood, Keystone, Torque | PO_REQUIRED_MISSING | PO_REQUIRED_MISSING (block) on all 9 | pass |
| Invoice 000961 (Polar) | exact duplicate | DUPLICATE_EXACT (block) | pass |
| cloudbarnsoftwar_INV01561 | exact duplicate (paid by card) | DUPLICATE_EXACT (block) | pass |
| harlowsternllp_001468 | exact duplicate | DUPLICATE_EXACT (block) | pass |
| Brightline 583 (= FA-000583) | reformatted duplicate | DUPLICATE_EXACT (block) | pass |
| Voyageur 000903-A | near duplicate | DUPLICATE_EXACT (block) | **xfail**: controls (ISSUES_FOR_B #2) |
| Invoice 002935 (Queen Street rent) | no duplicate | no flags | pass |
| riverbendcaterin_1739 | pending-review vendor | VENDOR_PENDING_REVIEW, GST_NUMBER_MISSING, TAX_MISSING, PO_REQUIRED_MISSING | pass |

- **Cloudbarn:** the "paid by card" is the history invoice AP-00370, settled by AP virtual card (CT-00556), so
  the exact-duplicate flag is the right catch. No separate `ALREADY_PAID_BY_CARD` is expected.
- **Voyageur:** extraction reads `000903-A` exactly. Controls' `norm_invoice_no` keeps only the digits ("903"),
  which makes it an exact match. Payment is held either way. Strict xfail plus `ISSUES_FOR_B.md` item 2.
- **Unlisted block flags, explained:** Lumen FA-001761 and scan 1624 get `BANK_DETAILS_MISMATCH`. Both are dated
  before their vendor's bank change (BC-006 / BC-009) but print the new account, which matches the master today.
  Extraction is right; whether that should block is controls' call.

**Clean files** (no `block` flag; each checked on the PDF and master: active vendor, no PO required, bank as on
file, right tax for the province, arithmetic adds up, no earlier invoice with that number), 18 in all:
FA-000318, FA-001619, FA-002853, INV-00734, TR26-1042, Benefitwise 262, Granville GR26-2864, Great Lakes GR26-2271,
Harlow 001470, Lakeshore INV-03018, Lattice 557 (a `OVER_CONTRACT_RATE` warn only), Laurentian FA-002399, Ledgerline
FA-002176, Maple Tire 1531, Papertrail 2217, Place Mont-Royal FA-000566, Polar 000963, Prairie scan 8749. All pass.

## Step 5: Open decisions

- **`draft_json`:** kept as is. `as_extracted` is written at the first re-check and never overwritten (tested
  across two edits). Each re-check records a `bill.rechecked` audit event (actor `system`, before/after
  confidence and warnings, edited fields in the comment). The note stays in `ISSUES_FOR_DB.md` (open point 1).
- **Learned codings survive restarts:** `coding.feedback.replay_learned_codings(db)` rebuilds the in-memory store
  from every accepted/overridden line on an app bill. It's hooked once at start-up (`app/main.py`, its own commit
  `feat(api): call replay_on_startup from main`, `ISSUES_FOR_DB.md` hook 6) and honours test overrides of
  `get_session`. A missing DB is logged, not fatal. Tests: override → forget (restart) → replay → next suggestion
  cites the corrected bill; a new app start on the same DB replays it; history bills are never replayed.

## Step 6: A-owned endpoints 📝

**Decision:** main already serves `GET /intake/emails` (API lane: class, reason, items with bill ids, class filter,
pagination, `BACK_OFFICE_READ`). A second route on the same path would shadow it, so the list gains the suggested
action through an additive `EmailOut.suggested_action` field and one call, `app.intake.review.action_for(e)`, in
`services/intake.list_emails` (hook commit `feat(api): call action_for from list_emails`). A's router adds the
two missing reads.

**Decision:** approvers follow the matrix's treatment of intake reads (`/intake/emails`, `/intake/items`: C F X Au),
so they're refused. The router-wide guard in `main.py` (C F X) is removed; each A route has its own
`require_role(*BACK_OFFICE_READ)` (commit `feat(api): mount the intake router without a router-wide guard`).

**Decision:** the in-memory `/intake/upload`, `/intake/inbox/run` and `/intake/drafts` (with `_DRAFTS`) are
retired; `/submissions` and the inbox job replace them. `tests/api/test_intake_guard.py`, which tested the old
routes, is replaced by `tests/api/test_intake_review.py`.

**Decision:** originals are kept by content hash in `settings.files_dir` (`backend/files/`, gitignored), written by
the pipeline for every file it reads. `GET /intake/files/{file_hash}` serves them with the content type sniffed
from the bytes (`inline` for PDF/images, `nosniff`). It falls back to the dataset inbox for older items, checking
the hash. It only serves hashes that an intake item references, and rejects anything that isn't 64 hex characters.

Intake endpoints in `/openapi.json` (49 paths in all):

| Method | Path | Owner | Roles |
|---|---|---|---|
| GET | `/intake/emails` | API lane (+ A's `suggested_action`) | C F X Au |
| GET | `/intake/emails/{email_id}` | **A** | C F X Au |
| GET | `/intake/files/{file_hash}` | **A** | C F X Au |
| POST | `/intake/inbox/jobs` | API lane | C |
| GET | `/intake/inbox/jobs/{job_id}` | API lane | C F X Au |
| GET | `/intake/items` | API lane | C F X Au |
| GET/POST | `/submissions` | API lane | E C |

Tests (`tests/api/test_intake_review.py`, 19): EM-056 `reconcile_later`; EM-057 AP-00049 paid 2026-03-09 by EFT,
BRIM-EFT-26388945, with no bank numbers in the reply; EM-058 resend reply; EM-059 `ignore`; EM-029 links 2 bills;
the list shows the action on all 59 and filters by class; four back-office roles can read; employee and approver
get 403; unknown email 404 `email.not_found`; malformed or unknown hash 404; PDF and PNG served byte-exact with
the right type; the inbox fallback works. Matrix rows in their own commit.

**Live smoke test** (uvicorn on a fresh seeded SQLite DB, real LLM cache so no API cost), trimmed:
```
1. POST /auth/login U004 -> 200 {"user_id":"U004","role":"ap_clerk"}
2. POST /intake/inbox/jobs ... done in 3.1 s: 59 emails, 56 items, 56 bills, 0 failed
3. GET /intake/emails?email_class=payment_inquiry -> 200 [{"email_id":"EM-057","action":"answer_status"}]
   GET /intake/emails/EM-057 -> 200 "Invoice 1743 (AP-00049, 369.75 CAD, dated 2026-02-04) was paid on 2026-03-09
   by EFT, reference BRIM-EFT-26388945."  reply: "Hello, Invoice 1743 dated 2026-02-04 was paid on 2026-03-09 by
   EFT (369.75 CAD), reference BRIM-EFT-26388945. Best regards, Accounts Payable, Harborline Logistics"
4. POST /submissions Invoice HA26-2766.pdf -> 202; item ok, bill AP-00450 with warning "already_received: this
   exact file was already received as bill AP-00450 ... no new bill was created" (the inbox had it as EM-026)
5. GET /bills/AP-00450 -> 200 V052 HA26-2766 6452.30 needs_review, flags [VENDOR_LOOKALIKE block],
   line 1 suggested 6310 / D08 "Harlow and Stern LLP's default GL account (no past invoices to learn from)"
6. PATCH /bills/AP-00450 requester U013 -> 200, line 1 department D01 "...; department D01 from requester U013"
   PATCH /bills/AP-00450/lines/1 6420/D01 -> 200 coding_status overridden
7. GET /intake/files/43bef153... -> 200 application/pdf, 2457 bytes, identical to the PDF on disk,
   inline; filename="Invoice HA26-2766.pdf"
   employee U013 GET /intake/emails/EM-057 -> 403
```
The smoke test showed the step-6 reason still started with the original "· D08 Executive" label, which read as a
contradiction. The suffix now says "(replaces D08)".

## Step 7: Quality gate 📝

- Merged `origin/main` again (frontend scaffold, controls tax fixes #23, DB override carry-over #26); clean merge.
- `pytest` offline: **1272 passed, 1 xfailed** (ISSUES_FOR_B #2), 9 live deselected, ~60 s (105 s with coverage).
- `RUN_LIVE_LLM=1 pytest -m live`: **9 passed** in 61 s (HA26-2766, Laurentian, 2 vision fallbacks, 5 layouts).
- Coverage (`pytest-cov`, now a dev dependency) on `intake/ extraction/ coding/ reference/` +
  `api/routes_intake.py`: **95%**. Below 90%: `extraction/pipeline.py` 89% (defensive branches) and
  `reference/csv_repository.py` 87% (getters controls reads through its own `RefData`); details in the handoff.
  Raised from 91% by offline tests for OCR (fake tesseract), `pdftotext`, the triage LLM tie-break and replay edge
  cases.
- `ruff check .`: clean repo-wide.
- Dead code: `intake.upload.process_upload` (its only caller was the retired `/intake/upload`) removed. No TODOs
  in A's folders. READMEs (intake, extraction, coding, api) and DECISIONS 59–66 updated;
  `docs/PERSON_A_HANDOFF.md` written.
- Attribution: `git log origin/main..HEAD --format=%B` finds nothing. `git grep -inE "co-authored|generated with|claude
  code"` (excluding CLAUDE.md, .claude/) finds only files this branch doesn't touch: the DB lane's alembic migration
  docstrings ("Generated with `alembic revision --autogenerate`", a tool, not attribution) and the team's
  `docs/HACKATHON_PLAN.md`. The branch's own diff adds none.
- Not tracked: `.env`, `.cache/`, `output/`, `files/`, `*.db`, `CLAUDE_CODE_PROMPT_*.md` (left untracked).

# Intake UI run (2026-11-21)

## 1. Sync

- `a/extraction` is merged (PR #27). Since then main gained PR #28 `ui/bills` (the bills pages), #29 controls
  coverage map, #30 low-confidence flag. `frontend/openapi.json` on main predates the intake endpoints from #27;
  `npm run gen:api` regenerates it (each page branch carries the same regenerated, byte-identical files).
- **Found and fixed outside git:** 228 iCloud sync-conflict copies (`README 2.md`, `backend/app/main 2.py`,
  `frontend/src 2/`, a second `0002_audit_chain_unique 2.py` migration that gave alembic two heads, `.git/index 2`,
  …) plus 3 numbered copies (`tests/fixtures/raw/Invoice 288.json` = `Invoice 287.json`, 4444 = 4443,
  854 = 853). All were untracked, byte-identical or older than the originals. They broke `pytest` (duplicate tests,
  alembic "multiple heads"). **Decision:** moved, not deleted, to `../brimchallenge-sync-duplicates/` with their
  paths kept. The repo sits in an iCloud-synced Desktop folder, so this can recur. Moving the repo out of
  Desktop/Documents (or turning off "Desktop & Documents" sync) stops it.
- Backend on main: `alembic upgrade head`, seed (4167 rows), `pytest`: **1332 passed, 1 xfailed**; ruff clean.
- Frontend on main (Node 24 via nvm, per `.nvmrc`; the default `node` is 20): `npm ci`, `gen:api`, typecheck,
  lint, **162 tests in 13 files**, build: all pass.

## 2. Voyageur: exact duplicate by design (branch `a/voyageur-exact-test`)

Person B keeps `000903-A` vs `000903` as `DUPLICATE_EXACT`: `DUPLICATE_LIKELY` is only `warn`, so the bill
wouldn't be held although the original (AP-00277) is paid; the Redline `1655-A` vs `FA-001655` double payment in
history is caught only because the suffix is stripped. The strict xfail became
`test_suffixed_number_is_an_exact_duplicate` (block, matched against AP-00277). `ISSUES_FOR_B.md` #2 is closed by
design; the handoff and the HACKATHON_PLAN §4 row now say exact duplicate. `pytest`: 1332 passed, 0 xfailed.
