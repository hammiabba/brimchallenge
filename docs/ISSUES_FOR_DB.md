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
| 2 | `feat(api): call learn_from_line from code_line` | `app/services/bills.py` | `code_line` calls `app.coding.feedback.learn_from_line(bill, line)` after the coding is set. | An accepted or overridden coding feeds the next suggestion for that vendor (feature 3: "the system learns from corrections"). In memory only; see "Open points". | `tests/api/test_clerk_loop.py::test_override_feeds_the_next_bill_from_the_same_vendor` |
| 3 | `feat(api): call requester_problem from update_header` | `app/services/bills.py` | After your reference checks, `update_header` calls `app.coding.requester.requester_problem(db, requester_user_id)` and raises `ApiError(422, "bill.requester_not_allowed", ...)` when it returns a message. | A terminated user (U015) can't be made the requester of a new bill. `on_leave` users are allowed. | `tests/api/test_clerk_loop.py::test_terminated_requester_is_refused` |
| 4 | `feat(api): call recode_for_requester from update_header` | `app/services/bills.py` | After the fields are set, `update_header` calls `app.coding.requester.recode_for_requester(db, bill, changes)`. | Setting the requester re-runs the department override: lines still on our suggestion (`coding_status == "suggested"`) take the requester's department; clerk-coded lines are untouched. | `tests/api/test_clerk_loop.py::test_setting_the_requester_moves_suggested_departments` |
| 5 | `feat(api): call recheck_bill from update_header` | `app/services/bills.py` | Just before `controls_runner.rerun`, `update_header` calls `app.extraction.recheck.recheck_bill(db, bill, changes)`. | Edits re-run the self-check, so confidence and warnings stay truthful: a field the clerk set gets confidence 1.0 and loses its extraction warnings (e.g. an ambiguous date); arithmetic warnings are recomputed. Runs before controls so `LOW_EXTRACTION_CONFIDENCE` sees the new values. | `tests/api/test_clerk_loop.py::test_editing_a_field_rechecks_its_confidence_and_warnings` |

## New test files in `tests/api/`

They use your fixtures (`act_as`, `fresh_db`, `factories.draft`), so they have to live next to them.

| File | What it covers |
|---|---|
| `tests/api/test_intake_received.py` | Same file twice → same bill, one audit event; different file → new bill; voided bill doesn't block a resend. |
| `tests/api/test_clerk_loop.py` | Override → next bill's suggestion cites it; requester change moves suggested departments (and doesn't stack reasons); U015 refused with 422; editing a date rechecks its confidence and warning. |
| `tests/api/test_flags_end_to_end.py` | The whole inbox through `POST /intake/inbox/jobs` with the model replayed from `tests/fixtures/raw`: every §4 trap raises its flag, 18 clean invoices have no `block` flag. One run per module; reuses `_client_on`, `_copy`, `_engine_on` from your conftest. |
| `tests/api/test_intake_end_to_end.py` | A real PDF through `POST /submissions` → real pipeline (model output faked) → bill → controls flags (`VENDOR_LOOKALIKE` on HA26-2766); an unreadable file becomes a clean failed item. |

## Open points for you to decide

1. **`draft_json` is no longer strictly frozen after an edit** (hook 5). `load_draft_bill` reads
   `field_confidence` and `extraction_warnings` from `draft_json`, so `recheck_bill` updates those two keys there.
   The values as extracted are preserved once, under `draft_json["as_extracted"]`; nothing else in the snapshot
   changes. If you'd rather keep `draft_json` frozen, a small `review_state` JSON column read by
   `load_draft_bill` would do the same job; `recheck()` itself is pure and returns the two values.
2. **Learned codings are in memory** (hook 2). They're also on `bill_lines` (`coding_status` accepted/overridden),
   so a start-up step could replay them with `app.coding.history_index.learn(Correction(...))`. Not done yet.
