# Controls engine

How the controls engine in [`backend/app/controls/`](../backend/app/controls/) checks a bill, decides who approves it
and who may pay it, and what it found in the dataset.

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
| `bill` | `DraftBill` | The bill to check (the extraction pipeline's output) |
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
| `recommendation` | `"Hold until cleared: <titles of the blocking flags>."` when blocked, else `None` |

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
result.recommendation     # "Hold until cleared: Lookalike vendor."
```

### The other public functions

| Function | Use |
| --- | --- |
| `can_approve(user_id, step, bill, ref, *, route, amount_cad=None)` | Call on the server before recording an approval. Pass the full `route` (the final signer's limit is checked) and, for a split, the combined amount. Returns `PermissionDecision(allowed, reason)`. |
| `can_release(user_id, amount_cad, approver_ids, flags, approval_complete, ref, *, bill)` | Call before releasing a payment. Pass `result.flags` so duplicates hold the payment, and the `bill` (requester and credit-note checks). |
| `validate`, `find_duplicates`, `duplicate_flags`, `find_split`, `route` | The pieces `run_controls` calls, if you need one alone. |
| `load_refdata()` / `bill_from_history(...)` | Load reference data; turn a historical invoice row into a `DraftBill` (tests, replay). |
| `build_refdata(rows_by_file, as_of=None)` / `REFDATA_FILES` | **For a database-backed loader.** Builds `RefData` from rows instead of files: a dict keyed by the 12 CSV stems in `REFDATA_FILES` (`"vendors"`, `"users"`, …, `"approval_policies"`), each a list of `dict[str, str]` rows with the CSV's column names. `as_of` defaults to the settings date. `load_refdata()` is `build_refdata` over the CSVs, and a test checks both give identical `RefData`. |
| `incoming.run_batch(items)` / `incoming.render_report(...)` | Runs the controls on the extracted incoming batch as one batch (so in-batch duplicates and splits are caught), sorts problem bills first and renders the report. Printed by `backend/scripts/run_incoming.py`. |
| `history.replay(ref)` | Replays all historical invoices, each judged as of its own date, plus checks on `approvals.csv` and `payments.csv`. Printed by `backend/scripts/replay_history.py`. |
| `flag_help.help_for(code)` / `flag_help.FLAG_HELP` | **For display.** A short title and one plain-English help sentence (what it means, what to do) for every code in `FLAG_CODES`, plus its severity. The UI shows the title as the badge, the flag's own `message` for this bill's details, and the help as a tooltip or help panel. A test fails if a code has no help. |
| `refdata.history_taxes(ref, invoice, lines)` | Tax lines for a historical invoice, with the same tax codes the engine uses. The database seed uses it directly (`_history_taxes` is an alias). |
| `early_pay.suggest_pay_dates(ref, payments)` / `early_pay.discount_history(ref, payments)` / `early_pay.parse_terms(text, days)` | **Early-payment discounts.** Best pay date and saving for approved and scheduled bills, and the discounts history took and missed. Payments are CSV-shaped rows (`payments.csv`), so the database adapter (`services/early_pay.py`) feeds it the same way. See "Early-payment discounts" below. |
| `reconciliation.reconcile(bank_rows, payment_rows, ref)` | **Bank reconciliation.** Matches every bank statement line to its payment and explains the rest. Rows are CSV-shaped dicts (`bank_statement.csv`, `payments.csv`), so the CSV loader (`load_bank_and_payments()`) and the database adapter (`services/reconciliation.py`) feed it the same way. Returns `Reconciliation` (lines, payments, double payments, `summary()`). See "Bank reconciliation" below. |
| `validate.suspicious_lookalikes(ref, vid)` | The lookalike-record rule on its own: the vendor records `vid` is a suspicious copy of (see the Vendor checks). `check_vendor` uses it for `VENDOR_LOOKALIKE`, and `GET /vendors` and `GET /vendors/{id}` use it for their `lookalike_of` field, so the vendor screens mark exactly the records whose bills get flagged. |

`controls.permissions` re-exports `can_approve` / `can_release`.

**Flag help.** Every flag has a code, a severity and a `message` about this bill. For the general explanation, call
`help_for(flag.code)` from `app.controls.flag_help` (also exported from `app.controls`):

```python
help_for("BANK_CHANGE_UNVERIFIED")
# {"code": "BANK_CHANGE_UNVERIFIED", "severity": "block", "title": "Bank change not verified",
#  "help": "The vendor's bank account was changed recently without a callback check, so hold payment until
#           someone verifies it by phone."}
```

A code that isn't in the map (shouldn't happen) gets a generic title from the code name.

## Where the API calls the controls

Every rule that decides whether money moves runs on the server, inside the write that depends on it. The UI only
shows what the server allows. File paths are under `backend/app/`.

| Controls function | Called from | When | What it's given |
|---|---|---|---|
| `run_controls(bill, batch, ref=)` | `services/controls_runner.py` → `rerun()`, the single path every service uses | A new bill from an upload or inbox run (`services/intake.py` `store_outcome`, started by `services/jobs.py` for the inbox), a header edit or line recoding (`services/bills.py` `update_header`, `code_line`) and submit (`services/bills.py` `submit`) | `ref` is rebuilt from the database on every call by `db/refdata_db.py` `refdata_from_db(exclude_bill_id=<this bill>)` (which uses `build_refdata`), never cached. So admin edits to users, policies and vendors apply at once, and the bill isn't matched against itself. The result is saved as a new versioned run (`db/bills.py` `save_controls_run`), and flag resolutions carry over when a flag is unchanged. |
| `can_approve(user, step, bill, ref, route=, amount_cad=)` | `services/approvals.py` `decision_check()`, used by `approve`, `reject` and the allowed-actions check in `services/actions.py` | Before an approval or rejection is recorded | The stored `route` (`db/bills.py` `route_for_bill`). A manually assigned approver replaces the step's user. `amount_cad` is the split's combined amount when controls saw a split (`controls_runner.routed_amount`). A delegate's decision is stored with `on_behalf_of`. |
| `can_release(user, amount_cad, approver_ids, flags, approval_complete, ref, bill=)` | `services/payments.py` `release_check()`, used by `release` and the allowed-actions check | Before a scheduled payment is released (simulated EFT) | `approver_ids` = everyone who approved, plus everyone a delegate approved for (`db/bills.py` `approver_ids_for_bill`). `flags` = only the flags still open in the latest stored run (`controls_runner.open_flags`), so an overridden flag no longer holds the payment. `approval_complete` = the bill's status is `approved` or `scheduled` (a bill only reaches `approved` through its final step). `bill` = the current `DraftBill`. |
| `flag_help.help_for(code)` | `api/routes_reference.py`: `GET /reference/flag-help`, every role | Loaded by the UI | Title, help and severity for every code in `FLAG_CODES`. |
| `early_pay.suggest_pay_dates` / `discount_history` | `api/routes_early_pay.py`: `GET /early-pay` (`?include_pending=true` adds bills not approved yet), same roles as the payments list (`BACK_OFFICE_READ`: AP clerk, finance manager, controller, auditor), via `services/early_pay.py` `early_pay_report()` | On request (read-only) | Payments read from the database in CSV row shape, and `ref` from `refdata_from_db()`. Response models are at the end of `api/schemas_api.py` (`EarlyPayReport` and friends). |
| `reconciliation.reconcile(bank_rows, payment_rows, ref)` | `api/routes_reconciliation.py`: `GET /reconciliation/bank` (`?only_issues=true` for just what needs review), controller and auditor only (`AUDIT_READERS`), via `services/reconciliation.py` `bank_reconciliation()` | On request (read-only) | Statement lines and payments read from the database in CSV row shape, and `ref` from `refdata_from_db()`. The response models are at the end of `api/schemas_api.py` (`BankReconciliation` and the `Recon*` models). |
| `validate.suspicious_lookalikes(ref, vid)` | `services/vendors.py`: `GET /vendors` and `GET /vendors/{id}`, every role | On request (read-only) | `ref` from `refdata_from_db()`. Fills each vendor's `lookalike_of`. |

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
| Bill sits on a lookalike vendor record (same name after removing Ltd/Inc/&, or same bank account as another vendor) | `VENDOR_LOOKALIKE` (block) | Classic impersonation fraud (V051/V053/V052). Only flags the *suspicious* copy (fewer past invoices, or not active), never the real vendor. The rule is `validate.suspicious_lookalikes`, which the vendor screens use too. |
| GST/HST number differs from master | `GST_NUMBER_MISMATCH` (warn) | Could be OCR or a fake invoice. OCR confusions (1/I/!, 0/O) are folded first, so OCR noise doesn't fire it. |
| Bank details on the invoice differ from master | `BANK_DETAILS_MISMATCH` (block) | Changed bank details on an invoice is the main payment-fraud pattern. Verify by phone on a known number. Only fields present on both the invoice and the master are compared (leading zeros ignored), so a missing institution number isn't a mismatch. |
| Invoice dated **before** a bank change already shows the account that change set up | `BANK_DETAILS_MISMATCH` (block, `kind: account_before_change`) | A genuine invoice prints the account in use on its date. Showing the new one means it was made or edited after the change (Cascadia scan 1624: dated Oct 24, shows the account ending 9679 from the Oct 27 change). The master already holds the new account, so the plain comparison above can't see it. Only a change dated strictly after the invoice counts. History bills dated before a later change carry no bank details (`bill_from_history` leaves them empty rather than copying today's account). |
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
or the can't-claim-it-back message if they charged GST/HST). PST/QST they charge is still checked. A GST number
printed on the invoice counts as registered. Tolerance is 5 cents because some vendors round tax per line. **Unknown
vendors are checked too:** with no master record, a CAD bill is treated as a taxable Canadian supplier and a
foreign-currency bill as a foreign vendor.

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

**Which contract.** `RefData.contract_for` uses the bill's `contract_id` when it names a known contract, else the
vendor's first contract by id. Invoices rarely print a contract number, so a new app bill stores its vendor's
contract when it names none (`db.bills.vendor_contract_id`, the same first-by-id rule). The bill then shows the
contract its flags cite, and `contract_for` finds the same contract through `contract_id`.

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
- **Why rent isn't a duplicate:** fixed-monthly contract vendors (rent, SaaS) bill the same amount every month, and
  their consecutive invoice numbers always look alike (Cloudbarn INV-01561 / INV-01567: 75%). So for them only the
  same service month makes a near match; number similarity doesn't count. Two bills that name the same service month
  still match with unrelated numbers, so a re-issued October rent bill is caught, and a re-sent copy is caught by the
  exact and normalized checks.
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

## Known limits

- **`can_release` trusts the `approver_ids` it is given.** The caller must pass everyone who actually approved,
  including the people a delegate approved for. The API does (`db/bills.py` `approver_ids_for_bill`).
- **`default_refdata()` is loaded once per process.** It is only used when no `ref` is passed (scripts and tests),
  so CSV edits there need a restart. The API always passes a `ref` built from the database on each call
  (`build_refdata` over the database rows, same keys and column names as the CSVs).
- **Two reference-data interfaces.** The controls take a `RefData`; the reference module (`app/reference/`) offers a
  `ReferenceRepository` for extraction and coding. Both read the same master data, but they aren't unified.
- **Invoices don't print a department**, so routing would have no department manager. `run_incoming.py` uses the
  department the line coding suggestions give the most money to, and the report marks it "suggested by coding".
- **Very short invoice numbers can collide.** The normalized-number duplicate check keeps digits only, so `A-1`
  and `B-1` from the same vendor match as `DUPLICATE_EXACT`. Real numbers are longer, and it doesn't happen in the
  dataset.
- **No received date in the schema**, so "stale" and "future" use the as-of date.
- Due date isn't checked against the vendor's payment terms.
- Invoices dated before the PO, the contract start or vendor onboarding aren't flagged.
- A closed PO with money left still accepts new bills.
- HST 15% provinces (NS, NB, NL, PE) are unsupported: no codes in `tax_codes.csv`, so those bills get no tax check.
- A wrong `contract_id` on the bill silently falls back to the vendor's first contract.

## Incoming batch results (2026-11-21)

`cd backend && python scripts/run_incoming.py`. All 56 files were read, 0 unreadable. First run: **19 hold**,
**14 review**, **23 can proceed**, $89,963.04 CAD on hold. With the fixes and checks added since (see the reruns
below): **24 hold, 10 review, 22 can proceed, $110,405.03 CAD on hold**.

Email triage: 55 emails carry the 56 invoice attachments. The other 4 (EM-056 to EM-059) are a statement, a payment
inquiry, a missing attachment and a marketing email, and were listed correctly. The two scans and the two French
invoices were checked by hand against the files. Numbers, dates and totals were all read correctly, so none of the
flags below come from extraction mistakes.

### Against the known dataset traps, row by row

| Known trap | Result |
|---|---|
| Exact duplicates: Polar 000961, Cloudbarn INV-01561, Harlow 001468 | Caught: `DUPLICATE_EXACT` on all three (AP-00393, AP-00370, AP-00389). Cloudbarn's original was paid by AP virtual card (CT-00556). `ALREADY_PAID_BY_CARD` is deliberately not raised for AP virtual-card payments, and the exact match already holds the bill. |
| Brightline "583" | Caught: `DUPLICATE_EXACT` (normalized: 583 == FA-000583), plus `PO_REQUIRED_MISSING` |
| Voyageur "000903-A" | Caught, as an exact duplicate rather than a near match: `DUPLICATE_EXACT` (normalized, score 0.95). AP-00277 is already paid, so blocking is right. |
| Queen St rent $18,758 | Correct: not flagged as a duplicate. Routed P02: department manager (U003, delegate for U012), then finance step (U002) |
| Blue Heron, Zephyr | Caught: `VENDOR_NOT_FOUND` |
| Riverbend 1739 | Caught: `PO_REQUIRED_MISSING` (block), `VENDOR_PENDING_REVIEW` (with the P05 finance step) and `GST_NUMBER_MISSING` (warn: "Confirm the vendor is a small supplier (under $30k/year) before paying"). No tax flag: with no GST number, it's treated as a small supplier that shouldn't charge tax, and it charged none. (Earlier runs also showed `TAX_MISSING`; see the tax-and-math rerun.) |
| Harlow **and** Stern (EM-026) | Caught: `VENDOR_LOOKALIKE` of V026, plus the P06 finance step |
| V053 Great Lakes Incorporated | n/a: both Great Lakes files matched V002 |
| Cascadia 1625 and `scan_8049.png` | Caught: `BANK_CHANGE_UNVERIFIED` on both |
| Polar 000964 fuel 22% | Caught: `OVER_FUEL_SURCHARGE_CAP` |
| Northbound AB charged HST | Caught: `TAX_WRONG_FOR_PROVINCE` |
| Beaumont QC, no QST | Caught: `TAX_MISSING` |
| Signal & Sparrow PST on services | Caught: `PST_ON_SERVICES` |
| Ironwood, no tax | Caught: `TAX_MISSING`, plus `PO_REQUIRED_MISSING` |
| Evergreen total | Caught: `TOTAL_MISMATCH` (3,339 vs 3,439) |
| Northstar line math | Caught: `LINE_MATH_ERROR` (24 × 150) |
| Requires a PO, field blank (Summit, Hardhat, Alpenglow, Brightline, Fixwell + credit note, Ironwood, Keystone, Torque) | Caught: `PO_REQUIRED_MISSING` on all 9, and on Riverbend (10 total) |
| Credit notes: Fixwell, Great Lakes | Caught: `CREDIT_NOTE`, not routed for payment. The Fixwell credit note is also held for its missing PO, as expected. |
| USD: Sparkgrid, Tessera | Correct: converted at the rate printed on the bill. No false Canadian-tax flags. "Preferred method = card" isn't shown; that belongs to payment, not controls. |
| French: Laurentian, Place Mont-Royal | Correct: comma decimals read correctly (5,015.98 and 6,990.48). No false flags. |
| Scans `scan_8049.png`, `scan_8749.png` | Correct: read by the vision model and checked against the images. No false GST or bank flags. |
| EM-029 Orion 279 + 281 (+ 287) | Correct: two bills from one email. C023's $25k NTE isn't breached (October total $14,543.10), so no NTE flag. The first run raised a false `DUPLICATE_LIKELY` between 279 and 281, since fixed (see False alarms). |
| EM-056 to EM-059 | Correct: listed as statement, payment inquiry, missing attachment and marketing |

### False alarms

1. **Fixed. Orion 279 ↔ 281, `DUPLICATE_LIKELY` (warn).** Different invoice numbers, both attached to the same email,
   with amounts 0.5% apart. The near-match rule (same vendor, amount within 1%, within 14 days) used
   invoice-number similarity only for the score, not as a condition.
   Fix: a near match now also needs invoice numbers ≥ 60% alike or the same service month in the lines. 279 vs 281
   are 33% alike, and their lines name phases, not months, so they no longer match. The history replay didn't
   change, because no historical bill had a near match.
2. **Fixed. Lattice 557, `OVER_CONTRACT_RATE` (warn).** The $8,200 is a one-off "Implementation and data migration",
   not the monthly fee. The check compared any bill from a fixed-monthly vendor to the $1,320 fee. The bill still
   deserves a question (it isn't covered by the contract), but the message was wrong.
   Fix: one-off lines are left out of the fee comparison and get their own warning (`kind: one_off`): "One-off
   charge of $8,200.00 (Implementation and data migration) is not part of the $1,320.00/month fee in C005. Not an
   overcharge by itself: confirm it was ordered."
3. **Fixed. Cloudbarn INV-01561, extra `DUPLICATE_LIKELY` vs AP-00411 (INV-01567, the October subscription).** On a
   fixed-monthly vendor, consecutive invoice numbers always look ≥ 60% alike, so the number rule doesn't help. It
   was harmless here, since the exact duplicate already blocks the bill, but on a clean monthly bill it would be
   noise.
   Fix: for fixed-monthly vendors a near match needs the same service month. INV-01561 now gets only
   `DUPLICATE_EXACT` vs AP-00370 (September's, paid).
4. **Debatable: `POSSIBLE_SPLIT` (warn) on Cascadia (1619 + 1624 + 1625, $15,308.84) and Orion (279 + 281 + 287,
   $14,543.10).** Carriers and consultants often bill per load or per engagement, but three bills in 3 days
   above $10k together is exactly the pattern P01 is about. Kept as a warning.

### Misses

1. **Now checked.** Cascadia 1624 (`scan_8049.png`) is dated 2026-10-24 but already prints the new account (ending
   9679), which was only changed on 2026-10-27 by an unverified email request. The first run held the bill for the
   unverified change only; it is now flagged on its own, see "Cascadia: likely edited or forged invoice".

### Cascadia: likely edited or forged invoice

Cascadia's scanned invoice is dated 3 days before the Oct 27 bank change but already shows the new bank account. A
real invoice from before the change would show the old account, so the invoice was likely edited or forged.
`BANK_DETAILS_MISMATCH` (`kind: account_before_change`) fires on the scan: "Invoice dated 2026-10-24 shows the bank
account ending 9679, but that account was only set up on 2026-10-27 (BC-009, via email_request). On the invoice date
the account was the one ending 7504, so the invoice was likely edited or forged."

### Rerun after the false-alarm fixes

Levels are unchanged: 19 hold, 14 review, 23 can proceed, $89,963.04 CAD on hold. Orion 279 and 281 stay under
review because of `POSSIBLE_SPLIT`, and Lattice 557 because of the one-off warning. `DUPLICATE_LIKELY` drops from 3
bills to 1 (only Cloudbarn INV-01561, false alarm 3), and "Duplicates inside this batch" no longer appears. The
history replay output is identical.

### Rerun after the new flag codes

Riverbend 1739 now also gets `VENDOR_PENDING_REVIEW` and `GST_NUMBER_MISSING`. Nothing else changed: 19 hold,
14 review, 23 can proceed, $89,963.04 CAD on hold (Riverbend was already held for its missing PO). No bill came from
an unexpected sender domain, none has an unknown PO number or a missing FX rate, and no requester is terminated.
The history replay output is identical.

### Rerun after the bank-date check and the monthly near-match rule

**20 hold, 13 review, 23 can proceed, $92,064.84 CAD on hold** (was 19 / 14 / 23 and $89,963.04).
- The new bank-account check fires on 2 bills. **Cascadia `scan_8049.png`** was already held, and the new flag now
  leads its hold reason. **Lumen FA-001761** moves from review to hold ($2,101.80): dated 2026-04-06, it prints
  the account ending 0921, which BC-006 (verified by callback) only set up on 2026-04-26. That can be harmless (a
  vendor re-sending an old unpaid invoice may regenerate it with current bank details), but it's worth a call, and
  the bill is also 210 days old.
- Cloudbarn INV-01561 lost only its near match to next month's bill. `DUPLICATE_LIKELY` is now 0.
  `DUPLICATE_EXACT` is still on the same 5 bills.
- History replay: identical.

These numbers are with tax and math flags as `warn`; the next rerun makes them `block`.

### Rerun with tax and math flags as block

**24 hold, 9 review, 23 can proceed, $110,405.03 CAD on hold** (on top of the previous rerun's 20 / 13 / 23 and
$92,064.84). Four bills moved from review to hold: Evergreen 000850 (`TOTAL_MISMATCH`, $3,439.00), Beaumont
FA-000557 (`TAX_MISSING`, $8,101.67), Northbound 000639 (`TAX_WRONG_FOR_PROVINCE`, $2,505.52) and Northstar
NO26-1773 (`LINE_MATH_ERROR`, $4,294.00). Ironwood has `TAX_MISSING` too but was already held for its missing PO.

Small-supplier rule: Riverbend 1739 has no GST number anywhere, so it's treated as a small supplier that shouldn't
charge tax. It charged none, so it no longer gets `TAX_MISSING`, which would now block a legitimate invoice. It
keeps `GST_NUMBER_MISSING` as a warning ("Confirm the vendor is a small supplier (under $30k/year) before paying")
and stays held for its missing PO, with `VENDOR_PENDING_REVIEW`. No other incoming bill changed. History replay:
same counts; the 3 tax flags show as block instead of warn.

### Caught beyond the known traps (checked against the PDFs: real, not extraction errors)

- Summit 000809 is printed with date 2026-11-27, in the future → `DATE_ANOMALY`.
- Lumen FA-001761 is printed with date 2026-04-06, 210 days old → `DATE_ANOMALY`.
- Torque 1771 is under contract C025, which expired 2026-06-30 → `CONTRACT_EXPIRED`.
- Aurora AU26-2207 ($2,343.50 vs $2,150 fee, +9%) and Pinecone PI26-2809 ($826.80 vs $780, +6%) →
  `OVER_CONTRACT_RATE`.
- Redline FA-001687: October pre-tax billing reaches $9,946.54 with AP-00424, over the C027 $9,000 limit →
  `OVER_CONTRACT_NTE`.

### Detection coverage map

[`docs/DETECTION_COVERAGE.md`](DETECTION_COVERAGE.md) maps each "real-world mess" item in the brief to the flags
that catch it, with one example bill (from the batch, or the history when the batch has none). It also lists what
nothing catches. `backend/tests/controls/test_detection_coverage.py` runs the batch offline, replaying the recorded
model output in `backend/tests/fixtures/raw/`. It fails if any example stops getting its flag.
Rerun with all of the above: still 24 hold / 9 review / 23 can proceed, $110,405.03 on hold. Gaps found at that
point: low-quality scans had no flag (added in the next rerun). Self-approval can't be seen at intake because
invoices print no requester (it's enforced at approval). Seven flags, and `DATE_ANOMALY`'s "due before invoice"
case, have no real example and are only tested on made-up bills.

### Rerun with `LOW_EXTRACTION_CONFIDENCE`

**24 hold, 10 review, 22 can proceed, $110,405.03 CAD on hold.** Only the two scans changed. Each was read by the
vision model (no tesseract here) and carries that note, so both get the warning. Prairie Natural Gas `scan_8749.png`
moved from can proceed to review. Cascadia `scan_8049.png` was already on hold for its bank flags. No text-layer bill
is flagged: Evergreen's weak total is left to `TOTAL_MISMATCH`, and Blue Heron's and Zephyr's weak vendor to
`VENDOR_NOT_FOUND`. History replay: identical, because history bills have no confidence scores. The coverage map
now lists the scans under this flag.

## Early-payment discounts (`controls/early_pay.py`)

**Terms in the data.** `vendors.csv` has two columns: `early_pay_discount` and `payment_terms_days`.
- `early_pay_discount` is blank for 53 vendors. For the other 3 it's `2/10 net 30`: V010 Ironwood Pallet, V024 Paper
  Trail Office Supply and V033 Lumen Print & Signage.
- `payment_terms_days` is 30, 21, 15 or 0 (0 = due on receipt).

`parse_terms(text, days)` reads the dataset's format, plus the common variants a hidden dataset might use: `2/10 n/30`,
`2/10, net 30`, `2% 10 net 30`, `1.5/15 net 45`, `net 45`, `n/60` and `due on receipt`.
- **Blank text:** no discount, and `payment_terms_days` is the net days.
- **The text and `payment_terms_days` disagree:** the written term wins, with a note.
- **Text that can't be read** (e.g. `2/10 EOM`) or that makes no sense (`2/30 net 30`): no discount, with a note,
  never a guess.

A test checks every vendor in the dataset parses with no note.

**How the discount works**, checked on all 19 payments to the three vendors:
- It's **2% of the pre-tax subtotal**. Taxes are never discounted. All 9 discounts taken match this to the cent
  (a test checks each one).
- The **10 days count from the invoice date**. Every discount taken was paid on day 9, the day before the deadline,
  because an EFT posts the next day.

**Best pay date** (`suggest_pay_dates`, for `approved` and `scheduled` bills by default):
- **The discount is still open:** pay on the last day that still earns it. That's the deadline minus the method's
  lead days (EFT 1, cheque 3, card 0), never before today. The saving is the discount, compared with paying on the
  due date. Skipping 2/10 net 30 costs about 37% a year (2/98 for 20 days).
- **No discount, or it has ended:** pay on the due date. Paying earlier saves nothing. If it's already due, pay
  today. An ended discount is named in the reason.
- **Reschedule:** the action is `reschedule` when a scheduled payment falls after the discount ends, or after the
  due date.
- **Held bills are left out:** `GET /early-pay` (`services/early_pay.py`) skips bills whose latest controls run has an
  open blocking flag, so a held duplicate is never "Pay now".

Due dates use the invoice's own due date and get a note if it disagrees with the terms. Paying on the due date uses no
lead days, because in this data a payment's scheduled date is its due date. Credit notes are skipped.

**Results.**
- **Approved and scheduled bills:** none of the 20 is from a discount vendor, so the saving today is $0.00.
  - AP-00399 (Quillpad, due 2026-11-01) is overdue: pay now.
  - 4 bills are due today, and the rest are due on their dates.
- **Incoming batch, once approved:**
  - **Paper Trail 2217** ($542.16 subtotal, dated 2026-10-26) can proceed. Paying by 2026-11-04 saves **$10.84**.
  - **Ironwood INV-02210** would save $18.31 if paid by 2026-11-08, but it's on hold (missing PO, no tax charged).
  - **Lumen FA-001761**'s window closed in April.

  `?include_pending=true` shows these bills before they're approved.
- **History** (`discount_history`): **9 discounts taken, $296.18. 10 missed, $827.77.** The 10 missed were paid 30 to
  33 days after the invoice, so 7 of them were also late. The biggest is AP-00180, Ironwood's $10,096.40 subtotal,
  $201.93 missed.

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
`DOUBLE_PAYMENT_AT_RISK`, whose note ends "Cancel PAY-00399 before it is sent." (the reconciliation screen links the
payment). Payments sent after an unverified bank change get `PAID_AFTER_UNVERIFIED_BANK_CHANGE`.

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

## Questions and answers

**Why no LLM in controls?**
Controls decide whether money moves. They have to be reproducible, explainable and unit-tested. The LLM only reads
the document (extraction); the rules are plain code.

**How do you avoid false positives on duplicates?**
Layers with scores, and known exceptions: fixed-monthly vendors need the same service month for a near match, credit
notes never match invoices, and AP card payments are skipped. A near match (same amount, new number) also needs
alike invoice numbers or the same service month, so two phases of one job billed the same day don't match. Splits
ignore duplicate pairs, bills on their own POs and other departments, which removed the Deskhive and Redline false
positives. Replaying all 426 historical invoices (`cd backend && python scripts/replay_history.py`) shows what fires,
judging each bill as of its own date.

**What did it find in the history?**
Run `cd backend && python scripts/replay_history.py`. Each bill is judged only on what was known on its own date, and
each duplicate pair or split group is counted once.
- **AP-00388 ($3,290.01) was paid on Oct 29, two days after Cascadia's bank account was changed by email with no
  callback** (Oct 27). **AP-00426 ($2,563.92) is approved and next in line to be paid** to the same account. Hold it.
- **4 bills paid twice or more, $16,813.66 paid out extra** (same invoice number): Redline AP-00136/155 ($7,456.10),
  Alpenglow AP-00215/224 plus a card charge, paid three times ($5,022.72), Northbound AP-00073/77 ($2,639.61),
  Lakeshore AP-00023/34 ($1,695.23). **1 more is set to be paid twice:** Summit AP-00394/407 ($2,457.19 at risk).
- **5 more are likely paid twice** through an AP payment plus an employee card charge ($6,723.10), matched by vendor
  name, amount and date rather than invoice number, so they are reported as likely.
- **From the approval records:** 3 self-approvals (U010 on AP-00092, AP-00178, AP-00235), 2 bills over their PO that
  skipped the finance manager step (AP-00159, AP-00216). Nobody approved and released the same bill.
- Also: 3 wrong-tax bills, 5 bills on lookalike vendor records, and Torque Industrial's likely split (3 bills,
  ~$14k in 2 days). 48 of the 426 bills have at least one warn or block flag.

**Did you catch anything the dataset notes didn't mention?**
Cascadia's scanned invoice is dated 3 days before the Oct 27 bank change but already shows the new bank account. A
real invoice from before the change would show the old account, so the invoice was likely edited or forged.
`BANK_DETAILS_MISMATCH` (`kind: account_before_change`) flags it on its own; see "Cascadia: likely edited or forged
invoice".

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
Thresholds and role chains come from the policy table (`approval_policies.csv`, seeded into the database, where the
admin policies page edits it). Change the policy, not the code: controls read the database on every call.

**Why `Decimal`?**
Floats give 0.1 + 0.2 = 0.30000000000000004. Tax checks to the cent need exact money.

**How do you handle the hidden batch?**
No rules are keyed to specific files or vendors. Everything is derived from master data, policies and the bill
itself, and the batch is checked against itself as well as history.

**What does the UI show for a flag?**
A plain-English message, evidence (expected vs found), and the field to highlight.

## Message wording

The text the controls write is read by AP, approvers and auditors in the app, so it uses the app's words. Codes,
ISO dates and user ids don't appear in messages, reasons or notes.

- **`wording.py`** holds the shared pieces:
  - `human_date` writes dates as "Nov 2, 2026".
  - `money_text` writes "$1,234.50" for CAD and "US$1,234.50" for USD.
  - `status_label` writes "outstanding", "needs review".
  - `channel_phrase` writes "email request".
  - `role_group` writes "AP clerks".
  - `flag_title` / `flag_titles` take titles from `flag_help`.
  - `account_ending` / `account_change` write a bank account as "ending 9679" (never "…9679") and a change as
    "ending 7504 → ending 9679".
- **`ControlsResult.recommendation`** is "Hold until cleared: <titles of the blocking flags>." (for example
  "Hold until cleared: Duplicate invoice."), `None` when nothing blocks. Each flag's full message is shown with the
  flag itself.
- **`can_release` reasons** speak to the person asking, since its only caller passes the acting user:
  - "You approved this bill, so another finance manager or the controller must release it (policy P11)."
  - "You requested this bill, so someone else must release its payment."
  - "On hold until these flags are cleared: <flag titles>."
  - "<Role group> can't release payments."

  The policy ids P09, P10 and P11 are still in the text.
- **Approval route notes:** "<name> is on leave (since Oct 20, 2026), so <delegate> approves as delegate."
- **Flag messages:**
  - The tax flags (`TAX_MISSING`, `PST_ON_SERVICES`, `TAX_WRONG_FOR_PROVINCE`) don't end with "Ask the vendor for a
    corrected invoice.", because their flag help says what to do.
  - `BANK_CHANGE_UNVERIFIED` reads "The bank account changed on Oct 27, 2026 by email request (ending 7504 → ending
    9679). Nobody has confirmed it by phone."
  - `BANK_DETAILS_MISMATCH` (account before the change) reads "… shows the bank account ending 9679 … On the invoice
    date the account was the one ending 7504 …".
  - `FOREIGN_CURRENCY` uses "US$" and "Nov 2, 2026".
  - `PO_CLOSED_OR_WRONG_VENDOR` doesn't say "PO PO-…".
- **Duplicate reasons** read "same total $2,457.19" (or "total $X vs $Y") and "AP-00394 is scheduled".
- **Early payment:**
  - Reasons use human dates: "Overdue since Nov 1, 2026: pay now.", "Due today: pay today.", "Due Nov 3, 2026.
    Paying earlier saves nothing.".
  - A discount says how pay-by relates to the deadline: "Pay by Nov 8, 2026, 1 day before the discount ends on
    Nov 9, 2026, to take …".
- **Reconciliation and history findings** use human dates and words for statuses and request channels. The history
  finding `paid_after_unverified_bank_change` writes the change as "(ending 7504 → ending 9679)", and
  `DOUBLE_PAYMENT_AT_RISK` ends "Cancel PAY-00399 before it is sent."
