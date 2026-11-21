# api/

**Owner:** API lane. Exception: `routes_intake.py` belongs to the intake lane.

Every router is a thin wrapper: check the role with `require_role`, call one function in `app/services`, return a
model from `schemas_api.py`. No business logic in routes.

## Files
| File | What |
|---|---|
| `schemas_api.py` | Request/response models (the frontend contract). `Money` serializes as `"742.30"`; `MoneyIn` accepts only strings. Request models forbid unknown fields. |
| `errors.py` | `ApiError` and the handlers that give every error the shape `{"error": {"code", "message", "details"}, "request_id"}`. HTTPException-based errors also keep a top-level `detail`. Stale rows → 409 `conflict.stale`; constraint violations → 409 `conflict.constraint`. |
| `middleware.py` | Request id (`X-Request-ID`), body size limit (413), origin check for writes (CSRF). |
| `common.py` | Documented error responses and pagination params. |
| `routes_*.py` | One router per area: auth, bills, intake jobs/submissions, payments, vendors, spend, admin, audit. |

## Status
Every endpoint is live. Writes run in one write session (`get_write_session`) with exactly one audit event through
`app/services/events.record`, then commit. Controls always run through `app/services/controls_runner.py`
(flush, RefData from the database with the bill's own `exclude_bill_id`, store the run).

- Bills: edit header and line coding (controls re-run), resolve/override flags (blocking overrides need finance),
  submit (refused with 409 while a blocking flag is open), void.
- Approvals: approve / reject via `controls.can_approve` on the stored route (delegation recorded as
  `on_behalf_of`, repeat signing refused), assign an UNASSIGNED step.
- Payments: schedule (vendor active, no pending bank change, records the bank account version), release with a
  required `Idempotency-Key` via `controls.can_release` (approvers from `approval_decisions`, only open stored
  flags; a bank change after scheduling blocks release), cancel.
- Intake: `POST /submissions` and `POST /intake/inbox/jobs` return 202 and work in a background task; poll
  `GET /submissions` or `GET /intake/inbox/jobs/{id}`. Results are real bills with a controls run.

- UI support: `allowed_actions` on bill and payment detail (computed by `app/services/actions.py` from the same
  checks the writes run, so a button marked allowed won't be refused); queue fields on bill summaries
  (`open_flags`, `top_flag_code`, `current_step`); approval and release limits on `/auth/me`; `/reference/flag-help`,
  `/reference/departments`, `/reference/gl-accounts`; `/intake/emails`; `duplicates` on the controls run. Every
  timestamp is ISO 8601 UTC with `Z`.

The permission matrix (`tests/api/matrix.py`) lists every endpoint x role.

## Adding an endpoint
1. Add the route with `Depends(require_role(...))` and typed request/response models.
2. Add a row to `tests/api/matrix.py`; `test_matrix_covers_every_operation` fails until you do.
3. Put the logic in `app/services/`, including the audit event for writes.

## Intake routes
`routes_intake.py` (intake lane) holds two reads, `GET /intake/emails/{email_id}` and `GET /intake/files/{file_hash}`,
each behind `require_role(*BACK_OFFICE_READ)` like `/intake/emails`. It is mounted without a router-wide guard. The
old in-memory `/intake/upload`, `/intake/inbox/run` and `/intake/drafts` are gone: use `POST /submissions` and the
inbox job. See `app/intake/README.md`.
