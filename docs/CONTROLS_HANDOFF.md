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

`controls.permissions` re-exports `can_approve` / `can_release` (the API guide refers to that module).

## Each check in plain English

### Vendor (`validate.check_vendor`)

| Catches | Flag | Why |
| --- | --- | --- |
| Vendor not in the master | `VENDOR_NOT_FOUND` (block) | Never pay someone who hasn't been onboarded. Routing also adds a finance step (P05). |
| Vendor not in the master, but `name_on_invoice` is ≥ 85% similar to a master vendor's name | `VENDOR_LOOKALIKE` (block) | An unknown sender using a real vendor's name is the impersonation case. Names are compared after removing Ltd/Inc/&/punctuation. |
| Vendor on hold / inactive | `VENDOR_NOT_ACTIVE` (block) | The master says don't pay them. `pending_review` vendors aren't flagged (no code); routing adds the P05 finance step. |
| Bill sits on a lookalike vendor record (same name after removing Ltd/Inc/&, or same bank account as another vendor) | `VENDOR_LOOKALIKE` (block) | Classic impersonation fraud (V051/V053/V052). Only flags the *suspicious* copy (fewer past invoices, or not active), never the real vendor. |
| GST/HST number differs from master | `GST_NUMBER_MISMATCH` (warn) | Could be OCR or a fake invoice. OCR confusions (1/I/!, 0/O) are folded first, so OCR noise doesn't fire it. |
| Bank details on the invoice differ from master | `BANK_DETAILS_MISMATCH` (block) | Changed bank details on an invoice is the main payment-fraud pattern. Verify by phone on a known number. Only fields present on both the invoice and the master are compared (leading zeros ignored), so a missing institution number isn't a mismatch. |
| Vendor's latest bank change was never verified by callback | `BANK_CHANGE_UNVERIFIED` (block) | Cascadia (V004) changed its account by email on Oct 27 with no callback. Hold every payment to it. |

### Tax (`validate.check_tax`)

| Catches | Flag | Why |
| --- | --- | --- |
| A tax that should be charged isn't | `TAX_MISSING` (warn) | e.g. QC bill with GST but no QST (AP-00098). |
| BC PST charged on services | `PST_ON_SERVICES` (warn) | BC PST applies to goods only. |
| Anything else wrong (wrong code, wrong amount) | `TAX_WRONG_FOR_PROVINCE` (warn) | e.g. HST charged on an Alberta delivery (AP-00253). |

**Why tax is recomputed, not trusted:** the vendor's printed tax is exactly what we're checking, so it can't be
the reference. Expected tax comes from the place of supply (`ship_to_province`), the vendor's country and category,
and each line's type: ON = HST 13%; QC = GST 5% + QST 9.975%; BC = GST 5% + PST 7% on goods only;
AB/SK/MB/territories = GST 5%; insurance = exempt; foreign vendors = no Canadian tax. Tolerance is 5 cents
because some vendors round tax per line. **Unknown vendors are checked too:** with no master record, a CAD bill is
treated as a taxable Canadian supplier and a foreign-currency bill as a foreign vendor.

### Arithmetic (`validate.check_arithmetic`)

| Catches | Flag |
| --- | --- |
| quantity × unit price ≠ line amount | `LINE_MATH_ERROR` (warn) |
| lines don't add up to the subtotal | `SUBTOTAL_MISMATCH` (warn) |
| subtotal + taxes ≠ total | `TOTAL_MISMATCH` (warn) |

Tolerance is 2 cents. Extraction never "fixes" printed numbers, so these catch both vendor errors and misreads.

### Contract (`validate.check_contract`)

| Catches | Flag | Why |
| --- | --- | --- |
| Invoice dated after the contract ended | `CONTRACT_EXPIRED` (warn) | Work may not be authorized (Torque Industrial V044). |
| Fixed-monthly bill whose **fee line(s)** exceed the contract fee | `OVER_CONTRACT_RATE` (warn, `kind: fee`) | Only the fee line is compared, not the whole subtotal. Billing *under* the fee isn't flagged (no code). |
| Usage / overage lines on a fixed-monthly bill | `OVER_CONTRACT_RATE` (warn, `kind: overage`) | Billed on top of the fee by design (Redstone V021: $4,800 committed base + data-transfer overage), so it's a "confirm the usage" warning, not an overcharge. |
| Hourly line above the contract's hourly cap | `OVER_CONTRACT_RATE` (warn) | A line is hourly only if its description says hour / hr / hrs / heure. Quantity alone (5 pallets) isn't hours. |
| Fuel surcharge above the contract's cap | `OVER_FUEL_SURCHARGE_CAP` (warn) | Checks both the % printed on the line and the actual % of freight, and uses the worse one (Invoice 000964: 22% vs a 12% cap). |
| This month's billing would pass the contract's monthly not-to-exceed | `OVER_CONTRACT_NTE` (warn) | Sums this vendor's other bills in the same month from history (Orion C023). |

### Purchase order (`validate.check_po`)

| Catches | Flag | Why |
| --- | --- | --- |
| Vendor requires a PO and there isn't one, or it doesn't exist | `PO_REQUIRED_MISSING` (block) | P13: missing PO means hold. |
| PO belongs to another vendor, or is closed and fully used | `PO_CLOSED_OR_WRONG_VENDOR` (block) | |
| Bill is above what's left on the PO | `PO_OVER_BALANCE` (warn) | P12: routing adds a finance manager step. |

### FX, dates, credit notes

| Catches | Flag | Why |
| --- | --- | --- |
| Non-CAD bill | `FOREIGN_CURRENCY` (info) | Shows the rate used, where it came from and the CAD amount. Currency codes are case-insensitive. Rate order: the rate given on the bill (`fx_rate_to_cad`), then the USD/CAD table (USD only; weekends fall back up to 6 days). A non-USD currency is **never** converted at the USD rate. |
| No reliable FX rate | `FOREIGN_CURRENCY` (info), message starts "FX rate missing" | The CAD amount is left unknown (never 1, never guessed); routing uses the face amount and says so on every step. Should be a block: needs `CURRENCY_UNSUPPORTED` (see Open questions). |
| Invoice dated in the future, due before invoice date, or over 180 days old | `DATE_ANOMALY` (warn) | "Today" is the fixed as-of date (2026-11-02) from settings, never the machine clock, so results don't change with the demo date. |
| Credit note | `CREDIT_NOTE` (info) | Apply it to an open invoice instead of paying it. |

### Duplicates (`duplicates.find_duplicates`)

Layered, strongest first. Checked against history (minus rejected invoices) *and* the current batch.

| Kind | Rule | Flag |
| --- | --- | --- |
| `exact` | Same vendor, same invoice number | `DUPLICATE_EXACT` (block) |
| `normalized` | Same vendor, same number after dropping prefixes, punctuation and leading zeros (`FA-000583` = `583`) | `DUPLICATE_EXACT` (block) |
| `near` | Same vendor, amount within 1%, within 14 days | `DUPLICATE_LIKELY` (warn) |
| `cross_vendor` | Different vendor record with the same bank account, amount within 1%, within 30 days | `DUPLICATE_LIKELY` (warn) |
| `card_paid` | Employee card charge with a similar merchant name, same amount, within 45 days | `ALREADY_PAID_BY_CARD` (block) |

- **Unknown vendors:** two bills from vendors not in the master count as the same vendor when the name on the
  invoice is the same (after normalizing), so the same unknown invoice sent twice in one batch is caught.
- **Why rent isn't a duplicate:** fixed-monthly contract vendors (rent, SaaS) bill the same amount every month.
  For them a "near" match also needs the invoice numbers to look alike (≥ 60% similar); otherwise every rent
  bill would match last month's.
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
- **Signatures differ from the old stubs:** functions take a `RefData`, not a `ReferenceRepository`.
- **Not yet run on the incoming batch:** needs Person A's `DraftBill` output end to end.
- **`field_confidence`, `extraction_warnings` and `was_ocr` are ignored.** `LOW_EXTRACTION_CONFIDENCE` exists
  in `FLAG_CODES` but is never raised.
- **No received date in the schema**, so "stale" and "future" use the as-of date.

## Bugs not fixed yet

From the code review. The review's other items (permissions, currency, unknown vendors, contract and split false
positives, bank fields) were fixed on `b/controls-fixes`.

### History replay ([`backend/scripts/replay_history.py`](../backend/scripts/replay_history.py))
- **Applies today's state to past bills** (current bank-change status, terminated requesters), so old bills get flags
  that didn't apply at the time.
- **Counts each duplicate pair twice.**
- **Hides the key case:** AP-00388 was paid on Oct 29, two days after Cascadia's unverified bank change (Oct 27).
- **Doesn't check `approvals.csv`:** U010 self-approved AP-00092, AP-00178 and AP-00235; AP-00159 and AP-00216 went
  over their PO without the finance manager step (P12).

### Minor
- Due date isn't checked against the vendor's payment terms.
- Invoices dated before the PO, the contract start or vendor onboarding aren't flagged.
- A closed PO with money left still accepts new bills.
- HST 15% provinces (NS, NB, NL, PE) are unsupported: no codes in `tax_codes.csv`, so those bills get no tax check.
- A wrong `contract_id` on the bill silently falls back to the vendor's first contract.

## Open questions for the team

1. **Should tax and math flags be `block`?** `TAX_WRONG_FOR_PROVINCE`, `TAX_MISSING`, `LINE_MATH_ERROR`,
   `SUBTOTAL_MISMATCH`, `TOTAL_MISMATCH` are `warn`, so a bill with wrong tax or bad totals can still be paid.
   Needs schema agreement.
2. **Missing flag codes.** These checks are dropped until codes exist in `FLAG_CODES`: `PO_NOT_FOUND` (block),
   `CURRENCY_UNSUPPORTED` (block), `REQUESTER_TERMINATED` (warn), `VENDOR_PENDING_REVIEW` (warn),
   `SENDER_DOMAIN_MISMATCH` (warn). `CURRENCY_UNSUPPORTED` would also cover a missing FX rate (or add a separate
   `FX_RATE_MISSING`): today that case is only reported on the `FOREIGN_CURRENCY` info flag, so it doesn't hold
   the bill.
3. **`RefData` vs `ReferenceRepository`:** API/DB team, let's agree on one.

## Likely judge questions

**Why no LLM in controls?**
Controls decide whether money moves. They have to be reproducible, explainable and unit-tested. The LLM only reads
the document (extraction); the rules are plain code.

**How do you avoid false positives on duplicates?**
Layers with scores, and known exceptions: recurring fixed-fee vendors need similar invoice numbers too, credit
notes never match invoices, and AP card payments are skipped. Splits ignore duplicate pairs, bills on their own
POs and other departments, which removed the Deskhive and Redline false positives. Replaying all 426 historical invoices
(`cd backend && python scripts/replay_history.py`) shows what fires.

**What did it find in the history?**
4 invoices paid twice (AP-00023/34, AP-00073/77, AP-00136/155, AP-00215/224) and 2 scheduled twice (AP-00394/407);
3 wrong-tax invoices; Cascadia's unverified bank change; two lookalike vendors sharing bank accounts with real ones
(V053 was paid twice); Torque Industrial's likely split. Lead with **AP-00388**: paid Oct 29, two days after
Cascadia's unverified bank change. Careful: the replay doesn't show that case yet, still counts duplicate pairs
twice, and doesn't check `approvals.csv` (U010 self-approved three bills), so don't quote its raw totals.

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
