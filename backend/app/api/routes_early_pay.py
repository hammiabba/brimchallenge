"""Early-payment discounts: the best pay date for every approved or scheduled bill, the money an early payment saves
under the vendor's terms ("2/10 net 30"), and the discounts the history took and missed. Same roles as the payments
list. Read-only: the logic is app.controls.early_pay."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.common import READ_ERRORS
from app.api.schemas_api import EarlyPayReport
from app.auth.deps import CurrentUser, require_role
from app.auth.roles import BACK_OFFICE_READ
from app.db.database import get_session
from app.services import early_pay

router = APIRouter(prefix="/early-pay", tags=["payments"])


@router.get("", response_model=EarlyPayReport, responses=READ_ERRORS)
def early_pay_report(user: CurrentUser = Depends(require_role(*BACK_OFFICE_READ)), include_pending: bool = False,
                     db: Session = Depends(get_session)):
    """include_pending=true adds bills not approved yet (needs_review, on_hold, pending_approval), to see what
    approving them in time would save."""
    return early_pay.early_pay_report(db, include_pending=include_pending)
