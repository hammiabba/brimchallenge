# Judge Q&A prep

A study guide for the live Q&A. Every number here comes from a run or a test in this repo. The sources are
[`RUN_LOG.md`](RUN_LOG.md), [`PERSON_A_HANDOFF.md`](PERSON_A_HANDOFF.md), [`CONTROLS_HANDOFF.md`](CONTROLS_HANDOFF.md),
[`DETECTION_COVERAGE.md`](DETECTION_COVERAGE.md), [`DECISIONS.md`](DECISIONS.md) and the code. If a number changes,
fix it here too. Where something isn't built, this page says so. Say the same in the room: the brief scores a
simpler thing we can explain above a polished one we can't.

The test suites at the time of writing (main, 2026-11-22): backend **1,427 passed** (offline, no network), frontend
**291 passed** in 29 files, plus typecheck, lint and build.

---

## The whole app in 30 seconds

> Harborline gets about 50 supplier invoices a month by email. Our app reads the AP inbox (or an upload), sorts
> each email (invoice, credit note, statement, payment question, missing attachment, junk) and reads each attached
> PDF or scan, in English or French, into a draft bill. An LLM does only the reading. Everything after that is
> plain, tested code: it codes each line to a GL account and department from 10 months of history, then checks
> the bill against the vendor master, contracts, POs, tax rules, arithmetic, duplicates and bank-change history.
> Each problem becomes a flag that explains itself and blocks, warns or informs. The bill is routed to the right
> approvers by amount and policy, with delegation and self-approval handled. A finance manager or the controller
> releases a simulated EFT, but never for a bill they approved. Every action lands in a tamper-evident audit log.
> On the 56 unseen invoices: 56/56 read, 24 held, 10 sent for review, 22 clean, $110,405.03 on hold.

**The demo story** (set up by `backend/scripts/demo_scenario.py`, walk-through in
[`DEMO_SCENARIO.md`](DEMO_SCENARIO.md)):

1. **Cascadia (fraud).** Cascadia Cartage's bank account was changed on Oct 27 by email, with no callback. Its new
   bill AP-00435 is held (`BANK_CHANGE_UNVERIFIED`). Submit is disabled and says why, and the approved history bill
   AP-00426 can't be scheduled. Its scanned invoice is dated Oct 24 but already shows the new account, so it was
   likely edited or forged.
2. **Approvals.** Every approver has a bill in their queue. U012 is on leave, so their delegate U003 approves
   AP-00433 "acting for" U012, and the audit log records it as on behalf of U012.
3. **Separation of duties.** U003 approved AP-00436, so U003 can't release its payment PAY-00416 (P11). The
   controller U002 releases it instead.
4. **Audit.** The auditor U006 sees every step, with who acted, in which role and for whom, and exports it as CSV.
   The hash chain verifies.

---

## 1. Getting the bill in

### Plain English

- **Intake.** Two ways in. An AP clerk presses **Run** on the Inbox, which reads all unprocessed emails
  (`POST /intake/inbox/jobs`). An employee or a clerk can also upload a file (`POST /submissions`). Both return
  straight away (HTTP 202) and do the work in the background, and the page polls for progress. Each attachment
  becomes one draft bill.
- **Email triage** ("which kind of email is this?"). Rules first: English and French keywords scored on the
  subject, the body and the attachments. The LLM is only a tie-break for unclear emails. Every class comes with a
  next step, not just a label:
  - **invoice / credit note:** create drafts
  - **missing attachment:** a ready reply asking for the file
  - **payment inquiry:** answered from the payment history. The sender has to be identified first, so one
    vendor's invoice number never answers for another vendor. Bank details are never put in the reply.
  - **statement:** reconcile later
  - **not AP:** ignore
- **Extraction** ("read the document into fields"):
  1. **Check the file type from its first bytes**, not its name. An empty, encrypted, corrupt or Word file becomes a
     failed item with one plain sentence, never a crash. One bad file can't stop a batch.
  2. **Get text:** pdfplumber, then `pdftotext`, then tesseract OCR (English + French). Under 50 letters or digits
     counts as "no text", and the image goes to the vision model.
  3. **The LLM** (Claude Opus 5.5) fills a fixed schema with **values exactly as printed**, as strings. It doesn't
     convert or fix anything. Structured output means the reply always matches the schema.
  4. **Plain code normalizes:** money (`4 362,67 $`, `(1,042.76)`) goes straight to `Decimal` (exact decimal
     numbers, never floats). It also parses English and French dates and maps tax labels to tax codes
     (TPS→GST, TVQ→QST, TVH→HST). OCR digit fixes (`O→0`, `!→1`) are only applied to ID numbers with a known
     shape (GST, transit, account), and each fix is logged.
  5. **Vendor match:** GST number, then bank account, then sender domain, then fuzzy name ≥ 90. Names come last
     because the master has lookalikes.
  6. **Self-check:** qty × price = line, lines = subtotal, subtotal + tax = total. A failure lowers that field's
     confidence and adds a warning. The printed number is **never changed**: a wrong total is a finding for
     controls.
- **OCR vs vision.** OCR is cheap and local, but it misreads digits. When OCR text doesn't add up, the image is
  re-read once by the vision model and the read with fewer arithmetic problems wins. Born-digital PDFs are never
  re-read, because a total that's wrong on the paper stays wrong.
- **Low confidence.** Each field gets a confidence score: 0.95 for a clean text read and 0.75 for a clean scan. It
  goes down for each problem: an OCR fix (−0.15), an unclear date (−0.15 or −0.45), a failed check (−0.2 to −0.4) or
  a missing value (0). Below 0.7 on a key field, or a scan with extraction notes, raises `LOW_EXTRACTION_CONFIDENCE`
  (warn). The warning names the weak fields and says to check them against the image. When a clerk edits a field,
  its confidence becomes 1.0 and the checks run again.
- **Smart coding** (suggest a GL account and department per line). The first tier that has an answer wins:
  1. **A clerk's past correction** on a near-identical line from the same vendor. The reason names that bill.
  2. **The vendor's history:** past lines vote, weighted by how similar their description is.
  3. **The vendor's default GL account** from the master.
  4. **Similar lines from any vendor.**

  Every suggestion shows a reason and a confidence. The clerk accepts or changes it, and that feeds tier 1. The
  department comes from the requester when there is one.

### Key numbers and real examples

| What | Number | Source |
|---|---|---|
| Emails triaged | 59: 53 invoice, 2 credit note, 1 statement, 1 payment inquiry, 1 missing attachment, 1 not AP; 0 left untriaged | RUN_LOG Step 1, intake UI run |
| Files read | **56/56 ok**, 0 failed | RUN_LOG Step 1 |
| Field accuracy, 11 hand-labelled golden files | **100%** (135/135 fields) | `scripts/eval_extraction.py` |
| All 56 files vs expectations taken from the PDFs (not from our output) | **176/176** checks | `test_batch_expectations.py` |
| Unseen layouts we made ourselves (no table, right-aligned, French, totals first, USD) | 5/5 same core fields | `test_synthetic_layouts.py` |
| Cost of a full run | 218k tokens in / 26k out, **≈ $1.39 for 56 files ≈ $0.025 per file** | RUN_LOG Step 3 |
| Speed | ≈ **4.4 s per file**, sequential (246 s for 56). Reruns are free and near-instant (cache): 59 emails in 3.1 s | RUN_LOG |

- **French:** `laurentianlogist_FA002399.pdf`, "Sous-total 4 362,67 $ / TPS 218,13 $ / TVQ 435,18 $ / Total
  5 015,98 $", gives subtotal 4362.67, GST 218.13, QST 435.18, total 5015.98, QC. Its line is coded 5010 / D01 at
  0.97: "54 of 54 past lines from Laurentian Logistics Inc. coded this way".
- **Scan:** `scan_8749.png` (Prairie Natural Gas) has no text layer, so the vision model read it. GST and total
  were read exactly, and confidence is capped at 0.75. In a live test with a deliberately misread OCR total
  (4,779.28), the vision re-read returned the right 4,719.28.
- **Lookalike, read correctly:** `Invoice HA26-2766.pdf`. Its GST number picks V052 "Harlow and Stern LLP", the
  record the document really names. A name-only match could have silently picked the real V026 "Harlow & Stern".
- **Credit note:** Fixwell CN-FA-000413, total −1,614.21, `is_credit_note` true.
- **Payment inquiry EM-057:** "Invoice 1743 (AP-00049, 369.75 CAD) was paid on 2026-03-09 by EFT, reference
  BRIM-EFT-26388945", with a ready reply.
- **EM-029** has 2 attachments and gives 2 bills (Orion 279 and 281).
- **Same file twice** (same SHA-256 fingerprint): linked to the bill it already made, with an `already_received`
  warning. No second bill.

### Likely questions

1. **Why use an LLM at all, and not templates or regex?**
   The hidden batch has layouts we've never seen, and templates break on those. The LLM only maps text to fields,
   as printed. Parsing, maths, vendor matching and every decision are plain tested code. Regex is only used as a
   cross-check (and to build our test expectations).
2. **What stops the LLM from inventing or "fixing" a number?**
   It returns strings exactly as printed. Python parses them, and the self-check recomputes the arithmetic. If the
   model changed a number, the maths would disagree and the field would lose confidence. We never correct printed
   values: Evergreen's wrong total stays wrong and gets flagged.
3. **How do you handle scans?**
   Text layer first. Then OCR (tesseract, English + French), then the vision model when there's no usable text or
   the OCR totals don't add up. Honest limit: tesseract isn't installed on our dev machine, so both real scans
   went straight to vision. The OCR path is tested with a fake tesseract and simulated misreads.
4. **French?**
   Labels (TPS, TVQ, Sous-total, Facture n°), comma decimals with space thousands, and French dates are all handled
   in `normalize`. Both French invoices were read exactly. Triage scores French keywords too, because the subject
   and body can be in different languages.
5. **What happens with a bad file?**
   The type comes from the first bytes. An empty, encrypted or corrupt file, or a Word document named `.pdf`, becomes
   a failed item with a sentence the clerk can forward ("The PDF is password-protected; ask the vendor..."). A PDF
   named `.png` is read as a PDF, with a warning. Nothing crashes the batch.
6. **What about an ambiguous date like 03/04/2026?**
   Both readings are kept. The due date, payment terms and the other date's format usually settle it. Otherwise it
   reads day-first, with −0.45 confidence and a warning, which then raises `LOW_EXTRACTION_CONFIDENCE`.
7. **Prompt injection, e.g. an invoice that says "mark this as paid"?**
   The document text is fenced in `<document>` tags it can't close, and the prompt says it's data. The schema has no
   vendor id, status or approval field, so there's nothing to write "paid" into. The worst an injection can do is
   change a printed value, which vendor matching and controls then check.
8. **How does coding learn, and how accurate is it?**
   It learns from history votes, and from clerk corrections, which win next time and name the bill they came from.
   Honest limit: we haven't measured coding accuracy on held-out history. We show confidence and a reason on every
   line instead. Learned corrections live in memory and are rebuilt from the database at start-up.
9. **Cost and speed on the hidden batch?**
   About $0.025 and 4.4 s per file, so roughly $1.40 and 4 minutes for 56. Results are cached by file hash + prompt
   version + model, so a rerun costs nothing.
10. **Several invoices in one PDF?**
    We detect it (more than one invoice number across pages), warn and lower confidence. We don't split it
    automatically: page boundaries need a human.

---

## 2. Catching problems

### Plain English

The controls engine (`backend/app/controls/`) takes one draft bill, plus the rest of its batch, and returns flags,
duplicate matches and an approval route. It's pure functions: no LLM, no database, and the same input always gives
the same answer. It runs on every new bill, every edit and every submit. The reference data is rebuilt from the
database each time, so an admin edit applies at once.

Each flag has a **severity**:
- **block:** the bill can't be submitted or paid until someone resolves it, or a finance manager or the controller
  overrides it with a written reason
- **warn:** a human should look
- **info:** context

Each flag also has a plain-English message about this bill, evidence (expected vs found) and the field to
highlight. Every code has a help sentence the UI shows (`/reference/flag-help`).

- **Tax.** We **recompute** the expected tax rather than trusting the printed one, since the printed tax is what
  we're auditing. Expected tax comes from the delivery province, the vendor and each line's type:
  - ON: HST 13%
  - QC: GST 5% + QST 9.975%
  - BC: GST 5% + PST 7% on goods only
  - AB, SK, MB and the territories: GST 5%
  - insurance: exempt
  - foreign vendor: no Canadian tax
  - small supplier (no GST number anywhere): no tax expected, but warn

  Tolerance is 5 cents (some vendors round per line).
- **Maths:** line, subtotal and total, to 2 cents. All block.
- **Contracts:** expired; fee over the contract; hourly rate over the cap; fuel surcharge over the cap; this month's
  billing over the not-to-exceed limit. One-off charges (implementation, setup) are flagged separately, not as
  overcharges.
- **POs:** vendor requires a PO and there's none (block, P13); PO doesn't exist; PO closed or for another vendor; over
  the PO's remaining balance (warn, adds a finance step, P12).
- **Dates:** in the future, due before invoice date, older than 180 days. "Today" is the fixed as-of date
  2026-11-02, never the machine clock.
- **Currency:** USD converted at the rate for the invoice date (weekends fall back up to 6 days). Limits and
  routing use the CAD amount. No rate means the bill is held. We never assume a rate of 1, and never use the USD
  rate for another currency.
- **Duplicates**, layered, strongest first:
  1. same vendor and invoice number (block)
  2. same number after stripping prefixes, punctuation and leading zeros, so `FA-000583` = `583` (block)
  3. same vendor, amount within 1%, within 14 days, *and* invoice numbers ≥ 60% alike or the same service month
     (warn)
  4. different vendor record with the same bank account (warn)
  5. already paid on an employee card: similar merchant, same amount, within 45 days (block)
- **Splits:** 2+ bills from one vendor and department within 3 days, each under $10k, together over it. The group
  is routed at the combined amount.
- **Bank-change fraud:**
  - The vendor's latest bank change wasn't verified by callback (block).
  - Bank details on the invoice differ from the master (block).
  - The invoice is dated *before* a bank change but already shows the new account, so it was likely edited (block).
- **Lookalike vendors:** an unknown sender using a real vendor's name (≥ 85% similar after removing
  Ltd/Inc/&), or a bill on a duplicate vendor record (same normalized name or same bank account). It only flags the
  suspicious copy, never the real vendor.

### Key numbers and real examples

**Incoming batch** (56 files): **24 hold, 10 review, 22 can proceed, $110,405.03 CAD on hold.** Every trap in our
analysis of the batch raises its flag, and 18 invoices we checked by hand as clean raise no block flag
(`tests/api/test_flags_end_to_end.py`).

| Problem | File | Flag | What it says |
|---|---|---|---|
| Wrong tax | `northboundcourie_000639.pdf` | `TAX_WRONG_FOR_PROVINCE` (block) | Ships to AB, charged HST 13%, expected GST 5% |
| Missing QST | `beaumontrivieres_FA000557.pdf` | `TAX_MISSING` (block) | QC delivery, GST only |
| PST on services | `signalsparrowcre_000970.pdf` | `PST_ON_SERVICES` (warn) | BC PST is for goods only |
| Total wrong | `evergreenenergyu_000850.pdf` | `TOTAL_MISMATCH` (block) | 3,180 + 159 = 3,339, invoice says 3,439 |
| Line wrong | `northstarmediabu_NO261773.pdf` | `LINE_MATH_ERROR` (block) | 24 × 150 = 3,600, line says 3,800 |
| Fuel surcharge | `Invoice 000964.pdf` (Polar) | `OVER_FUEL_SURCHARGE_CAP` (warn) | 22% vs C018's 12% cap |
| Over contract fee | Aurora AU26-2207 | `OVER_CONTRACT_RATE` (warn) | $2,343.50 vs $2,150 in C008 |
| Over monthly limit | Redline FA-001687 | `OVER_CONTRACT_NTE` (warn) | October reaches $9,946.54, over C027's $9,000 |
| Expired contract | Torque 1771 | `CONTRACT_EXPIRED` (warn) | C025 ended 2026-06-30 |
| No PO | 10 bills (Summit, Hardhat, Alpenglow, Brightline, Fixwell + credit note, Ironwood, Keystone, Torque, Riverbend) | `PO_REQUIRED_MISSING` (block) | P13 |
| Future date | Summit 000809 | `DATE_ANOMALY` (warn) | Dated 2026-11-27 |
| Exact duplicates | Polar 000961, Harlow 001468, Cloudbarn INV-01561 | `DUPLICATE_EXACT` (block) | Match paid AP-00393, AP-00389, AP-00370 |
| Reformatted duplicates | Brightline "583", Voyageur "000903-A" | `DUPLICATE_EXACT` (block) | = FA-000583, = 000903 (AP-00277, paid) |
| Not a duplicate | Queen St rent $18,758 | none | Same amount every month is rent, not a duplicate |
| Possible split | Orion 279 + 281 + 287 | `POSSIBLE_SPLIT` (warn) | 3 in 3 days, each under $10k, $14,543.10 together |
| Bank change | Cascadia 1625 and `scan_8049.png` | `BANK_CHANGE_UNVERIFIED` (block) | Changed Oct 27 by email, no callback |
| Edited invoice | `scan_8049.png` (Cascadia 1624) | `BANK_DETAILS_MISMATCH` (block) | Dated Oct 24, shows account …9679, set up only on Oct 27 |
| Lookalike | `Invoice HA26-2766.pdf` | `VENDOR_LOOKALIKE` (block) | V052 "Harlow and Stern LLP" looks like V026 "Harlow & Stern LLP" |
| Unknown vendor | Blue Heron 4443, Zephyr 7590 | `VENDOR_NOT_FOUND` (block) | Not in the master |
| Pending vendor | Riverbend 1739 | `VENDOR_PENDING_REVIEW` (warn) + `GST_NUMBER_MISSING` (warn) | Adds a finance step (P05); "confirm small supplier" |
| USD | Sparkgrid, Tessera | `FOREIGN_CURRENCY` (info) | Converted at the invoice-date rate |
| Credit notes | Fixwell CN, Great Lakes 025 | `CREDIT_NOTE` (info) | Apply against an invoice; never paid |
| Scans | `scan_8749.png`, `scan_8049.png` | `LOW_EXTRACTION_CONFIDENCE` (warn) | Read from an image: check against it |

**History replay** (all 426 historical invoices, each judged only on what was known on its own date,
`scripts/replay_history.py`). 48 of the 426 have a warn or block flag. The findings:
- **4 bills paid twice or more, $16,813.66 paid out extra.** Redline AP-00136/155 $7,456.10; Alpenglow AP-00215/224
  plus a card charge, paid three times, $5,022.72; Northbound $2,639.61; Lakeshore $1,695.23.
- **1 more scheduled to be paid twice:** Summit AP-00394/407, $2,457.19 at risk.
- **5 more likely paid twice** through an AP payment plus an employee card charge, $6,723.10. These are matched by
  vendor name, amount and date, so call them "likely".
- **3 self-approvals** (U010 on AP-00092, AP-00178, AP-00235), and 2 over-PO bills that skipped the finance step.
- **Cascadia AP-00388** ($3,290.01) was paid 2 days after the unverified bank change.

### Likely questions

1. **Why no LLM in the controls?**
   These rules decide whether money moves. They have to give the same answer every time, explain themselves and be
   unit-tested. An LLM gives none of that.
2. **How do you avoid false positives on duplicates, e.g. rent?**
   A near match needs more than amount and date. It also needs alike invoice numbers or the same service month. For
   fixed-monthly vendors only the same service month counts, because consecutive numbers always look alike. So the
   Queen St rent isn't flagged. Credit notes never match invoices, and AP virtual-card payments aren't treated as
   card double-pays. Running it on the real data removed three false alarms (Orion 279/281, Lattice's one-off fee,
   Cloudbarn vs next month).
3. **Isn't stripping the "-A" suffix too aggressive?**
   It's deliberate. The original 000903 is already paid, and a near match is only a warning, so it wouldn't hold the
   bill. In history, Redline `1655-A` vs `FA-001655` was a real double payment, caught only because the suffix is
   stripped. Known risk: very short numbers (`A-1` vs `B-1`) from one vendor would collide. That didn't happen in
   the data.
4. **Why do tax and maths errors block, not just warn?**
   Paying a wrong invoice pays the wrong amount, or claims a tax credit the CRA won't allow. The bill waits for a
   corrected invoice, or for a finance manager or the controller to accept it with a reason, which goes into the
   audit log.
5. **How does the split check avoid flagging normal billing?**
   It skips duplicate pairs, bills that each have their own PO (each purchase was authorized), different
   departments, bills more than 3 days apart, and fixed-monthly vendors (V037's 11 rent bills around $8k). There's
   no minimum per piece, so four $2,500 bills are caught.
6. **What did you find that the brief didn't mention?**
   Cascadia's scan is dated 3 days before the bank change but already shows the new account, so it was likely
   forged. The bank statement also has 5 unexplained pre-authorized debits and 6 wire fees with no wire payment (see
   topic 4).
7. **What isn't caught?**
   - A misread on a scan that still adds up is only covered by the low-confidence warning and the clerk.
   - `DUPLICATE_LIKELY` never fires on the real data, so its thresholds are only tested on made-up bills.
   - Six flags have no real example and are only unit-tested.
   - Lookalike vendor records with no bills aren't reported on their own.
   - The due date isn't checked against the vendor's terms.
   - HST 15% provinces (NS, NB, NL, PE) aren't in `tax_codes.csv`, so they get no tax check.
   - A closed PO with money left still accepts bills.
   - A wrong contract id on a bill falls back to the vendor's first contract.

   All of these are listed in `DETECTION_COVERAGE.md` and `CONTROLS_HANDOFF.md`.
8. **How do you know it works on the hidden batch and not just the 56 samples?**
   No rule names a file or a vendor. Everything comes from master data, policies and the bill itself. A coverage
   test (`test_detection_coverage.py`) fails if any example loses its flag. And the batch is checked against itself
   as well as history, so two copies of the same unseen invoice are caught.
9. **Why Decimal?**
   0.1 + 0.2 isn't 0.3 in floating point. Tax checks to the cent need exact money. In the database money is integer
   cents. In the API it's a string ("742.30"), and JSON numbers are refused for money.
10. **What's the difference between resolve and override?**
    Resolve means it's fixed, e.g. a corrected invoice came in. Anyone in AP, finance or the controller can resolve.
    Override means accept it as is, with a reason. Overriding a *blocking* flag needs a finance manager or the
    controller. Both are audited.

---

## 3. Who can do what

### Plain English

- **Approval tiers** (on the CAD amount, or the combined amount of a split), from `approval_policies.csv`:
  - P01: up to $10k, department manager
  - P02: over $10k, + finance manager
  - P03: over $50k, + controller
  - P04: over $250k, + CFO

  The policies are data: the controller edits them on the **Policies** page, and routing follows on the next run
  (tested: `test_policy_threshold_edits_change_routing`).
- **Extra finance step:** new or pending-review vendor (P05), Legal vendor (P06) or over the PO balance (P12). It's
  added once, and merged if the tier already has a finance step.
- **Finding a person for each step:** start with the role holder and walk up the org chart until someone can
  legally sign:
  - **Requester = approver** (P07): go to their manager (`escalated_from`).
  - **On leave** (P08): their named delegate (`delegated_from`). An approver sets this on **Out of office**, and the
    controller can add absences.
  - **Terminated:** go to their manager.
  - **Already signs another step on this bill:** go to their manager (nobody signs twice).
  - **Not enough limit:** on the final step, the signer's approval limit must cover the amount.
  - **Nobody left:** the step is UNASSIGNED and shows on **Unassigned steps** for a finance manager or the
    controller to assign.
- **At approval time** (`can_approve`), the server re-checks the user's *current* record: active, not the
  requester, the step's assignee, a role that can sign that step, and the limit on the final step. A delegate's
  decision is stored with `on_behalf_of`.
- **Payments.**
  1. **The AP clerk schedules.** The bill must be approved, not a credit note, the vendor active with an account on
     file and no pending bank change, and the date not in the past. The payment records which version of the
     vendor's bank account it will pay.
  2. **A finance manager (up to $100k, P09) or the controller (any amount, P10) releases** a simulated EFT
     (reference `EFT-SIM-PAY-…`). Release fails if:
     - anyone releasing approved the bill (P11), or requested it
     - the person releasing prepared the payment
     - a block flag is still open
     - the bank details changed after scheduling
     - the bill is a credit note

     Release needs an `Idempotency-Key` header, so a double click can't pay twice.
  3. **Cancel:** AP, finance or the controller.
- **Roles are enforced on the server.**
  - Every route declares its roles (`require_role`).
  - Object rules live in `app/services`: department scope, P07, P11, limits. A bill outside your scope returns 404,
    so you can't even learn it exists.
  - A permission matrix test lists every endpoint × role, and fails if a new route has no row or answers without a
    session.
  - The UI only shows the buttons the server says are allowed (`allowed_actions`, computed by the same checks the
    write runs). A refusal shows the server's message and request id.
- **Early payment** (bonus): reads "2/10 net 30" (2% off if paid within 10 days, otherwise due in 30) and suggests
  the best pay date. That's the last day that still earns the discount, minus the payment method's lead days (EFT
  1, cheque 3, card 0). With no discount, it's the due date. It also flags scheduled payments that should move.

### Key numbers and real examples

- **Org:** 40 users, 8 departments, 6 roles, 13 policies (P01–P13).
- **The delegate trap:** U012 (Facilities manager) is on leave with delegate U003, who is *also* the finance
  manager. On a Facilities bill over $10k, step 1 goes to U003 as U012's delegate. Step 2 would be U003 again, so
  "nobody signs twice" sends it to U003's manager, the controller U002. If U003 is the *requester*, the delegated
  step escalates to U002 and the delegation is cleared, because U002 isn't acting for U012.
- **Demo:** AP-00433 waits for U003 "acting for" U012. AP-00434 ($11,800) waits at step 2 for the finance manager.
  PAY-00416 can't be released by U003 (they approved AP-00436), only by U002. All three payments were prepared by
  clerk U004, who can't release any of them.
- **HA26-2766:** step 1 dept_manager U007 (P01), step 2 finance_manager U003 (P06 Legal).
- **Terminated:** U015 can't approve and can't be set as a requester (422). Their 10 old invoices aren't flagged,
  because each history bill is judged as of its own date (all were before their 2026-09-15 termination).
- **Early pay:** none of the 20 approved or scheduled bills is from a discount vendor today, so today's saving is
  $0.00. AP-00399 is overdue: pay now. Once approved, Paper Trail 2217 saves **$10.84** if paid by 2026-11-04.
  History: **9 discounts taken ($296.18), 10 missed ($827.77)**, the biggest Ironwood AP-00180 ($201.93). Skipping
  2/10 net 30 costs about 37% a year.

### Likely questions

1. **How are roles enforced? Can't I just call the API?**
   Identity comes only from an HMAC-signed session cookie that holds the user id, not the role. The user row is
   re-read on every request, so a role change or termination applies on the next call. Every route has
   `require_role`. Object rules (your department, your own bill, approver ≠ releaser) are checked in the service,
   inside the write. Hiding buttons in the UI is just a convenience.
2. **What if someone approves their own invoice?**
   Routing skips them and goes to their manager (P07), and `can_approve` refuses them anyway. The history has 3
   self-approvals by U010, which the replay finds. Honest limit: invoices don't print a requester, so this can only
   be enforced once someone sets the requester on the bill, at routing time, not at intake.
3. **How is delegation recorded?**
   The route step carries `delegated_from`, and the decision is stored with `on_behalf_of`. The audit event shows
   both the actor and on whose behalf, and the bill screen says "Acting for …".
4. **Can a finance manager approve and then release?**
   No. P11 is checked in `can_release` on the server, against everyone who approved, including people a delegate
   approved for. The database also has CHECK constraints: releaser ≠ preparer, bank-change verifier ≠ requester,
   delegate ≠ actor.
5. **What if the approver's limit is too low?**
   Only the final signer's limit must cover the amount, since earlier steps are reviews. If nobody up the chain
   can sign, the step is UNASSIGNED and finance or the controller assigns someone. The assignee is checked again.
6. **Can an admin change the rules without a deploy?**
   Yes. The controller edits a policy's condition (e.g. the $10,000 threshold), and the next controls run reads
   policies from the table. Removing a threshold entirely is refused. Honest note: conditions are edited as text
   ("Invoice total up to $10,000 CAD") and parsed, not built with a form.
7. **What stops a double payment from a double click or retry?**
   The `Idempotency-Key` on release: the same key returns the stored result, and a reused key on another payment
   is refused. Only one live payment per bill can exist (`payment.already_exists`).
8. **What if the vendor changes bank details after a payment is scheduled?**
   Release is refused: the payment records which account version it was scheduled against.
9. **Payments are simulated, so what's real?**
   The state machine (scheduled → released or cancelled), the limits, separation of duties, idempotency and the
   audit trail. The EFT itself is a generated reference. No bank file (e.g. a CPA-005 EFT file) is produced.
10. **Early pay: why not just pay everything early?**
    Paying early only earns something when there's a discount. Otherwise it costs cash for nothing, so the advice
    is the due date. We take the discount as 2% of the pre-tax subtotal, never the tax, and count the 10 days from
    the invoice date. All 9 discounts taken in history match this to the cent. Honest limit: it suggests dates; it
    doesn't move the payment for you.

---

## 4. Trust and scale

### Plain English

- **Audit log.** Every write records exactly one audit event, in the same database transaction as the change:
  either both are saved or neither is. An event holds who acted, their role, on whose behalf, what changed
  (before/after) and the request id.
  - The table is **append-only**: database triggers abort any UPDATE or DELETE.
  - Events form a **hash chain**: each event stores the previous event's hash and its own hash, which is SHA-256
    over the previous hash plus the event. Change, insert or delete one in the middle and `verify_chain` finds the
    first bad one.
  - A unique index on `prev_hash` stops the chain from forking.
  - Deleting the *newest* events can't be seen from inside. For that, `chain_head()` gives an anchor (seq + hash)
    to keep outside the database with each export.
  - Bank account numbers in events become last 4 digits + an HMAC fingerprint keyed by `AUDIT_HMAC_KEY` (a secret
    key), so two events about one account still match but the number can't be recovered. Digit runs of 7+ in
    comments are masked.
  - The CSV export streams in 500-row batches. A cell that starts with `=` is prefixed, so a spreadsheet won't run
    it as a formula.
- **Vendor management.** The AP clerk onboards a vendor. It starts as `pending_review`, and a finance manager or
  the controller approves it. AP, finance and the controller can put a vendor on hold.
- **Bank changes** are a controlled action:
  - AP records the request, with the channel it came in by. The vendor's account is untouched.
  - A finance manager or the controller **verifies it after calling the vendor back on a number already on file**.
    The old account closes and the new one opens in the same transaction.
  - Nobody can verify their own request (checked in code and by a database CHECK).
  - Rejecting a change that was already applied without verification puts the vendor on hold, which is the
    Cascadia case.
  - Bank details are shown as last 4 digits to roles that don't need more.
- **Bank reconciliation** (bonus, controller and auditor). Every bank statement line is matched to its payment:
  - **EFTs** by the reference in the description, then by amount and payee within 5 days.
  - **Cheques** to the closest cheque issued before, within 60 days.
  - **Fees** are classified as fees.
  - **Everything else** is unexplained.

  Payments with no bank line are explained too (card, scheduled, in transit, outstanding or stale cheque).
- **Architecture:** FastAPI + SQLAlchemy on SQLite (25 tables, Alembic migrations), React + TypeScript + Mantine
  frontend with types generated from the OpenAPI spec. Four lanes with clear boundaries:
  - **A:** intake, extraction, coding. Returns a `DraftBill`.
  - **B:** controls. Pure functions, returns flags, route and permissions.
  - **DB/API:** storage, roles, audit and the state machines.
  - Routes are thin: a role check, then one service call.

### Key numbers and real examples

- **Reconciliation** (statement 2026-01-05 to 2026-11-02, 354 lines, $1,742,643.22 out):
  - **Matched:** 333 lines, $1,740,825.21 (all 313 EFTs and all 20 cheques).
  - **Bank fees:** 16, $385.00. **6 wire fees, but no payment in the data went by wire.**
  - **Unexplained:** 5 pre-authorized debits, $1,433.01 (BK-00064, -00088, -00192, -00193, -00207).
  - **Double payments:** 10 bills, $23,536.76 paid out extra. $2,457.19 is still scheduled to go out again (Summit
    PAY-00399: cancel it).
  - **Amounts that differ:** 4, including cheque 5018 cleared 5 cents over.
  - **Records not updated:** all 20 cheques cleared, but every one is still `outstanding` in `payments.csv`.
  - **Paid after the unverified bank change:** Cascadia AP-00388, $3,290.01.
- **Bank changes:** 9 in the history. BC-009 (Cascadia) is the one requested by email and never verified.
- **Audit check:** `verify_chain` returns `ChainReport(ok=True, count=…)`, and the demo-scenario test checks the
  chain.

### Likely questions

1. **How do you know the audit log wasn't edited?**
   Three layers. The database triggers refuse updates and deletes. The hash chain makes any edit, insertion or
   deletion in the middle detectable by `verify_chain`. And the event is written in the same transaction as the
   change, so there are no changes without an event. Honest limits: someone with raw file access could drop the
   triggers and rewrite the whole chain from that point. The chain hash is a plain SHA-256, not keyed, and the HMAC
   key only protects account numbers. Catching a full rewrite or a truncation needs the exported `chain_head`
   anchor kept outside the database. Also, the UI doesn't show the chain check: it's a one-line command.
2. **How do you link a payment back to its invoice, approvals and coding?**
   A payment belongs to a bill. The bill screen shows the invoice, line coding, flags, the approval route with
   each decision (including on whose behalf), payments and the bill's own audit history on one page. The audit
   API filters by entity.
3. **Why SQLite?**
   One file, no server to install for judges, real transactions and foreign keys. We write with `BEGIN IMMEDIATE`
   (take the write lock first) and run in WAL mode (readers don't wait for the writer). It's the first thing to
   change at scale (below). Honest limit: the baseline migration uses SQLite-only triggers, so a Postgres port needs
   a trigger function and one foreign key step rewritten.
4. **Why is the data modelled this way?**
   - Money is integer cents with a currency (SQLite would store decimals as floats).
   - Bank accounts are versioned rows, so each payment records exactly which account it paid.
   - `draft_json` keeps what was extracted, so you can compare "extracted vs corrected".
   - History and app bills share one table, so duplicate checks see both. There's deliberately no UNIQUE on
     (vendor, invoice number), because the history really has repeats and we need to see them.
   - Approval decisions store both the user's role and the step's role.
5. **What breaks at 100× volume** (≈ 5,000 invoices a month, or 5,600 files per inbox run)?
   - **Inbox job:** runs files one by one in a background task inside the API process: ~7 hours. Jobs live in
     memory, so a restart loses progress. *Fix:* a real queue with workers, 10–20 LLM calls at a time, or the
     Message Batches API at half price when same-day is fine.
   - **LLM cost:** ≈ $140 per run. *Fix:* the Batches API, prompt caching of the fixed system prompt, a lower effort
     setting for clean text PDFs.
   - **Controls:** rebuild reference data from the whole database on every run, and scan history for duplicates.
     Fine at 426 bills, slow at 45,000. *Fix:* indexed lookups by vendor and normalized invoice number, cached
     reference data invalidated on admin edits.
   - **SQLite:** has one writer at a time. *Fix:* Postgres.
   - **Files and the LLM cache** sit on local disk. *Fix:* object storage keyed by the same SHA-256.
   - **Learned codings** are per process. *Fix:* read them from the database per suggestion.
   - **Audit chain:** a single chain serializes every write (each event needs the previous hash). *Fix:*
     per-entity or per-day chains anchored together.
6. **What about security?**
   - **Sessions:** HMAC-signed `HttpOnly`, `SameSite=Lax` cookies, re-checked every request.
   - **CSRF** (another site making your browser send a request): an Origin allowlist on every write.
   - **Request size:** bodies are capped at 10 MB.
   - **Scope:** out-of-scope objects return 404.
   - **Money:** strings only.
   - **Files** are served by content hash with the type sniffed from the bytes, and only if an intake item
     references them.
   - **Secrets** live in `.env`, never in git.

   Honest limits:
   - **The sign-in is a demo picker with no passwords.** A real deployment needs SSO or passwords with MFA.
   - Sessions are stateless, so logout can't revoke a stolen cookie before it expires (8 h).
   - There's no rate limiting.
7. **Why can't AP just change the bank account?**
   Because that's the classic fraud: a fake "we changed banks" email. The request is recorded but not applied.
   Someone else has to verify it by calling a number already on file. Until then every bill to that vendor is held,
   and a payment scheduled before a change can't be released.
8. **Which bonus features are built?**
   - Bank reconciliation
   - Early-payment discounts
   - Spend by vendor, GL account or department (approvers see their own department)
   - Bank-change and lookalike-vendor alerts
   - A "Hold: …" recommendation on blocked bills, with the flag as the reason

   **Not built:** journal export to an accounting system, paying with a single-use virtual card, spend questions
   in plain language, and approving from a phone, Slack or email.
9. **How did you test without paying for the LLM every time?**
   The real model output for every file is recorded once (`tests/fixtures/raw`) and replayed through the real
   pipeline offline. Tests never call the network. Nine optional live tests (`RUN_LIVE_LLM=1`) hit the real model.
10. **You used AI to write code. Can you defend it?**
    Every design choice is one line with its reason in `DECISIONS.md` (66 rows). Each module has a handoff doc with
    its known gaps. And the numbers on this page come from runs we can repeat in front of you.
