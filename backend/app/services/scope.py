"""
Object-level read scope: the one place that decides which bills a user may see.

- employee: bills of their own department (the brief: they must not see other departments' invoices)
- approver: bills of their own department, plus any bill where they hold an approval route step (this covers a
  delegate who signs for an absent manager, and escalations past a self-approval)
- ap_clerk, finance_manager, controller_admin, auditor: every bill

A bill outside the caller's scope is reported as not found (404), exactly like a bill that doesn't exist, so the
API never confirms that it exists.
"""
from __future__ import annotations

from sqlalchemy import Select, exists, or_, select
from sqlalchemy.orm import Session

from app.api.errors import not_found
from app.auth.deps import CurrentUser
from app.auth.roles import APPROVER, EMPLOYEE, SEE_ALL
from app.db import models


def bill_scope_clause(user: CurrentUser):
    """A WHERE clause limiting `models.Bill` to what `user` may see, or None for roles that see everything."""
    if user.role in SEE_ALL:
        return None
    in_department = models.Bill.department_id == user.department_id
    if user.role == EMPLOYEE:
        return in_department
    if user.role == APPROVER:
        on_route = exists().where(models.ApprovalRouteStep.bill_id == models.Bill.bill_id,
                                  models.ApprovalRouteStep.user_id == user.user_id)
        return or_(in_department, on_route)
    # Unknown role: see nothing. require_role normally stops these earlier.
    return models.Bill.bill_id.is_(None)


def visible_bills(user: CurrentUser) -> Select:
    stmt = select(models.Bill)
    clause = bill_scope_clause(user)
    return stmt if clause is None else stmt.where(clause)


def get_bill_for(db: Session, user: CurrentUser, bill_id: str) -> models.Bill:
    """The bill if `user` may see it; otherwise 404 (same response as a bill that doesn't exist)."""
    bill = db.scalars(visible_bills(user).where(models.Bill.bill_id == bill_id)).first()
    if bill is None:
        raise not_found("bill", bill_id)
    return bill
