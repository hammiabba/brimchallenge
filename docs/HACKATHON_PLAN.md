# Brim AP Hackathon: Features Team Plan

Put this file in the repo root (or link it from CLAUDE.md) so every Claude Code session knows the plan.

## 1. Scope: what to perfect

The judges test the required features on a **hidden batch of invoices**. That batch goes through intake, extraction, validation and duplicate checks, so those four features earn the accuracy points.

| # | Feature | Level | Owner |
|---|---------|-------|-------|
| 1 | Invoice intake (upload + inbox) | **Perfect** | Features A |
| 2 | Data extraction (PDF, scan, FR) | **Perfect** | Features A |
| 3 | Smart coding | **Perfect** (cheap once #2 works) | Features A |
| 4 | Validation & matching | **Perfect** | Features B |
| 5 | Duplicate detection | **Perfect** | Features B |
| 6 | Approval workflow (routing rules) | **Perfect** | Features B (rules) + DB team (storage, admin edit) |
| — | Role enforcement (server-side) | **Perfect**, it applies to everything | DB team |
| 8 | Audit trail | Solid. Comes almost free from an append-only event table | DB team |
| 7 | Payments | Simple but correct (release limits + separation of duties) | DB team (state) + B (`can_release` rule) |
| 9 | Vendor management | Simple. The controlled bank-change action is what matters | DB team |

**Bonus features that fall out of this work:** (a) an alert on suspicious bank changes or lookalike senders, and (b) an approval recommendation with a reason, built directly from the flags list.

## 2. Features team split

### Person A: "Document → Draft Bill" pipeline (features 1, 2, 3)

**1. Email classifier (inbox/emails.json, 59 emails)**
- Classes: `invoice`, `credit_note`, `statement`, `payment_inquiry`, `marketing/spam`, `invoice_missing_attachment`.
- Edge cases in the sample:
  - EM-029 has **2 attachments**, so it produces 2 draft bills.
  - EM-056 is a statement. EM-057 asks where a payment is. EM-059 is marketing.
  - EM-058 says "invoice attached" but has **no attachment**. Route it to the clerk to request the file.
  - Subject and body languages don't always match (French body under an English subject, and the reverse). Classify from content, not keywords alone.

**2. Extraction**
- Step 1: `pdftotext -layout`. If the text is empty or garbage, it's a scan, so use OCR (tesseract) or a vision LLM.
- Step 2: an LLM with a **strict JSON schema** maps the text to fields. Don't hand-write regex per template, because the hidden batch will have layouts you haven't seen. Regex is fine as a *cross-check*.
- Step 3: **self-validate**: line qty × unit price = amount, sum of lines = subtotal, subtotal + taxes = total. Any failure lowers the confidence and marks the field for human review.
- Things to handle:
  - French number format `4 362,67 $`
  - French labels (TPS/TVQ/TVH, Facture n°, Sous-total)
  - Credit notes with negative amounts
  - USD totals (`Total USD`)
  - OCR noise: `RT000!` should be `RT0001`, `Transit $5541` should be `55541`
  - The **bill-to address gives ship_to_province**
- Map each tax line to a tax code: HST13, GST5, PST7_BC, QST9975, EXEMPT, FOREIGN.
- **Vendor resolution:** match on GST number, then bank account, then sender email domain, then fuzzy name. Return the candidate plus *how* it matched. Don't match on name alone: the master contains lookalikes.
- Cache LLM results to disk by file hash. This makes the demo fast, repeatable and cheap.

**3. Smart coding**
- For each line, propose a GL account and department using the vendor's history in invoice_lines. Fall back to the vendor's `default_gl_account`, then to keyword similarity across all history.
- Show the reason, for example: *"5010: 18 of 20 past Polar Freight lines; similar description 'LTL shipment…'"*.
- Department comes from the requester when one exists, otherwise from the vendor's history.

**Deliverable:** `extract(file) -> DraftBill` and `classify(email) -> EmailClass`, plus an eval script that runs all 56 files against ~15 hand-labelled ground-truth files and prints field accuracy.

### Person B: Controls engine (features 4, 5, 6, plus payment-release rules)

Write everything as **pure functions with unit tests**: input in, list of `Flag` out. This is easy to test, and easy to defend in the Q&A.

**4. Validation & matching checks**
- **Vendor**
  - Not in the master
  - Status `pending_review` / inactive
  - GST number on the invoice ≠ master
  - **Bank details on the invoice ≠ master**
  - Recent bank change not verified by callback
- **Tax:** expected tax from ship_to_province + line type:
  - ON → HST 13%
  - AB/MB/SK → GST 5%
  - BC → GST 5% + PST 7% on **goods only**
  - QC → GST 5% + QST 9.975%
  - Insurance → exempt
  - Foreign vendor → no Canadian tax
- **Arithmetic:** lines, subtotal, total.
- **Contract**
  - Fuel surcharge % over the cap
  - Hourly rate over the cap
  - Fixed monthly fee ≠ contract fee
  - Over the not-to-exceed monthly amount
  - Contract expired
- **PO**
  - Vendor `requires_po` but no PO on the invoice → hold (P13)
  - Total > PO remaining balance (P12)
  - PO closed, or belongs to another vendor
- **FX:** USD → CAD at the invoice-date rate from fx_rates.
- **Dates:** invoice date in the future, due date before invoice date, very old invoices.

**5. Duplicate detection** (score each match and show the evidence)
- **Exact:** same vendor + same invoice number.
- **Normalized:** strip non-alphanumerics, leading zeros and prefixes (`FA-000583` = `583`, `000903-A` vs `000903`).
- **Near:** same vendor, amount within ~1%, date within ~14 days.
- **Cross-vendor:** same amount and bank account under a lookalike vendor record.
- **Already paid by card:** card_transactions merchant descriptor (fuzzy) + amount_cad + date window.
- ⚠️ **Avoid false positives:** rent, SaaS and other fixed monthly contracts bill the *same amount every month*. Matching amount alone ≠ duplicate. Also require invoice-number similarity or the same service period.
- **Split detection:** same vendor, several invoices just under $10k within a short window. History vendor V037 has 11 invoices between $8k and $10k.

**6. Approval routing:** `route(invoice, users, policies) -> [steps]`
- Amount tiers P01–P04 (on CAD total).
- Extra finance step for new or pending vendors (P05) and for the Legal category (P06).
- Requester = approver → escalate to the manager (P07).
- Approver on leave → delegate (P08), recorded as a delegation.
  - U012 (Facilities) is on leave with delegate U003, who is *also* the finance manager. Don't let one person fill two steps; escalate to the controller.
- Terminated users (U015) can't approve, and their old requests need re-ownership.
- The approver's `approval_limit_cad` must be ≥ the invoice amount for that step.
- Read policies from the DB so the admin can edit them. No hard-coding.

**Payment release:** `can_release(user, payment, approval_chain)`
- Finance manager ≤ $100k, controller above that (P09–P10).
- **Anyone who approved the invoice can never release its payment** (P11).
- Hold release when there's an open block flag (bank mismatch, unverified bank change, duplicate).

**Deliverable:** `validate(draft) -> [Flag]`, `find_duplicates(draft) -> [Match]`, `route(bill) -> [Step]`, `can_approve(...)`, `can_release(...)`, plus unit tests using the known cases in §4.

## 3. Shared contract: agree with the DB team in hour 1

```jsonc
DraftBill {
  source: {email_id?, file_name, file_hash},
  vendor: {vendor_id?, name_on_invoice, gst_number, bank: {inst, transit, account}, match_method, match_score},
  invoice_number, invoice_date, due_date, currency, is_credit_note,
  ship_to_province, po_number?, 
  lines: [{description, quantity, unit_price, amount, line_type: "goods"|"services",
           suggested_gl, suggested_dept, coding_reason, tax_codes: []}],
  subtotal, taxes: [{code, rate, amount}], total, total_cad, fx_rate,
  field_confidence: {field: 0..1}, extraction_warnings: []
}
Flag  { code: "TAX_WRONG_PROVINCE", severity: "block"|"warn"|"info",
        message: "AB delivery charged HST 13%, expected GST 5%",
        evidence: {expected, found, source_ids} }
Step  { step_no, role, user_id, reason: "P02 amount > $10k", delegated_from? }
```

**DB team owns:**
- Schema + loading all CSVs as-is
- Auth / session + **server-side role middleware**
- Append-only `audit_event` table + a single `log_event()` helper that every endpoint calls
- Invoice / payment state machines
- Vendor CRUD + bank-change workflow
- Policies table (admin-editable)

**Features team owns:** the logic modules above, called by their endpoints.

Use one fixed "today" = **2026-11-02** (the dataset's as-of date) everywhere.

## 4. Known cases in the incoming batch (use as tests)

From my analysis of the 56 files and 59 emails. Not exhaustive: the hidden batch will have more of the same kinds.

| File / email | Expected flag |
|---|---|
| `Invoice 000961.pdf` (Polar), `cloudbarnsoftwar_INV01561.pdf`, `harlowsternllp_001468.pdf` | **Exact duplicate** of history. Cloudbarn's was paid by card |
| `brightlinesafety-inv-032.pdf` "583" | **Reformatted duplicate** of history FA-000583 |
| `voyageurcorporat-inv-017.pdf` "000903-A" | **Exact duplicate** of history 000903 (suffix stripped on purpose, so it blocks: see ISSUES_FOR_B #2) |
| `Invoice 002935.pdf` (Queen St rent, $18,758) | Same amount every month = **contract rent, NOT a duplicate** |
| `Invoice 4443.pdf` Blue Heron, `zephyrdataservic_7590.pdf` | **Vendor not in master** |
| `riverbendcaterin_1739.pdf` | Vendor **pending_review**, requires PO but none, no GST number, no tax charged |
| EM-026 / `Invoice HA26-2766.pdf` "Harlow **and** Stern LLP" from `harlowandstern-llp.example` | **Lookalike** of V026 "Harlow **&** Stern" (`harlow.example`). Different GST and bank. V052 exists in the master too, so a name match "succeeds". Also Legal → P06 |
| V053 "Great Lakes Carriers **Incorporated**" in master | Lookalike vendor record of V002 |
| `cascadiacartagel_1625.pdf`, `scan_8049.png` (Cascadia, V004) | Bank change BC-009 on 2026-10-27 via **email, not callback-verified** → hold payment |
| `Invoice 000964.pdf` Polar | Fuel surcharge **22%** vs contract cap 12% (C018) |
| `northboundcourie_000639.pdf` | Ships to **AB** but charged **HST 13%** (expected GST 5%) |
| `beaumontrivieres_FA000557.pdf` | Ships to **QC**, charged GST only, **missing QST** |
| `signalsparrowcre_000970.pdf` | BC **PST 7% charged on services** (PST is goods-only) |
| `ironwoodpalletco-inv-048.pdf` | Ontario delivery, **no tax** charged |
| `evergreenenergyu_000850.pdf` | **Total wrong**: 3,180 + 159 = 3,339, but the invoice says 3,439 |
| `northstarmediabu_NO261773.pdf` | **Line math wrong**: 24 × 150 = 3,600, but the line says 3,800 |
| Summit 000809, Hardhat 853, Alpenglow, Brightline, Fixwell FA-000415 + credit note, Ironwood, Keystone, Torque | Vendor `requires_po` = yes, **PO field blank** → hold |
| `fixwellfacilitys_CNFA000413.pdf`, `greatlakescarrie-inv-025.pdf` | **Credit notes** (negative). Don't route as normal payables |
| `sparkgridcrminc_FA002342.pdf`, `tesseraanalytics-inv-050.pdf` | **USD**, foreign vendor, no Canadian tax, preferred method = card |
| `laurentianlogist_FA002399.pdf`, `placemontroyalim-inv-053.pdf` | **French** layout, comma decimals |
| `scan_8049.png`, `scan_8749.png` | **Scans**: OCR noise in GST and transit numbers |
| EM-029 | 2 attachments → 2 bills (Orion 279 and 281). Orion also sent 287, so check the C023 monthly NTE of $25k |
| EM-056 / 057 / 058 / 059 | Statement / payment inquiry / missing attachment / marketing |

**History mess:**
- 3 self-approvals in approvals.csv
- U015 (terminated) is the requester on 10 invoices
- 12 rejections with reasons (useful for the approval-recommendation bonus)

## 5. Timeline (~40 working hours)

| When | What |
|---|---|
| H0–H2 | All 4: agree on stack, the §3 contract, folder ownership, CLAUDE.md. DB team pushes the schema skeleton early. |
| H2–H12 | A: classifier + extraction + eval script. B: validation + duplicates with tests against §4 (on mock DraftBills; no need to wait for A). |
| **H12** | **Integration checkpoint:** one email → draft bill → flags → approval route, end to end. |
| H12–H22 | A: coding suggestions, accuracy on the hard files. B: routing, delegation, `can_release`, split detection. Fix what the eval shows. |
| **H22–H24** | **Backend freeze.** Run the full batch, check every case in §4. |
| H24–H36 | All 4 on the frontend: one screen per role, flags that explain themselves. |
| H36–H40 | Demo script per role, Q&A rehearsal: each person explains someone else's module. |

## 6. Claude Code tips for 4 people

1. **One repo, one root CLAUDE.md** covering:
   - stack and run/test commands
   - folder ownership (`/extraction` = A, `/controls` = B, `/db`, `/api` = DB team)
   - "don't edit other people's folders; change the shared schema only via the DB team"
   - the fixed as-of date
   - a link to this file
2. **Separate folders per person + short-lived branches**, merging to main several times a day. `git worktree` lets you run two Claude sessions without conflicts.
3. **Plan mode first** (Shift+Tab): read the plan, push back, then let it code. Most bad AI code comes from skipping this.
4. **Tests before code for the controls engine.** Give Claude the §4 table and ask it to turn each row into a failing test first.
5. **Never let Claude invent the schema or the contract.** Paste the §3 contract into its context. Changes go through the DB team.
6. **Keep the LLM only where it's needed** (extraction, email classification). Keep every check, duplicate test, route and permission deterministic. It's more accurate, testable, and defensible.
7. **`/clear` between tasks** and keep sessions focused. Long contexts drift.
8. **Make Claude explain its own code before you merge** ("why this approach, what are the failure cases, what breaks at 100× volume"). That's your Q&A prep. Each person keeps a `DECISIONS.md` with one line per design choice.
9. **Don't overfit to the 56 samples.** The hidden batch is what counts. Ask Claude to generate variant test files (different layout, missing field, worse scan) to check robustness.
10. **Keep API keys in `.env`** and gitignore it from the start.
