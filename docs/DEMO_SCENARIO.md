# Demo scenario

`backend/scripts/demo_scenario.py` puts the database into a state worth demoing:
- bills waiting in every approver's queue
- the Cascadia bank-change hold
- a delegated approval
- payments ready to release

It goes through the same services the API uses (intake, bills, approvals, payments), so every step passes the real
checks and writes a real audit event. Nothing is written to the database directly.

## Run it

From `backend/`, with the venv active and `AUDIT_HMAC_KEY` set (in `.env`):

```bash
python -m app.db.seed --reset           # fresh database from the dataset
python -m app.db.backfill               # one controls run per history bill
python scripts/demo_scenario.py         # the demo state
uvicorn app.main:app --reload           # then sign in as the users below
```

Every command takes `--database-url sqlite:////path/to/ap.db` to use another database. The script refuses a database
that isn't seeded.

**Running it again is safe.** Each demo bill has a fixed file hash, and intake links a file it has already seen to
the bill it made. Each step looks at the bill first and does only what's missing. A second run prints
`0 step(s) done (already set up).` and writes no bills, payments, decisions or audit events. If a run stops halfway,
the next run picks up where it stopped. To start over, rerun the seed with `--reset`, then the back-fill and the
script.

## What it sets up

On a freshly seeded database, the bills are AP-00427 to AP-00438 and the payments PAY-00416 to PAY-00418. The script
prints the ids. All invoices are dated 2026-10-30, and "today" is the as-of date, 2026-11-02.

| Bill | Vendor, department | Amount before tax | State | Who sees it |
|---|---|---|---|---|
| AP-00427 | V001 Polar Freight, D01 | $2,840.00 | Waiting, step 1 | U007 Dev Malhotra |
| AP-00428 | V029 Orion Strategy, D02 | $3,150.00 | Waiting, step 1 | U008 Chloe Bergeron |
| AP-00429 | V032 Northstar Media, D03 | $4,200.00 | Waiting, step 1 | U009 Tomas Alvarez |
| AP-00430 | V028 Ledgerline CPA, D04 | $2,600.00 | Waiting, step 1 | U002 Marcus Webb (D04's manager) |
| AP-00431 | V023 Fibrewave, D05 | $1,180.00 | Waiting, step 1, with an `OVER_CONTRACT_RATE` warning (a one-off install fee) | U010 Wen Zhao |
| AP-00432 | V048 Talentbridge, D06 | $6,500.00 | Waiting, step 1 | U011 Grace Mbeki |
| AP-00433 | V040 Lakeshore Hydro, D07 | $1,860.00 | Waiting, step 1, **delegated**: U012 is on leave, so it goes to their delegate (P08) | U003 Elise Tremblay, acting for U012 |
| AP-00434 | V002 Great Lakes, D01 | $11,800.00 | U007 approved step 1. **Waiting at step 2** for the finance manager (over $10,000, P02) | U003 Elise Tremblay |
| AP-00435 | V004 Cascadia, D01 | $3,480.00 | **Held**: `BANK_CHANGE_UNVERIFIED` (block). Submit is refused | AP clerk U004 |
| AP-00436 | V040 Lakeshore Hydro, D07 | $1,420.00 | **Approved by U003 acting for U012** (`on_behalf_of=U012`), then scheduled as PAY-00416 | Release: U002 only |
| AP-00437 | V030 Brightmore, D02 | $3,900.00 | Approved by U008, scheduled as PAY-00417 | Release: U003 or U002 |
| AP-00438 | V024 Paper Trail, D06 | $640.00 | Approved by U011, scheduled as PAY-00418 | Release: U003 or U002 |

All three payments were prepared by AP clerk U004, who can't release them.

**The Cascadia hold, from the seed.** Bank change BC-009 for V004 came in by email on 2026-10-27 and was never
verified by callback, so it's `pending_verification`. Because of that:
- the new Cascadia bill AP-00435 has an open block flag, and submitting it is refused (`bill.blocked`);
- history bill AP-00426 is approved but can't be scheduled (`payment.bank_change_pending`).

The script prints both checks at the end.

## A walk-through

1. **U004 (AP clerk).** Open AP-00435 from the review queue and show the Cascadia flag: the account changed by email,
   with no callback. **Submit for approval** is disabled and lists the blocking flag. The flag has **Resolve**, and
   instead of Override a note says only a finance manager or the controller can override a blocking flag. Then open
   **Payments**: under "Approved, not scheduled", AP-00426 has no Schedule button and shows the reason instead,
   "Bank change BC-009 for this vendor isn't verified yet." (The API refuses both too: `bill.blocked`,
   `payment.bank_change_pending`.)
2. **U007, U008, U009, U010, U011, U002.** Each one's approval queue has one bill.
3. **U003 (finance manager).** The banner shows U003 acting for U012. The queue has AP-00433 (as U012's delegate) and
   AP-00434 (step 2). The audit trail of AP-00436 shows U003's approval recorded on behalf of U012.
4. **U003 on Payments.** PAY-00416 has no Release button: it shows "U003 approved this bill, so they can't release
   its payment (P11)." PAY-00417 and PAY-00418 have **Release**. (A release sent through the API anyway is refused
   with the same message.)
5. **U002 (controller).** Releases PAY-00416.
6. **U006 (auditor).** The audit log shows every step above, with the actor, the role and `on_behalf_of`, and
   **Export CSV** downloads it. The log is a hash chain (each event signs the one before it with `AUDIT_HMAC_KEY`).
   The UI doesn't show the check; run it from `backend/`:
   `python -c "from sqlalchemy.orm import Session; from app.db.database import make_engine; from app.db.audit import verify_chain; print(verify_chain(Session(make_engine())))"`
   prints `ChainReport(ok=True, ...)` with the number of events checked.

## Notes

- **No extraction step.** The invoices are typed in as extracted data, so no file is read and no LLM is called. From
  there, everything is the normal intake path: the upload is recorded, the bill is created, controls run and
  `bill.created` is logged.
- **Invoice numbers DM-1001 to DM-1012.** Duplicate detection compares invoice numbers by their digits, so each demo
  bill has its own digits.
- **Test:** `tests/api/test_demo_scenario.py` runs the script twice on a fresh seeded, back-filled database. It checks:
  - the queues
  - the delegated decision
  - who may release which payment
  - the Cascadia hold
  - the audit chain
  - that the second run changes nothing
