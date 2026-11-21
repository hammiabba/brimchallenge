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
All endpoints exist with typed models so `/openapi.json` is complete.

- **Live:** auth; bill list and detail (scoped); approval queue; submissions list; intake items; payments list,
  dashboard and detail; vendors list and detail; bank changes list; spend; admin reads; audit list, entity history,
  CSV export.
- **Live writes:** vendor onboarding, approval and hold; bank change request, verification and rejection;
  self-service delegation; admin edits to users, policies and absences. Each runs in one write session
  (`get_write_session`) with exactly one audit event through `app/services/events.record`, then commits.
- **501 until DB-backed RefData lands:** bill edits, flags, submit, approve/reject, payments and the inbox job
  (they call controls, which must read the database, not the dataset CSVs).

The permission matrix (`tests/api/matrix.py`) lists every endpoint x role.

## Adding an endpoint
1. Add the route with `Depends(require_role(...))` and typed request/response models.
2. Add a row to `tests/api/matrix.py`; `test_matrix_covers_every_operation` fails until you do.
3. Put the logic in `app/services/`, including the audit event for writes.

## Intake routes
The intake router is mounted in `app/main.py` behind `require_role("ap_clerk", "finance_manager", "controller_admin")`,
so `routes_intake.py` itself is unchanged. Employees submit through `POST /submissions` instead.
