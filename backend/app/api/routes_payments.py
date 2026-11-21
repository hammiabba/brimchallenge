"""Payments: list, dashboard, audit-ready detail, schedule, release (idempotent), cancel."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy.orm import Session

from app.api.common import READ_ERRORS, WRITE_ERRORS, Limit, Offset
from app.api.schemas_api import (
    CommentIn,
    Page,
    PaymentDashboard,
    PaymentDetail,
    PaymentStatus,
    PaymentSummary,
    ScheduleIn,
)
from app.auth.deps import CurrentUser, require_role
from app.auth.roles import AP_CLERK, BACK_OFFICE_READ, CONTROLLER_ADMIN, FINANCE_MANAGER, RELEASERS
from app.db.database import get_session, get_write_session
from app.services import payments

router = APIRouter(tags=["payments"])

IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128,
                                       pattern=r"^[A-Za-z0-9._:-]+$")]


@router.get("/payments", response_model=Page[PaymentSummary], responses=READ_ERRORS)
def list_payments(user: CurrentUser = Depends(require_role(*BACK_OFFICE_READ)),
                  status: Annotated[list[PaymentStatus] | None, Query()] = None, vendor_id: str | None = None,
                  limit: Limit = 50, offset: Offset = 0, db: Session = Depends(get_session)):
    return payments.list_payments(db, status=status, vendor_id=vendor_id, limit=limit, offset=offset)


@router.get("/payments/summary", response_model=PaymentDashboard, responses=READ_ERRORS)
def payment_dashboard(user: CurrentUser = Depends(require_role(*BACK_OFFICE_READ)),
                      db: Session = Depends(get_session)):
    return payments.dashboard(db)


@router.get("/payments/{payment_id}", response_model=PaymentDetail, responses=READ_ERRORS)
def get_payment(payment_id: str, user: CurrentUser = Depends(require_role(*BACK_OFFICE_READ)),
                db: Session = Depends(get_session)):
    return payments.payment_detail(db, user.role, payment_id)


@router.post("/bills/{bill_id}/payments", response_model=PaymentDetail, status_code=201, responses=WRITE_ERRORS)
def schedule_payment(bill_id: str, body: ScheduleIn, user: CurrentUser = Depends(require_role(AP_CLERK)),
                     db: Session = Depends(get_write_session)):
    payment_id = payments.schedule(db, user, bill_id, body)
    db.commit()
    return payments.payment_detail(db, user.role, payment_id)


@router.post("/payments/{payment_id}/release", response_model=PaymentDetail, responses=WRITE_ERRORS)
def release_payment(payment_id: str, idempotency_key: IdempotencyKey, response: Response,
                    user: CurrentUser = Depends(require_role(*RELEASERS)), db: Session = Depends(get_write_session)):
    """Release a scheduled payment. Send a unique Idempotency-Key per release attempt; retrying with the same key
    returns the same result (header Idempotent-Replayed: true) and never pays twice."""
    _, replayed = payments.release(db, user, payment_id, idempotency_key)
    db.commit()
    if replayed:
        response.headers["Idempotent-Replayed"] = "true"
    return payments.payment_detail(db, user.role, payment_id)


@router.post("/payments/{payment_id}/cancel", response_model=PaymentDetail, responses=WRITE_ERRORS)
def cancel_payment(payment_id: str, body: CommentIn,
                   user: CurrentUser = Depends(require_role(AP_CLERK, FINANCE_MANAGER, CONTROLLER_ADMIN)),
                   db: Session = Depends(get_write_session)):
    payments.cancel(db, user, payment_id, body.comment)
    db.commit()
    return payments.payment_detail(db, user.role, payment_id)
