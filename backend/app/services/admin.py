"""Admin: approval policies, users and absences (reads and writes), and absences set by approvers themselves.

Policy and user edits change the database; controls see them once they read RefData from the database
(refdata_from_db), instead of the dataset CSVs."""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import schemas_api as s
from app.api.errors import ApiError, not_found
from app.auth.deps import CurrentUser
from app.auth.roles import SIGNERS
from app.config import get_settings
from app.controls.refdata import parse_threshold
from app.db import models
from app.db.audit import AuditAction
from app.db.types import utcnow
from app.services import views
from app.services.events import record
from app.services.money import money_to_cents


def policies(db: Session) -> list[models.Policy]:
    return list(db.scalars(select(models.Policy).order_by(models.Policy.rule_id)))


def users(db: Session) -> list[s.UserOut]:
    return [views.user_out(u) for u in db.scalars(select(models.User).order_by(models.User.user_id))]


def absences(db: Session) -> list[models.UserAbsence]:
    return list(db.scalars(select(models.UserAbsence).order_by(models.UserAbsence.starts_on.desc())))


# ---------------------------------------------------------------- writes


def _user(db: Session, user_id: str) -> models.User:
    u = db.get(models.User, user_id)
    if u is None:
        raise not_found("user", user_id)
    return u


def set_absence(db: Session, actor: CurrentUser, *, user_id: str, delegate_user_id: str, starts_on: date,
                ends_on: date | None) -> models.UserAbsence:
    """Record an absence with a named delegate (P08). If it covers the as-of date, the user is marked on_leave with
    that delegate right away, which is what approval routing reads; a future absence is stored for later."""
    if ends_on is not None and ends_on < starts_on:
        raise ApiError(422, "absence.bad_range", "The absence can't end before it starts.")
    if delegate_user_id == user_id:
        raise ApiError(422, "absence.self_delegate", "Pick someone else as the delegate.")
    user, delegate = _user(db, user_id), _user(db, delegate_user_id)
    if user.role not in SIGNERS:
        raise ApiError(422, "absence.not_an_approver", f"{user_id} doesn't approve bills, so needs no delegate.")
    if delegate.status != "active" or delegate.role not in SIGNERS:
        raise ApiError(422, "absence.bad_delegate", f"{delegate_user_id} must be an active approver, finance manager "
                       "or controller.")
    absence = models.UserAbsence(user_id=user_id, delegate_user_id=delegate_user_id, starts_on=starts_on,
                                 ends_on=ends_on)
    db.add(absence)
    before = {"status": user.status, "delegate_user_id": user.delegate_user_id}
    as_of = get_settings().as_of_date
    if starts_on <= as_of and (ends_on is None or ends_on >= as_of):
        user.status, user.status_since, user.delegate_user_id = "on_leave", starts_on, delegate_user_id
    db.flush()
    record(db, actor_user_id=actor.user_id, actor_role=actor.role, action=AuditAction.ABSENCE_CREATED,
           entity_type="user", entity_id=user_id, before=before,
           after={"absence_id": absence.id, "delegate_user_id": delegate_user_id, "starts_on": starts_on,
                  "ends_on": ends_on, "status": user.status})
    return absence


def update_user(db: Session, actor: CurrentUser, user_id: str, patch: s.UserPatch) -> s.UserOut:
    changes = patch.model_dump(exclude_unset=True)
    if not changes:
        raise ApiError(422, "request.empty", "Nothing to change.")
    if user_id == actor.user_id and ({"role", "status"} & changes.keys()):
        raise ApiError(403, "user.self_lockout", "You can't change your own role or status. Ask another admin.")
    u = _user(db, user_id)
    for ref_field, model in (("department_id", models.Department), ("manager_id", models.User),
                             ("delegate_user_id", models.User)):
        value = changes.get(ref_field)
        if value is not None and db.get(model, value) is None:
            raise ApiError(422, f"user.unknown_{ref_field}", f"{value} doesn't exist.")
    if changes.get("manager_id") == user_id or changes.get("delegate_user_id") == user_id:
        raise ApiError(422, "user.self_reference", "A user can't be their own manager or delegate.")
    before = {k: getattr(u, k if k != "approval_limit_cad" else "approval_limit_cad_cents") for k in changes}
    if "approval_limit_cad" in changes:
        u.approval_limit_cad_cents = money_to_cents(changes.pop("approval_limit_cad"), "approval_limit_cad")
    if "status" in changes and changes["status"] != u.status:
        u.status_since = get_settings().as_of_date
    for key, value in changes.items():
        setattr(u, key, value)
    db.flush()
    record(db, actor_user_id=actor.user_id, actor_role=actor.role, action=AuditAction.USER_UPDATED,
           entity_type="user", entity_id=user_id, before=before,
           after=patch.model_dump(exclude_unset=True))
    return views.user_out(u)


def update_policy(db: Session, actor: CurrentUser, rule_id: str, patch: s.PolicyPatch) -> models.Policy:
    """Edit a rule's text. A rule whose condition carries an amount ("over $10,000 CAD") must keep one, because
    controls read the threshold out of that text."""
    changes = patch.model_dump(exclude_unset=True)
    if not changes:
        raise ApiError(422, "request.empty", "Nothing to change.")
    p = db.get(models.Policy, rule_id)
    if p is None:
        raise not_found("policy", rule_id)
    if "condition" in changes and parse_threshold(p.condition) is not None:
        new_threshold = parse_threshold(changes["condition"])
        if new_threshold is None or new_threshold <= 0:
            raise ApiError(422, "policy.threshold_required",
                           'This rule needs an amount in its condition, e.g. "Invoice total over $10,000 CAD".')
    before = {k: getattr(p, k) for k in changes}
    for key, value in changes.items():
        setattr(p, key, value)
    p.updated_at, p.updated_by = utcnow(), actor.user_id
    db.flush()
    record(db, actor_user_id=actor.user_id, actor_role=actor.role, action=AuditAction.POLICY_UPDATED,
           entity_type="policy", entity_id=rule_id, before=before, after=changes)
    return p
