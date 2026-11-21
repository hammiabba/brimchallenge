"""User facts the UI shows next to the signed-in user: approval and release limits."""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import CurrentUser
from app.auth.roles import CONTROLLER_ADMIN, FINANCE_MANAGER
from app.controls.refdata import parse_threshold
from app.db import models
from app.services.money import cents


def limits(db: Session, user: CurrentUser) -> tuple[Decimal | None, Decimal | None]:
    """(approval limit, release limit) in CAD. Release: the P09 threshold for a finance manager (read from the
    policies table, so admin edits show up), None (no limit) for the controller, 0 for everyone else."""
    row = db.get(models.User, user.user_id)
    approval = cents(row.approval_limit_cad_cents) if row else None
    if user.role == CONTROLLER_ADMIN:
        return approval, None
    if user.role == FINANCE_MANAGER:
        policy = db.scalars(select(models.Policy).where(models.Policy.rule_type == "payment_release",
                                                        models.Policy.required == "finance_manager")).first()
        threshold = parse_threshold(policy.condition) if policy else None
        return approval, (threshold.quantize(Decimal("0.01")) if threshold is not None else Decimal("0.00"))
    return approval, Decimal("0.00")
