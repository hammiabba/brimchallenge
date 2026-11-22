# controls/

**Owner:** Person B.

Validation, duplicate detection, approval routing and payment release rules.
Pure Python, no database, no web framework, no LLM. Bill in, flags out.

## Run it (from `backend/`)

```bash
pytest tests/controls                 # 72 tests, most based on real cases in the dataset
python scripts/run_incoming.py        # extract the incoming batch and run the controls on it (needs the API key)
python scripts/replay_history.py      # all 426 historical invoices, each judged as of its own date (history.py)
```

Reference data is read from the repo dataset (`get_settings().dataset_dir / "data"`), and "today" is
`get_settings().as_of_date`. Every type and flag code comes from `app/shared/schemas.py`.

## Files

| File | What it does |
| --- | --- |
| `engine.py` | `run_controls(bill, batch) -> ControlsResult`: the one call the backend needs |
| `refdata.py` | Loads the CSVs into one `RefData` object, plus `bill_from_history` and `history_taxes` (also used by the DB seed). `build_refdata(rows_by_file)` builds the same object from DB rows keyed by `REFDATA_FILES`; nothing else changes. |
| `validate.py` | `validate(bill, ref) -> [Flag]`: vendor, tax, arithmetic, contract, PO, FX, dates, credit notes |
| `duplicates.py` | `find_duplicates(bill, ref, batch) -> [DuplicateMatch]`, `duplicate_flags(...)`, `find_split(bill, ref, batch)` |
| `approvals.py` | `route(...) -> [ApprovalStep]`, `can_approve(...)` / `can_release(...) -> PermissionDecision` |
| `incoming.py` | `run_batch(items)` / `render_report(...)`: controls on the extracted incoming batch as one batch, problem bills first (used by `scripts/run_incoming.py`) |
| `history.py` | `replay(ref)`: point-in-time replay of the history, plus approvals/payments checks (used by `scripts/replay_history.py`) |
| `early_pay.py` | Vendor payment terms (`parse_terms`), the best pay date and saving for approved and scheduled bills (`suggest_pay_dates`), and discounts taken and missed in the history (`discount_history`). Served by `GET /early-pay` (see docs/CONTROLS_HANDOFF.md, "Early-payment discounts"). |
| `flag_help.py` | `help_for(code)` / `FLAG_HELP`: short title and one help sentence for every flag code, for the UI |
| `permissions.py` | Re-exports `can_approve` / `can_release` from `approvals.py` (the API guide refers to `controls.permissions`) |

## How the pieces fit

```python
from app.controls import run_controls, can_approve, can_release
result = run_controls(bill, batch)          # batch = the other DraftBills that arrived with it (may include bill)
result.flags, result.duplicates, result.route, result.can_auto_proceed
decision = can_release("U003", amount_cad, approver_ids, result.flags, True, ref, bill=bill)
decision = can_approve("U007", result.route[0], bill, ref, route=result.route)
decision.allowed, decision.reason
```

Duplicates and splits are also returned as flags (`DUPLICATE_EXACT`, `DUPLICATE_LIKELY`, `ALREADY_PAID_BY_CARD`,
`POSSIBLE_SPLIT`), so passing `result.flags` to `can_release` holds a duplicate's payment.
A split is routed at the combined amount.

Flag severity (from `FLAG_CODES`): `block` holds the payment until someone resolves it, `warn` needs a human look, `info` is context.

## For Person A: what to put in a DraftBill

Fill `schemas.DraftBill`. The engine uses `source.file_hash` as the bill's id (the schema has no bill id).
Required by the checks: `vendor.vendor_id` (None if no match), `invoice_number`, `invoice_date`, `currency`, `subtotal`,
`taxes` (one `TaxLine` per tax code), `total`, `lines` (with `line_no` and `line_type`), `ship_to_province`.
Strongly wanted: `vendor.gst_number`, `vendor.bank`, `source.sender_address`, `po_number`, `due_date`, `is_credit_note`.
Money is `Decimal`, not float.

## Design choices (Q&A prep)

- **Pure functions.** No hidden state, so every rule has a unit test and a judge can see exactly why a flag fired.
- **Policies are data.** Thresholds and role chains are parsed from `approval_policies.csv`. Change `$10,000` there and routing follows.
- **Money is `Decimal`.** Floats give 0.1 + 0.2 = 0.30000000000000004. Not OK for tax checks.
- **Tax is recomputed, not trusted.** Expected tax comes from `ship_to_province` + vendor country/category + line type, then compared to what was charged (5 cent tolerance for rounding).
- **Duplicates are layered**, strongest first: exact number, normalized number (`FA-001655` = `1655-A`), near match (amount within 1%, within 14 days, and invoice numbers ≥ 60% alike or the same service month named in the lines), same bank account under another vendor record, already paid by employee card. History and the current batch are both checked. A credit note is never matched against an invoice.
- **Recurring bills are not duplicates.** Fixed-monthly contract vendors (rent, SaaS) need similar invoice numbers too, otherwise every rent bill matches last month's.
- **One-off lines on a fixed-fee bill** (implementation, migration, setup, training…) are not compared to the monthly fee; they get their own `OVER_CONTRACT_RATE` warning with `kind: one_off`.
- **Split detection** looks for 2+ bills from one vendor and department within 3 days, each under the $10k limit, adding up to more than it. Duplicate pairs, bills on separate POs and fixed-monthly vendors (V037's rent) are skipped.
- **Approval chain**: role holder first, then walk up the org chart if they are the requester (P07, recorded in `escalated_from`), on leave (P08, recorded in `delegated_from`), terminated, already on another step, or (final step only) below the amount limit. If nobody is left, the step is `UNASSIGNED` for a manual decision.
- **Release**: needs full approval, no open `block` flags, not an approver of this bill (P11), and the right role for the amount (P09/P10).

## What it found in the history

- AP-00388 **paid two days after Cascadia's unverified bank change**; AP-00426 approved and next to be paid
- 4 bills **paid twice or more** ($16,813.66 extra: AP-00023/34, AP-00073/77, AP-00136/155, AP-00215/224 + card) and 1 set to be paid twice (AP-00394/407)
- 3 self-approvals (U010) and 2 PO overruns without the finance step (P12), from `approvals.csv`
- 3 wrong-tax invoices (AP-00098 no QST in QC, AP-00253 HST in Alberta, AP-00325 no HST in ON)
- V051 / V053 lookalike vendors sharing bank accounts with Polar Freight / Great Lakes; V053 is on hold but was paid twice
- Torque Industrial (V044): expired contract, no PO, 3 bills in one week totaling ~$14k (looks like a split)
- Redstone Cloud (V021) billing above its $4,800 USD contract fee most months

## Known gaps / next

- `can_release` checks the approver list; the backend must pass who **actually** acted, including delegates.
- A missing FX rate holds the bill (`CURRENCY_UNSUPPORTED`, block) and routing uses the face amount.
  Full list of fixes and open items: `docs/CONTROLS_HANDOFF.md`.
- Card duplicate check skips AP virtual card payments (they belong to other invoices). Employee card charges only.
- Signatures differ from the original stubs: functions take a `RefData` (from `load_refdata()`), not a `ReferenceRepository`.
- Run on the real incoming batch (all 56 files, `cd backend && python scripts/run_incoming.py`). Results, the
  check against HACKATHON_PLAN §4, false alarms and misses: "Incoming batch results" in `docs/CONTROLS_HANDOFF.md`.
