"""Bank reconciliation: every bank statement line matched to its payment, and everything that doesn't match
explained (bank fees, unexplained debits, double payments, amount differences, payments not on the statement).
Controller and auditor only, like the audit log. Read-only: the logic is app.controls.reconciliation."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.common import READ_ERRORS
from app.api.schemas_api import BankReconciliation
from app.auth.deps import CurrentUser, require_role
from app.auth.roles import AUDIT_READERS
from app.db.database import get_session
from app.services import reconciliation

router = APIRouter(prefix="/reconciliation", tags=["reconciliation"])


@router.get("/bank", response_model=BankReconciliation, responses=READ_ERRORS)
def bank_reconciliation(user: CurrentUser = Depends(require_role(*AUDIT_READERS)), only_issues: bool = False,
                        db: Session = Depends(get_session)):
    """only_issues=true keeps just the lines and payments someone has to act on (severity "review")."""
    return reconciliation.bank_reconciliation(db, only_issues=only_issues)
