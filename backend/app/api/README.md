# api/

**Owner:** DB team. Exception: `routes_intake.py` is Person A's.

Every router is a thin wrapper: parse the request, check the role, call a feature module, write an audit event, return a schema from `shared/schemas.py`. No business logic in routes.

## Current routes
| Method | Path | Owner | Notes |
|---|---|---|---|
| GET | `/health` | DB team | as-of date + whether the LLM is configured |
| POST | `/intake/upload` | A | multipart file → `DraftBill` (503 without API key, 422 if unreadable) |
| POST | `/intake/inbox/run` | A | runs the dataset inbox → triage + per-file status |
| GET | `/intake/drafts` | A | **TEMP** in-memory store until the DB exists |

## Role-dependency pattern (to implement in `auth/`)
Roles are enforced **server-side** on every route:

```python
from fastapi import Depends
from app.auth.deps import current_user, require_role   # DB team

@router.post("/invoices/{invoice_id}/approve")
def approve(invoice_id: str, user = Depends(require_role("approver", "finance_manager", "controller_admin"))):
    decision = controls.permissions.can_approve(user.user_id, ...)   # Person B, pure function
    if not decision.allowed:
        raise HTTPException(403, decision.reason)
    ...
    log_event(actor=user, action="invoice.approved", entity_type="invoice", entity_id=invoice_id, ...)
```

- `require_role(*roles)` raises 403 when the user's role isn't listed.
- Object-level rules (self-approval P07, approver ≠ releaser P11, limits) come from `controls.permissions`.
- Every state change writes an `AuditEvent` through one `log_event()` helper.

## To do for the DB team
- Replace `_DRAFTS` in `routes_intake.py` with persistence, and add `Depends(require_role("ap_clerk", ...))`.
- Run controls on each stored draft, then store the `ControlsResult`.
