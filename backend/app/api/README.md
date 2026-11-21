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
All endpoints exist with typed models so `/openapi.json` is complete. Auth endpoints are live; the rest return
**501** until their service lands. The permission matrix (`tests/api/matrix.py`) lists every endpoint × role.

## Adding an endpoint
1. Add the route with `Depends(require_role(...))` and typed request/response models.
2. Add a row to `tests/api/matrix.py`; `test_matrix_covers_every_operation` fails until you do.
3. Put the logic in `app/services/`, including the audit event for writes.

## Intake routes
The intake router is mounted in `app/main.py` behind `require_role("ap_clerk", "finance_manager", "controller_admin")`,
so `routes_intake.py` itself is unchanged. Employees submit through `POST /submissions` instead.
