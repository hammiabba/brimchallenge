# Changes in DB/API files, for review by the DB/API lane

Person A's logic lives in `intake/`, `extraction/`, `coding/` and `reference/`. Where your services need to call
it, Person A added a single call site in your file, each in its own commit titled
`feat(api): call <function> from <service>`, with no other change to your code. Every file Person A touched outside
those folders is listed here. Revert or move any of them as you see fit; the tests named below show the behaviour
each hook exists for.

## Hooks in your services

| # | Commit | File | Change | Why | Tests |
|---|---|---|---|---|---|
| 1 | `feat(api): call link_to_existing_bill from store_outcome` | `app/services/intake.py` | `store_outcome` first calls `app.intake.received.link_to_existing_bill(db, item, out, started_by)`. If it returns a bill id, the item is linked to that bill (with an `already_received` warning and one `intake.already_received` audit event) and no bill is created; `else:` became `elif bill_id is None:` so the failure event isn't also written. | Idempotent intake: the exact same file (same sha256) submitted twice, or attached to two emails, points at the existing bill instead of making a second one. Voided bills don't count, so a misread bill can be voided and the file resent. | `tests/api/test_intake_received.py` |

## New test files in `tests/api/`

They use your fixtures (`act_as`, `fresh_db`, `factories.draft`), so they have to live next to them.

| File | What it covers |
|---|---|
| `tests/api/test_intake_received.py` | Same file twice → same bill, one audit event; different file → new bill; voided bill doesn't block a resend. |
