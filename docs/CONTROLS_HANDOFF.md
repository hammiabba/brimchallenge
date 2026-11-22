# Controls engine: handoff

For teammates wiring the engine in, and for judge Q&A prep. Owner: Person B.
Keep this file accurate: any change in [`backend/app/controls/`](../backend/app/controls/) updates it
(see [`backend/app/controls/CLAUDE.md`](../backend/app/controls/CLAUDE.md)).

## What it does

It runs deterministic checks on one extracted bill. It answers three questions:

1. **Is anything wrong with this bill?** (validation, duplicates, split invoices)
2. **Who has to approve it?** (approval route from the policy table)
3. **Can it be paid, and by whom?** (release rules)

No LLM, no database, no web framework. The same bill always gives the same answer, and every flag
says why in plain English.

## The one function to call

```python
from app.controls import run_controls

result = run_controls(bill, batch)   # -> ControlsResult
```

| Argument | Type | Meaning |
| --- | --- | --- |
| `bill` | `DraftBill` | The bill to check (Person A's extraction output) |
| `batch` | iterable of `DraftBill`, optional | Other bills that arrived with it. May include `bill`. Used for duplicate and split checks within the batch. |
| `ref` | `RefData`, optional | Reference data. Defaults to the repo dataset, loaded once per process. |

### Input: what the engine reads from `DraftBill`

- **Required:** `vendor.vendor_id` (None if extraction found no match), `invoice_number`, `invoice_date`,
  `currency`, `subtotal`, `taxes` (one `TaxLine` per code), `total`, `lines` (with `line_no`,
  `line_type`, `quantity`, `unit_price`, `amount`), `ship_to_province`.
- **Strongly wanted:** `vendor.gst_number`, `vendor.bank`, `source.sender_address`, `po_number`,
  `due_date`, `is_credit_note`, `requester_user_id`, `department_id`.
- `source.file_hash` is used as the bill's id (the schema has no bill id).
- Money is `Decimal`, never float. Amounts are as printed, never corrected.

### Output: `ControlsResult`

| Field | Meaning |
| --- | --- |
| `flags` | `list[Flag]`: code, severity (`block` / `warn` / `info`), message, evidence, field to highlight |
| `duplicates` | `list[DuplicateMatch]`: matched invoice or card transaction, kind, score, reasons |
| `route` | `list[ApprovalStep]`: ordered approvers, with policy ids, reason, `delegated_from` / `escalated_from` |
| `can_auto_proceed` | `False` if any `block` flag is open |
| `recommendation` | `"Hold: <first block message>"` when blocked, else `None` |

Severity comes from `FLAG_CODES` in [`backend/app/shared/schemas.py`](../backend/app/shared/schemas.py); the engine defines no codes of its own.
`block` holds payment until someone resolves it, `warn` needs a human look, `info` is context.

### Example (real output)

Invoice HA26-2766 from "Harlow and Stern LLP" (V052), $6,452.30 CAD, Legal, requester U013:

```python
result = run_controls(bill)
result.flags
# [VENDOR_LOOKALIKE (block): This bill is on V052 Harlow and Stern LLP, which looks like existing vendor
#  V026 Harlow & Stern LLP (same name once 'Ltd/Inc/&' are ignored). Verify by phone before approving.]
result.route
# step 1  dept_manager     U007  [P01]  Total $6,452.30 ≤ $10,000
# step 2  finance_manager  U003  [P06]  Legal vendor needs finance approval
result.can_auto_proceed   # False
result.recommendation     # "Hold: This bill is on V052 Harlow and Stern LLP, ..."
```

### The other public functions

| Function | Use |
| --- | --- |
| `can_approve(user_id, step, bill, ref, *, route, amount_cad=None)` | Call on the server before recording an approval. Pass the full `route` (the final signer's limit is checked) and, for a split, the combined amount. Returns `PermissionDecision(allowed, reason)`. |
| `can_release(user_id, amount_cad, approver_ids, flags, approval_complete, ref, *, bill)` | Call before releasing a payment. Pass `result.flags` so duplicates hold the payment, and the `bill` (requester and credit-note checks). |
| `validate`, `find_duplicates`, `duplicate_flags`, `find_split`, `route` | The pieces `run_controls` calls, if you need one alone. |
| `load_refdata()` / `bill_from_history(...)` | Load reference data; turn a historical invoice row into a `DraftBill` (tests, replay). |
| `build_refdata(rows_by_file, as_of=None)` / `REFDATA_FILES` | **For the DB layer.** Builds `RefData` from rows instead of files: a dict keyed by the 12 CSV stems in `REFDATA_FILES` (`"vendors"`, `"users"`, …, `"approval_policies"`), each a list of `dict[str, str]` rows with the CSV's column names. `as_of` defaults to the settings date. `load_refdata()` is now just `build_refdata` over the CSVs, and a test checks both give identical `RefData`. |
| `incoming.run_batch(items)` / `incoming.render_report(...)` | Runs the controls on the extracted incoming batch as one batch (so in-batch duplicates and splits are caught), sorts problem bills first and renders the report. Printed by `backend/scripts/run_incoming.py`. |
| `history.replay(ref)` | Replays all historical invoices, each judged as of its own date, plus checks on `approvals.csv` and `payments.csv`. Printed by `backend/scripts/replay_history.py`. |
| `flag_help.help_for(code)` / `flag_help.FLAG_HELP` | **For the UI team.** A short title and one plain-English help sentence (what it means, what to do) for every code in `FLAG_CODES`, plus its severity. Show the title as the badge, the flag's own `message` for this bill's details, and the help as a tooltip or help panel. A test fails if a code has no help. |
| `refdata.history_taxes(ref, invoice, lines)` | Tax lines for a historical invoice, with the same tax codes the engine uses. Public now, so the DB seed uses it directly (`_history_taxes` still works as an alias). |
| `reconciliation.reconcile(bank_rows, payment_rows, ref)` | **Bank reconciliation.** Matches every bank statement line to its payment and explains the rest. Rows are CSV-shaped dicts (`bank_statement.csv`, `payments.csv`), so the CSV loader (`load_bank_and_payments()`) and the DB adapter (`services/reconciliation.py`) feed it the same way. Returns `Reconciliation` (lines, payments, double payments, `summary()`). See "Bank reconciliation" below. |

`controls.permissions` re-exports `can_approve` / `can_release` (the API guide refers to that module).

**For the UI team: flag help.** Every flag has a code, a severity and a `message` about this bill. For the general
explanation, call `help_for(flag.code)` from `app.controls.flag_help` (also exported from `app.controls`):

```python
help_for("BANK_CHANGE_UNVERIFIED")
# {"code": "BANK_CHANGE_UNVERIFIED", "severity": "block", "title": "Bank change not verified",
#  "help": "The vendor's bank account was changed recently without a callback check, so hold payment until
#           someone verifies it by phone."}
```

A code that isn't in the map (shouldn't happen) gets a generic title from the code name.

## Where the API calls the controls (for judge Q&A)

Every rule that decides whether money moves runs on the server, inside the write that depends on it. The UI only
shows what the server allows. File paths are under `backend/app/`.

| Controls function | Called from | When | What it's given |
|---|---|---|---|
| `run_controls(bill, batch, ref=)` | `services/controls_runner.py` → `rerun()`, the single path every service uses | A new bill from an upload or inbox run (`services/intake.py` `store_outcome`, started by `services/jobs.py` for the inbox), a header edit or line recoding (`services/bills.py` `update_header`, `code_line`) and submit (`services/bills.py` `submit`) | `ref` is rebuilt from the database on every call by `db/refdata_db.py` `refdata_from_db(exclude_bill_id=<this bill>)` (which uses `build_refdata`), never cached. So admin edits to users, policies and vendors apply at once, and the bill isn't matched against itself. The result is saved as a new versioned run (`db/bills.py` `save_controls_run`), and flag resolutions carry over when a flag is unchanged. |
| `can_approve(user, step, bill, ref, route=, amount_cad=)` | `services/approvals.py` `decision_check()`, used by `approve`, `reject` and the allowed-actions check in `services/actions.py` | Before an approval or rejection is recorded | The stored `route` (`db/bills.py` `route_for_bill`). A manually assigned approver replaces the step's user. `amount_cad` is the split's combined amount when controls saw a split (`controls_runner.routed_amount`). A delegate's decision is stored with `on_behalf_of`. |
| `can_release(user, amount_cad, approver_ids, flags, approval_complete, ref, bill=)` | `services/payments.py` `release_check()`, used by `release` and the allowed-actions check | Before a scheduled payment is released (simulated EFT) | `approver_ids` = everyone who approved, plus everyone a delegate approved for (`db/bills.py` `approver_ids_for_bill`). `flags` = only the flags still open in the latest stored run (`controls_runner.open_flags`), so an overridden flag no longer holds the payment. `approval_complete` = the bill's status is `approved` or `scheduled` (a bill only reaches `approved` through its final step). `bill` = the current `DraftBill`. |
| `flag_help.help_for(code)` | `api/routes_reference.py`: `GET /reference/flag-help`, every role | Loaded by the UI | Title, help and severity for every code in `FLAG_CODES`. |
| `reconciliation.reconcile(bank_rows, payment_rows, ref)` | `api/routes_reconciliation.py`: `GET /reconciliation/bank` (`?only_issues=true` for just what needs review), controller and auditor only (`AUDIT_READERS`), via `services/reconciliation.py` `bank_reconciliation()` | On request (read-only) | Statement lines and payments read from the database in CSV row shape, and `ref` from `refdata_from_db()`. The response models are at the end of `api/schemas_api.py` (`BankReconciliation` and the `Recon*` models). |

Checks the API adds around these: the payment's preparer can't release it, a bank change after scheduling blocks
release, release needs an `Idempotency-Key`, and one person can't sign two steps of the same bill. Every write
records one audit event.

**Inbox runs and the batch.** The inbox job stores each bill and runs controls on it with the rest of the run as
`batch`, so bills stored earlier in the run are in both the reference data and the batch. `run_controls` skips a
batch bill whose vendor, invoice number, date and total match a reference row, so it counts once. Without this, two
$4,000 bills looked like a $12,000 split, and a duplicate pair listed its match twice
(`tests/controls/test_batch_overlap.py`).

## Each check in plain English

### Vendor (`validate.check_vendor`)

| Catches | Flag | Why |
| --- | --- | --- |
| Vendor not in the master | `VENDOR_NOT_FOUND` (block) | Never pay someone who hasn't been onboarded. Routing also adds a finance step (P05). |
| Vendor not in the master, but `name_on_invoice` is ≥ 85% similar to a master vendor's name | `VENDOR_LOOKALIKE` (block) | An unknown sender using a real vendor's name is the impersonation case. Names are compared after removing Ltd/Inc/&/punctuation. |
| Vendor on hold / inactive | `VENDOR_NOT_ACTIVE` (block) | The master says don't pay them. |
| Vendor is `pending_review` | `VENDOR_PENDING_REVIEW` (warn) | Not blocked: routing adds the P05 finance manager step, and the flag says why it's there (Riverbend V054). |
| Canadian vendor with no GST/HST number in the master or on the invoice | `GST_NUMBER_MISSING` (warn), always | Two messages. **No tax charged** (`kind: no_tax`): "No GST/HST number on file. Confirm the vendor is a small supplier (under $30k/year) before paying." (Riverbend 1739.) **Tax charged** (`kind: tax_charged`): the tax can't be claimed back without a registration number, and charging tax with no number is a common fake-invoice signal. Either way, no tax flag: the tax check expects no tax from them. Foreign and unknown vendors are skipped. |
| Email sent from a domain other than the vendor's AP contact on file | `SENDER_DOMAIN_MISMATCH` (warn) | Someone else billing in the vendor's name. Domains are compared case-insensitively. Only for known vendors, and only when the bill came by email. |
| Bill sits on a lookalike vendor record (same name after removing Ltd/Inc/&, or same bank account as another vendor) | `VENDOR_LOOKALIKE` (block) | Classic impersonation fraud (V051/V053/V052). Only flags the *suspicious* copy (fewer past invoices, or not active), never the real vendor. |
| GST/HST number differs from master | `GST_NUMBER_MISMATCH` (warn) | Could be OCR or a fake invoice. OCR confusions (1/I/!, 0/O) are folded first, so OCR noise doesn't fire it. |
| Bank details on the invoice differ from master | `BANK_DETAILS_MISMATCH` (block) | Changed bank details on an invoice is the main payment-fraud pattern. Verify by phone on a known number. Only fields present on both the invoice and the master are compared (leading zeros ignored), so a missing institution number isn't a mismatch. |
| Invoice dated **before** a bank change already shows the account that change set up | `BANK_DETAILS_MISMATCH` (block, `kind: account_before_change`) | A genuine invoice prints the account in use on its date. Showing the new one means it was made or edited after the change (Cascadia scan 1624: dated Oct 24, shows …9679 from the Oct 27 change). The master already holds the new account, so the plain comparison above can't see it. Only a change dated strictly after the invoice counts. History bills dated before a later change carry no bank details (`bill_from_history` leaves them empty rather than copying today's account). |
| Vendor's latest bank change was never verified by callback | `BANK_CHANGE_UNVERIFIED` (block) | Cascadia (V004) changed its account by email on Oct 27 with no callback. Hold every payment to it. |

### Tax (`validate.check_tax`)

| Catches | Flag | Why |
| --- | --- | --- |
| A tax that should be charged isn't | `TAX_MISSING` (block) | e.g. QC bill with GST but no QST (AP-00098). |
| BC PST charged on services | `PST_ON_SERVICES` (warn) | BC PST applies to goods only. |
| Anything else wrong (wrong code, wrong amount) | `TAX_WRONG_FOR_PROVINCE` (block) | e.g. HST charged on an Alberta delivery (AP-00253). |

**Why tax is recomputed, not trusted:** the vendor's printed tax is exactly what we're checking, so it can't be
the reference. Expected tax comes from the place of supply (`ship_to_province`), the vendor's country and category,
and each line's type: ON = HST 13%; QC = GST 5% + QST 9.975%; BC = GST 5% + PST 7% on goods only;
AB/SK/MB/territories = GST 5%; insurance = exempt; foreign vendors = no Canadian tax; **small suppliers** (a
Canadian vendor in the master with no GST/HST number there or on the invoice) = no tax expected, so `TAX_MISSING`
never fires for them. They always get a `GST_NUMBER_MISSING` warning instead (a "confirm small supplier" message,
or the can't-claim-it-back message if they charged GST/HST). PST/QST they charge is still checked. A GST number printed on the invoice counts as registered. Tolerance is 5 cents
because some vendors round tax per line. **Unknown vendors are checked too:** with no master record, a CAD bill is
treated as a taxable Canadian supplier and a foreign-currency bill as a foreign vendor.

### Arithmetic (`validate.check_arithmetic`)

| Catches | Flag |
| --- | --- |
| quantity × unit price ≠ line amount | `LINE_MATH_ERROR` (block) |
| lines don't add up to the subtotal | `SUBTOTAL_MISMATCH` (block) |
| subtotal + taxes ≠ total | `TOTAL_MISMATCH` (block) |

Tax and math flags block: a bill with wrong tax or wrong totals can't be submitted or paid until someone marks the
flag resolved (e.g. a corrected invoice came in) or a finance manager or the controller overrides it with a reason.

Tolerance is 2 cents. Extraction never "fixes" printed numbers, so these catch both vendor errors and misreads.

### Contract (`validate.check_contract`)

| Catches | Flag | Why |
| --- | --- | --- |
| Invoice dated after the contract ended | `CONTRACT_EXPIRED` (warn) | Work may not be authorized (Torque Industrial V044). |
| Fixed-monthly bill whose **fee line(s)** exceed the contract fee | `OVER_CONTRACT_RATE` (warn, `kind: fee`) | Only the fee line is compared, not the whole subtotal. Billing *under* the fee isn't flagged (no code). |
| Usage / overage lines on a fixed-monthly bill | `OVER_CONTRACT_RATE` (warn, `kind: overage`) | Billed on top of the fee by design (Redstone V021: $4,800 committed base + data-transfer overage), so it's a "confirm the usage" warning, not an overcharge. |
| One-off lines on a fixed-monthly bill (implementation, migration, setup, installation, onboarding, training, one-time; French mise en place / formation) | `OVER_CONTRACT_RATE` (warn, `kind: one_off`) | Not part of the monthly fee, so not compared to it (Lattice 557: $8,200 implementation vs $1,320/month). The warning says "One-off charge … not part of the fee … confirm it was ordered". Uses the existing code because there is no separate one for it. |
| Hourly line above the contract's hourly cap | `OVER_CONTRACT_RATE` (warn) | A line is hourly only if its description says hour / hr / hrs / heure. Quantity alone (5 pallets) isn't hours. |
| Fuel surcharge above the contract's cap | `OVER_FUEL_SURCHARGE_CAP` (warn) | Checks both the % printed on the line and the actual % of freight, and uses the worse one (Invoice 000964: 22% vs a 12% cap). |
| This month's billing would pass the contract's monthly not-to-exceed | `OVER_CONTRACT_NTE` (warn) | Sums this vendor's other bills in the same month from history (Orion C023). |

### Purchase order (`validate.check_po`)

| Catches | Flag | Why |
| --- | --- | --- |
| Vendor requires a PO and there isn't one | `PO_REQUIRED_MISSING` (block) | P13: missing PO means hold. |
| The PO number on the bill doesn't exist | `PO_NOT_FOUND` (block) | Raised for any vendor, not only PO-required ones (they also get policy P13 in the evidence). |
| PO belongs to another vendor, or is closed and fully used | `PO_CLOSED_OR_WRONG_VENDOR` (block) | |
| Bill is above what's left on the PO | `PO_OVER_BALANCE` (warn) | P12: routing adds a finance manager step. |

### Requester (`validate.check_requester`)

| Catches | Flag | Why |
| --- | --- | --- |
| The requester is terminated | `REQUESTER_TERMINATED` (warn) | Someone who has left can't confirm the purchase. In the history replay, each bill is judged as of its own date, so U015's 10 invoices (all before their 2026-09-15 termination) aren't flagged. |

### FX, dates, credit notes

| Catches | Flag | Why |
| --- | --- | --- |
| Non-CAD bill | `FOREIGN_CURRENCY` (info) | Shows the rate used, where it came from and the CAD amount. Currency codes are case-insensitive. Rate order: the rate given on the bill (`fx_rate_to_cad`), then the USD/CAD table (USD only; weekends fall back up to 6 days). A non-USD currency is **never** converted at the USD rate. |
| No reliable FX rate (unsupported currency, or no USD rate for the date and none on the bill) | `CURRENCY_UNSUPPORTED` (block), message starts "FX rate missing" | The CAD amount is left unknown (never 1, never guessed), so the bill is held. Routing uses the face amount and says so on every step. Replaces the `FOREIGN_CURRENCY` info flag for this case. |
| Invoice dated in the future, due before invoice date, or over 180 days old | `DATE_ANOMALY` (warn) | "Today" is the fixed as-of date (2026-11-02) from settings, never the machine clock, so results don't change with the demo date. |
| Credit note | `CREDIT_NOTE` (info) | Apply it to an open invoice instead of paying it. |
| A key field (vendor, invoice number, invoice date, subtotal, taxes, total, bank details) read with confidence under 0.7, or a scanned bill (`source.was_ocr`) with extraction notes | `LOW_EXTRACTION_CONFIDENCE` (warn), `validate.check_extraction_confidence` | Names the weak fields, weakest first, and quotes the scan notes. The threshold is 0.7: extraction scores a clean text read 0.95 and a clean scan 0.75, and lowers a field for an OCR correction (-0.15), a resolved or ambiguous date (-0.15 / -0.45), a failed check (-0.2 to -0.4), a weak vendor match (the match score) or a missing value (0). So any one deduction on a scanned field is caught, and a clean read isn't. On a text-layer bill, a weak field another flag already reports (the total on `TOTAL_MISMATCH`, the subtotal on `SUBTOTAL_MISMATCH`, the vendor on `VENDOR_NOT_FOUND`) isn't repeated: the text is exact, so that's the vendor's mistake, not a misread. Bills with no scores (history, hand-entered) are never flagged. Extraction has no bank score yet, so bank details only count once it adds one. A clerk's edit sets that field to 1.0, but scan notes stay, so a scanned bill keeps the warning until someone resolves it. |

### Duplicates (`duplicates.find_duplicates`)

Layered, strongest first. Checked against history (minus rejected invoices) *and* the current batch.

| Kind | Rule | Flag |
| --- | --- | --- |
| `exact` | Same vendor, same invoice number | `DUPLICATE_EXACT` (block) |
| `normalized` | Same vendor, same number after dropping prefixes, punctuation and leading zeros (`FA-000583` = `583`) | `DUPLICATE_EXACT` (block) |
| `near` | Same vendor, amount within 1%, within 14 days, **and** invoice numbers ≥ 60% alike or both bills naming the same service month ("October", "octobre", 2026-10-…). For fixed-monthly vendors only the same service month counts. | `DUPLICATE_LIKELY` (warn) |
| `cross_vendor` | Different vendor record with the same bank account, amount within 1%, within 30 days | `DUPLICATE_LIKELY` (warn) |
| `card_paid` | Employee card charge with a similar merchant name, same amount, within 45 days | `ALREADY_PAID_BY_CARD` (block) |

- **Unknown vendors:** two bills from vendors not in the master count as the same vendor when the name on the
  invoice is the same (after normalizing), so the same unknown invoice sent twice in one batch is caught.
- **Why rent isn't a duplicate:** fixed-monthly contract vendors (rent, SaaS) bill the same amount every month.
  For them a "near" match also needs the invoice numbers to look alike (≥ 60% similar); otherwise every rent
  bill would match last month's.
  Update: the ≥ 60% number rule now applies to every vendor (it's part of `near` above). Two bills that name the
  same month still match with unrelated numbers, so a re-issued October rent bill is still caught.
  Update (`b/controls-polish`): for fixed-monthly vendors, number similarity no longer counts at all, because
  consecutive monthly numbers always look alike (Cloudbarn INV-01561 / INV-01567: 75%). Only the same service month
  makes a near match for them. A re-sent copy is still caught by the exact and normalized checks.
- **A bill in both the reference data and the batch counts once** (same vendor, invoice number, date and total):
  the API's inbox job stores bills one at a time, so earlier bills are in both. See "Where the API calls the
  controls".
- **A credit note is never matched against an invoice.** It shares the invoice's number and amount by design.
- **AP virtual-card payments are skipped** in the card check. They pay other invoices, which the invoice-to-invoice
  checks already compare.
- Each match carries a score and reasons, so the UI can show why.

### Split invoices (`duplicates.find_split`)

| Catches | Flag | Why |
| --- | --- | --- |
| 2+ bills from one vendor and department within 3 days, each under the $10k limit, together over it | `POSSIBLE_SPLIT` (warn) | Splitting a bill to stay under an approval limit. The group is then **routed at the combined amount**. Torque Industrial (V044): 3 bills in 2 days, ~$14k. |

There's no minimum per bill, so small pieces count too (four $2,500 bills are caught). Not counted as splits:
- **Duplicate pairs** (same invoice number, exact or normalized, e.g. Redline FA-001655 / 1655-A): that's a
  duplicate, reported by the duplicate check.
- **Bills that each have their own PO** (e.g. Deskhive's three furniture orders): each purchase was authorized.
- **Different departments**, and bills more than 3 days apart (Redline's monthly fuel bills).
- **Fixed-monthly vendors** (V037's 11 rent bills around $8k are just rent).

### Approval routing (`approvals.route`)

Policies are data: thresholds and role chains are parsed from `approval_policies.csv`. Change `$10,000` there and
routing follows.

1. **Amount tier** (CAD, or the combined amount for a split): ≤ $10k dept manager (P01); > $10k + finance
   manager (P02); > $50k + controller (P03); > $250k + CFO (P04).
2. **Extra finance step**: new or pending-review vendor (P05), Legal vendor (P06), over PO balance (P12).
   Added once, merged into the finance step if the tier already has one.
3. **Find a person for each step**, starting with the role holder and walking up the org chart until someone can
   legally sign:
   - **Self-approval (P07):** if the holder is the requester, go to their manager. Recorded in `escalated_from`.
   - **Leave (P08):** if the holder is on leave, go to their named delegate. Recorded in `delegated_from`. If no
     delegate, go to their manager.
   - **Terminated:** go to their manager (U015 can't approve).
   - **One person, one step:** if they already sign another step on this bill, go to their manager.
   - **Limit:** the final signer's `approval_limit_cad` must cover the amount; earlier steps are reviews.
   - Nobody left: the step is `UNASSIGNED`, with a note for AP to assign manually.
4. **The delegate case:** U012 (Facilities manager) is on leave with delegate U003, who is also the finance
   manager. On a Facilities bill over $10k, step 1 is U003 (as U012's delegate) and step 2 would be U003 again.
   The "one person, one step" rule sends step 2 to U003's manager, the controller (U002): chain U003 → U002.
   If U003 is the *requester* of a Facilities bill, the delegated step escalates to U002 and `delegated_from` is
   cleared, because U002 isn't acting for U012. All three cases are tested in
   [`backend/tests/controls/test_approvals.py`](../backend/tests/controls/test_approvals.py).

### Permissions (`approvals.can_approve`, `approvals.can_release`)

- **Approve:** user must be active, not the requester (P07), and the step's assignee (a delegate is the assignee
  of a delegated step). The user's **current** record is re-checked, not just the route: their role must be able
  to sign that kind of step (any approver for a department step; finance manager or controller for a finance step;
  controller for controller/CFO steps), and on the **final** step their approval limit must cover the amount.
- **Release:** fully approved; not a credit note (apply it, don't pay it); no open `block` flag; the user didn't
  request this bill and didn't approve it (P11, separation of duties); finance manager up to $100k (P09),
  controller above (P10). Other roles can't release.

## Known gaps

- **`can_release` trusts its `approver_ids`.** The backend must pass who *actually* acted, including delegates.
- **`RefData` is loaded once per process** (`default_refdata()` is cached). Data changes need a restart, or pass
  a fresh `ref`. When the DB lands, replace `refdata.load_refdata()`; nothing else needs to change.
  Update: the DB layer can now call `build_refdata(rows_by_file)` with rows read from the database (same keys and
  column names as the CSVs), so the CSV and DB paths share one builder. Pass the result as `ref`.
- **Signatures differ from the old stubs:** functions take a `RefData`, not a `ReferenceRepository`.
- **Not yet run on the real incoming batch.** `backend/scripts/run_incoming.py` is ready and tested on hand-built
  bills, but extraction currently fails on every file: the API rejects `RawInvoice` in
  `backend/app/extraction/llm_parser.py` ("19 parameters with union types", limit 16). Person A is fixing it.
  Email triage works: 55 emails with 56 attachments, plus a statement, a payment inquiry, a missing attachment
  and a marketing email.
  **Update 2026-11-21:** Person A's fix is on main and the batch has now been run. See "Incoming batch results"
  below.
- **Invoices don't print a department**, so routing would have no department manager. `run_incoming.py` uses the
  department the line coding suggestions give the most money to, and the report marks it "suggested by coding".
- **Very short invoice numbers can collide.** The normalized-number duplicate check keeps digits only, so `A-1`
  and `B-1` from the same vendor match as `DUPLICATE_EXACT`. Real numbers are longer; watch for it in the batch.
  Update: it didn't happen in the real batch.
- **`field_confidence`, `extraction_warnings` and `was_ocr` are ignored.** `LOW_EXTRACTION_CONFIDENCE` exists
  in `FLAG_CODES` but is never raised.
  Update (`b/low-confidence`): now raised by `validate.check_extraction_confidence`, see "FX, dates, credit notes".
- **No received date in the schema**, so "stale" and "future" use the as-of date.

## Incoming batch results (2026-11-21)

`cd backend && python scripts/run_incoming.py`, after Person A's extraction fix. All 56 files were read: 0
unreadable, **19 hold**, **14 review**, **23 can proceed**, $89,963.04 CAD on hold (before tax and math flags
became block; now 23 / 10 / 23 and $108,303.23, see the last rerun below). The 4 emails with no bill
(EM-056 to EM-059) were listed correctly. The two scans and the two French invoices were checked by hand against
the files. Numbers, dates and totals were all read correctly, so none of the flags below come from extraction
mistakes.

### Against HACKATHON_PLAN §4, row by row

| §4 row | Result |
|---|---|
| Exact duplicates: Polar 000961, Cloudbarn INV-01561, Harlow 001468 | ✅ `DUPLICATE_EXACT` on all three (AP-00393, AP-00370, AP-00389). Cloudbarn's original was paid by AP virtual card (CT-00556). `ALREADY_PAID_BY_CARD` is deliberately not raised for AP virtual-card payments, and the exact match already holds the bill. |
| Brightline "583" | ✅ `DUPLICATE_EXACT` (normalized: 583 == FA-000583), plus `PO_REQUIRED_MISSING` |
| Voyageur "000903-A" | ✅ Caught, and stricter than §4: `DUPLICATE_EXACT` (normalized, score 0.95) rather than a near match. AP-00277 is already paid, so blocking is right. |
| Queen St rent $18,758 | ✅ Not flagged as a duplicate. Routed P02: department manager (U003, delegate for U012), then finance step (U002) |
| Blue Heron, Zephyr | ✅ `VENDOR_NOT_FOUND` |
| Riverbend 1739 | ✅ `PO_REQUIRED_MISSING` (block), `VENDOR_PENDING_REVIEW` (with the P05 finance step) and `GST_NUMBER_MISSING` (warn: "Confirm the vendor is a small supplier (under $30k/year) before paying"). No tax flag: with no GST number, it's treated as a small supplier that shouldn't charge tax, and it charged none. (Earlier runs also showed `TAX_MISSING`; see the tax-and-math rerun.) |
| Harlow **and** Stern (EM-026) | ✅ `VENDOR_LOOKALIKE` of V026, plus the P06 finance step |
| V053 Great Lakes Incorporated | n/a: both Great Lakes files matched V002 |
| Cascadia 1625 and `scan_8049.png` | ✅ `BANK_CHANGE_UNVERIFIED` on both |
| Polar 000964 fuel 22% | ✅ `OVER_FUEL_SURCHARGE_CAP` |
| Northbound AB charged HST | ✅ `TAX_WRONG_FOR_PROVINCE` |
| Beaumont QC, no QST | ✅ `TAX_MISSING` |
| Signal & Sparrow PST on services | ✅ `PST_ON_SERVICES` |
| Ironwood, no tax | ✅ `TAX_MISSING`, plus `PO_REQUIRED_MISSING` |
| Evergreen total | ✅ `TOTAL_MISMATCH` (3,339 vs 3,439) |
| Northstar line math | ✅ `LINE_MATH_ERROR` (24 × 150) |
| Requires a PO, field blank (Summit, Hardhat, Alpenglow, Brightline, Fixwell + credit note, Ironwood, Keystone, Torque) | ✅ `PO_REQUIRED_MISSING` on all 9, and on Riverbend (10 total) |
| Credit notes: Fixwell, Great Lakes | ✅ `CREDIT_NOTE`, not routed for payment. The Fixwell credit note is also held for its missing PO, as §4 expects. |
| USD: Sparkgrid, Tessera | ✅ Converted at the rate printed on the bill. No false Canadian-tax flags. "Preferred method = card" isn't shown; that belongs to payment, not controls. |
| French: Laurentian, Place Mont-Royal | ✅ Comma decimals read correctly (5,015.98 and 6,990.48). No false flags. |
| Scans `scan_8049.png`, `scan_8749.png` | ✅ Read by the vision model and checked against the images. No false GST or bank flags. |
| EM-029 Orion 279 + 281 (+ 287) | ✅ Two bills from one email. C023's $25k NTE isn't breached (October total $14,543.10), so no NTE flag. ❌ False `DUPLICATE_LIKELY` between 279 and 281 (see below). Fixed on `b/controls-false-alarms`. |
| EM-056 to EM-059 | ✅ Listed as statement, payment inquiry, missing attachment and marketing |

### False alarms
1. ✅ **Fixed.** **Orion 279 ↔ 281, `DUPLICATE_LIKELY` (warn).** Different invoice numbers, both attached to the same email,
   with amounts 0.5% apart. The near-match rule (same vendor, amount within 1%, within 14 days) uses
   invoice-number similarity only for the score, not as a condition. Possible fix: require some number
   similarity, or skip two bills from the same email. Not changed yet, because it also moves the history replay
   numbers.
   Fix (`b/controls-false-alarms`): a near match now also needs invoice numbers ≥ 60% alike or the same service
   month in the lines. 279 vs 281 are 33% alike, and their lines name phases, not months, so they no longer match.
   The history replay didn't change, because no historical bill had a near match.
2. ✅ **Fixed.** **Lattice 557, `OVER_CONTRACT_RATE` (warn).** The $8,200 is a one-off "Implementation and data migration",
   not the monthly fee. The check compares any bill from a fixed-monthly vendor to the $1,320 fee. The bill still
   deserves a question (it isn't covered by the contract), but the message is wrong.
   Fix (`b/controls-false-alarms`): one-off lines are left out of the fee comparison and get their own warning
   (`kind: one_off`): "One-off charge of $8,200.00 (Implementation and data migration) is not part of the
   $1,320.00/month fee in C005. Not an overcharge by itself: confirm it was ordered."
3. ✅ **Fixed.** **Cloudbarn INV-01561, extra `DUPLICATE_LIKELY` vs AP-00411 (INV-01567, the October subscription).** On a
   fixed-monthly vendor, consecutive invoice numbers always look ≥ 60% alike, so the "recurring" guard doesn't
   help. This is harmless here, since the exact duplicate already blocks the bill. On a clean monthly bill it
   would be noise.
   Fix (`b/controls-polish`): for fixed-monthly vendors a near match needs the same service month. INV-01561 now
   gets only `DUPLICATE_EXACT` vs AP-00370 (September's, paid).
4. **Debatable: `POSSIBLE_SPLIT` (warn) on Cascadia (1619 + 1624 + 1625, $15,308.84) and Orion (279 + 281 + 287,
   $14,543.10).** Carriers and consultants often bill per load or per engagement, but three bills in 3 days
   above $10k together is exactly the pattern P01 is about. Kept as a warning.

### Misses
1. ✅ **Now checked.** **Not checked, worth knowing:** Cascadia 1624 (`scan_8049.png`) is dated 2026-10-24 but already prints the new
   account (…9679), which was only changed on 2026-10-27 by an unverified email request. The bill is held anyway.
   Update (`b/controls-polish`): flagged on its own now, see "Cascadia: likely edited or forged invoice".

### Cascadia: likely edited or forged invoice

Cascadia's scanned invoice is dated 3 days before the Oct 27 bank change but already shows the new bank account. A
real invoice from before the change would show the old account, so the invoice was likely edited or forged. The
engine holds the bill, but it doesn't yet flag this specific date mismatch on its own.
Update: it does now. `BANK_DETAILS_MISMATCH` (`kind: account_before_change`) fires on the scan: "Invoice dated
2026-10-24 shows bank account …9679, but that account was only set up on 2026-10-27 (BC-009, via email_request)."

### Rerun after the false-alarm fixes (`b/controls-false-alarms`)

Levels are unchanged: 19 hold, 14 review, 23 can proceed, $89,963.04 CAD on hold. Orion 279 and 281 stay under
review because of `POSSIBLE_SPLIT`, and Lattice 557 because of the one-off warning. `DUPLICATE_LIKELY` drops from 3
bills to 1 (only Cloudbarn INV-01561, false alarm 3), and "Duplicates inside this batch" no longer appears. The
history replay output is identical.

### Rerun after the new flag codes (`b/flag-codes`)

Riverbend 1739 now also gets `VENDOR_PENDING_REVIEW` and `GST_NUMBER_MISSING`. Nothing else changed: 19 hold,
14 review, 23 can proceed, $89,963.04 CAD on hold (Riverbend was already held for its missing PO). No bill came from
an unexpected sender domain, none has an unknown PO number or a missing FX rate, and no requester is terminated.
The history replay output is identical.

### Rerun after the polish (`b/controls-polish`)

**20 hold, 13 review, 23 can proceed, $92,064.84 CAD on hold** (was 19 / 14 / 23 and $89,963.04).
- The new bank-account check fires on 2 bills. **Cascadia `scan_8049.png`** was already held, and the new flag now
  leads its hold reason. **Lumen FA-001761** moves from review to hold ($2,101.80): dated 2026-04-06, it prints
  account …0921, which BC-006 (verified by callback) only set up on 2026-04-26. That can be harmless (a vendor
  re-sending an old unpaid invoice may regenerate it with current bank details), but it's worth a call, and the
  bill is also 210 days old.
- Cloudbarn INV-01561 lost only its near match to next month's bill. `DUPLICATE_LIKELY` is now 0.
  `DUPLICATE_EXACT` is still on the same 5 bills.
- History replay: identical.
- Ruff now passes on `backend/app/controls/` (long lines, `l` names and a lambda fixed, no behavior change).

These numbers are with tax and math flags as `warn`. If `b/tax-math-block` (PR #23) is merged as well, the 4 bills
it moves to hold come on top.

### Rerun with tax and math flags as block (`b/tax-math-block`)

**24 hold, 9 review, 23 can proceed, $110,405.03 CAD on hold** (on top of the polish rerun's 20 / 13 / 23 and
$92,064.84). Four bills moved from review to hold: Evergreen 000850 (`TOTAL_MISMATCH`, $3,439.00), Beaumont
FA-000557 (`TAX_MISSING`, $8,101.67), Northbound 000639 (`TAX_WRONG_FOR_PROVINCE`, $2,505.52) and Northstar
NO26-1773 (`LINE_MATH_ERROR`, $4,294.00). Ironwood has `TAX_MISSING` too but was already held for its missing PO.

Small-supplier rule (from review): Riverbend 1739 has no GST number anywhere, so it's treated as a small supplier
that shouldn't charge tax. It charged none, so it no longer gets `TAX_MISSING`, which would now block a legitimate
invoice. It keeps `GST_NUMBER_MISSING` as a warning ("Confirm the vendor is a small supplier (under $30k/year)
before paying") and stays held for its missing PO, with `VENDOR_PENDING_REVIEW`. No other incoming bill changed. History replay: same counts; the 3 tax flags show as block instead of warn.

### Caught beyond §4 (checked against the PDFs: real, not extraction errors)
- Summit 000809 is printed with date 2026-11-27, in the future → `DATE_ANOMALY`.
- Lumen FA-001761 is printed with date 2026-04-06, 210 days old → `DATE_ANOMALY`.
- Torque 1771 is under contract C025, which expired 2026-06-30 → `CONTRACT_EXPIRED`.
- Aurora AU26-2207 ($2,343.50 vs $2,150 fee, +9%) and Pinecone PI26-2809 ($826.80 vs $780, +6%) →
  `OVER_CONTRACT_RATE`.
- Redline FA-001687: October pre-tax billing reaches $9,946.54 with AP-00424, over the C027 $9,000 limit →
  `OVER_CONTRACT_NTE`.

### Detection coverage map (`b/coverage-map`)

[`docs/DETECTION_COVERAGE.md`](DETECTION_COVERAGE.md) maps each "real-world mess" item in the brief to the flags
that catch it, with one example bill (from the batch, or the history when the batch has none). It also lists what
nothing catches. `backend/tests/controls/test_detection_coverage.py` runs the batch offline, replaying the recorded
model output in `backend/tests/fixtures/raw/`. It fails if any example stops getting its flag.
Rerun on main after PR #23 and #26: still 24 hold / 9 review / 23 can proceed, $110,405.03 on hold. Gaps found:
low-quality scans have no flag (`LOW_EXTRACTION_CONFIDENCE` is never raised, see Known gaps). Self-approval
can't be seen at intake because invoices print no requester (it's enforced at approval). Seven flags, and
`DATE_ANOMALY`'s "due before invoice" case, have no real example and are only tested on made-up bills.

### Rerun with `LOW_EXTRACTION_CONFIDENCE` (`b/low-confidence`)

**24 hold, 10 review, 22 can proceed, $110,405.03 CAD on hold.** Only the two scans changed. Each was read by the
vision model (no tesseract here) and carries that note, so both get the warning. Prairie Natural Gas `scan_8749.png`
moved from can proceed to review. Cascadia `scan_8049.png` was already on hold for its bank flags. No text-layer bill
is flagged: Evergreen's weak total is left to `TOTAL_MISMATCH`, and Blue Heron's and Zephyr's weak vendor to
`VENDOR_NOT_FOUND`. History replay: identical, because history bills have no confidence scores. The coverage map
now lists the scans under this flag.

## Bank reconciliation (`controls/reconciliation.py`)

`reconcile(bank_rows, payment_rows, ref)` matches each line of `bank_statement.csv` (the CAD operating account) to the
payment behind it and classifies everything else. API: `GET /reconciliation/bank`, controller and auditor only.

**Matching**
- **EFT** (`EFT PMT <payee> <ref>`): the line's reference is the last 6 digits of the payment's `BRIM-EFT-` reference.
  If the reference matches nothing, the line is matched by amount and payee to an EFT paid within 5 days, and says so
  (`MATCHED_WITHOUT_REFERENCE`). A payee that isn't the payment's vendor is `PAYEE_DIFFERS`.
- **Cheques** (`CHEQUE <no> CLEARED`): the payment record doesn't carry the cheque number, so each cleared cheque goes
  to the cheque payment issued closest before it, within 60 days. Exact amounts are paired first, then amounts within
  $1.00 (reported as `AMOUNT_DIFFERS`). This matters for the 10 identical $6,990.48 rent cheques: each month's
  clearing goes to that month's cheque.
- **Fees** (`... FEE`, `SERVICE CHARGE`): `bank_fee`. A wire fee on a day no payment went by wire is
  `WIRE_FEE_WITHOUT_WIRE`.
- **Anything else** is `unexplained` (`UNEXPLAINED_DEBIT` / `UNEXPLAINED_CREDIT`).

**Payments with no bank line**:
- `PAID_BY_CARD` (info): the payment settles on the card account.
- `SCHEDULED` (info): not sent yet.
- `IN_TRANSIT` (info): sent in the last 3 days.
- `OUTSTANDING_CHEQUE` (info), or `STALE_CHEQUE` (review) after 90 days.
- `NOT_ON_STATEMENT` (review): settled in the records but missing from the statement.

**Double payments** use the duplicate checks' rules: the same vendor and normalized invoice number, or an AP payment
plus an employee card charge for the same amount. Instalments of one invoice don't count. A test checks the groups
equal the history replay's. The extra copy's bank line gets `DOUBLE_PAYMENT`, and a scheduled extra copy gets
`DOUBLE_PAYMENT_AT_RISK`. Payments sent after an unverified bank change get `PAID_AFTER_UNVERIFIED_BANK_CHANGE`.

**Results on the dataset** (statement 2026-01-05 to 2026-11-02, 354 lines, $1,742,643.22 out). The API reading the
seeded database gives exactly the same answer (`tests/api/test_reconciliation.py`).
- **Matched: 333 lines, $1,740,825.21.** That's all 313 EFTs and all 20 cheques. Every settled EFT and every cheque in
  `payments.csv` is on the statement.
- **Bank fees: 16, $385.00.** 10 monthly account fees ($29.50) and 6 wire fees ($15.00). **No payment in the data was
  sent by wire**, so the 6 wire fees need an explanation from the bank.
- **Unexplained: 5 pre-authorized debits, $1,433.01** (BK-00064, BK-00088, BK-00192, BK-00193, BK-00207). They match no
  payment, bill or card charge, and no vendor pays by pre-authorized debit. Someone authorized a pull from the account,
  or nobody did.
- **Double payments: 10 bills, $23,536.76 paid out extra, and $2,457.19 scheduled to go out again** (Summit
  AP-00394/AP-00407, `PAY-00399`: cancel it). 7 of the extra copies are bank lines. The other 3 extra copies were card
  charges.
- **Amounts that differ: 4.** Cheque 5018 (BK-00296) cleared for $6,990.53 against a $6,990.48 cheque, 5 cents over.
  Three EFTs took one cent more than the payment (BK-00121, BK-00190, BK-00230).
- **Records not updated: 20.** All 20 cheques cleared the bank, but every one is still `outstanding` in `payments.csv`.
- **Paid after an unverified bank change: 1.** Cascadia AP-00388 (BK-00347, $3,290.01) went out 2 days after the
  email-requested change.

## Bugs not fixed yet

From the code review. The review's other items were fixed: permissions, currency, unknown vendors, contract and
split false positives and bank fields on `b/controls-fixes`; the history replay on `b/controls-replay`.

### Minor
- Due date isn't checked against the vendor's payment terms.
- Invoices dated before the PO, the contract start or vendor onboarding aren't flagged.
- A closed PO with money left still accepts new bills.
- HST 15% provinces (NS, NB, NL, PE) are unsupported: no codes in `tax_codes.csv`, so those bills get no tax check.
- A wrong `contract_id` on the bill silently falls back to the vendor's first contract.

## Open questions for the team

1. **`RefData` vs `ReferenceRepository`:** API/DB team, let's agree on one.

## Likely judge questions

**Why no LLM in controls?**
Controls decide whether money moves. They have to be reproducible, explainable and unit-tested. The LLM only reads
the document (extraction); the rules are plain code.

**How do you avoid false positives on duplicates?**
Layers with scores, and known exceptions: recurring fixed-fee vendors need similar invoice numbers too, credit
notes never match invoices, and AP card payments are skipped. A near match (same amount, new number) also needs
alike invoice numbers or the same service month, so two phases of one job billed the same day don't match. Splits ignore duplicate pairs, bills on their own
POs and other departments, which removed the Deskhive and Redline false positives. Replaying all 426 historical invoices
(`cd backend && python scripts/replay_history.py`) shows what fires, judging each bill as of its own date.

**What did it find in the history?**
Run `cd backend && python scripts/replay_history.py`. Each bill is judged only on what was known on its own date, and
each duplicate pair or split group is counted once. Lead with Cascadia:
- **AP-00388 ($3,290.01) was paid on Oct 29, two days after Cascadia's bank account was changed by email with no
  callback** (Oct 27). **AP-00426 ($2,563.92) is approved and next in line to be paid** to the same account. Hold it.
- **4 bills paid twice or more, $16,813.66 paid out extra** (same invoice number): Redline AP-00136/155 ($7,456.10),
  Alpenglow AP-00215/224 plus a card charge, paid three times ($5,022.72), Northbound AP-00073/77 ($2,639.61),
  Lakeshore AP-00023/34 ($1,695.23). **1 more is set to be paid twice:** Summit AP-00394/407 ($2,457.19 at risk).
- **5 more are likely paid twice** through an AP payment plus an employee card charge ($6,723.10), matched by vendor
  name, amount and date rather than invoice number. Call these "likely".
- **From the approval records:** 3 self-approvals (U010 on AP-00092, AP-00178, AP-00235), 2 bills over their PO that
  skipped the finance manager step (AP-00159, AP-00216). Nobody approved and released the same bill.
- Also: 3 wrong-tax bills, 5 bills on lookalike vendor records, and Torque Industrial's likely split (3 bills,
  ~$14k in 2 days). 48 of the 426 bills have at least one warn or block flag.

**Did you catch anything the dataset notes didn't mention?**
Cascadia's scanned invoice is dated 3 days before the Oct 27 bank change but already shows the new bank account. A
real invoice from before the change would show the old account, so the invoice was likely edited or forged. The
engine holds the bill, but it doesn't yet flag this specific date mismatch on its own.
Update: it does now. `BANK_DETAILS_MISMATCH` (`kind: account_before_change`) fires on the scan: "Invoice dated
2026-10-24 shows bank account …9679, but that account was only set up on 2026-10-27 (BC-009, via email_request)."

**Why do tax and math errors block payment?**
Paying a wrong invoice means paying the wrong amount, or claiming input tax credits the CRA won't allow. So the bill
waits for a corrected invoice, or for a finance manager or the controller to accept it with a written reason, which
goes into the audit log.

**Why recompute tax instead of trusting the invoice?**
The printed tax is what we're auditing. Expected tax comes from the place of supply, the vendor and the line type.

**What if an approver is on leave, or approves their own bill?**
On leave: their named delegate, recorded as `delegated_from`. Own bill: escalate to their manager, recorded as
`escalated_from`. And one person never fills two steps (the U012 → U003 delegate case goes to the controller).

**Can the person who approved a bill also pay it?**
No. P11 is enforced in `can_release`, on the server, together with the $100k finance manager / controller split.
The requester can't release their own bill either, and a credit note can never be released.

**What stops someone splitting a $14k bill into three to dodge the $10k limit?**
`POSSIBLE_SPLIT`, and the group is routed at the combined amount. There's no minimum per piece, so four $2,500
bills in a few days are caught too.

**What if the rules change?**
Thresholds and role chains come from `approval_policies.csv`. Change the CSV (or the DB table later), not the code.

**Why `Decimal`?**
Floats give 0.1 + 0.2 = 0.30000000000000004. Tax checks to the cent need exact money.

**How do you handle the hidden batch?**
No rules are keyed to specific files or vendors. Everything is derived from master data, policies and the bill
itself, and the batch is checked against itself as well as history.

**What does the UI show for a flag?**
A plain-English message, evidence (expected vs found), and the field to highlight.
