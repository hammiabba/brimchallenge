"""Admin: approval policies, users and absences (controller_admin writes; auditor reads), plus self-service
delegation for approvers who are going to be away."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.common import READ_ERRORS, WRITE_ERRORS
from app.api.errors import not_implemented
from app.api.schemas_api import (
    AbsenceIn,
    AbsenceOut,
    DelegationIn,
    Me,
    PolicyOut,
    PolicyPatch,
    UserOut,
    UserPatch,
)
from app.auth.deps import CurrentUser, require_role
from app.auth.roles import AUDIT_READERS, CONTROLLER_ADMIN, SIGNERS
from app.db.database import get_session
from app.services import admin

router = APIRouter(tags=["admin"])


@router.put("/me/delegation", response_model=Me, responses=WRITE_ERRORS)
def set_my_delegation(body: DelegationIn, user: CurrentUser = Depends(require_role(*SIGNERS))):
    raise not_implemented("Delegation")


@router.get("/admin/policies", response_model=list[PolicyOut], responses=READ_ERRORS)
def list_policies(user: CurrentUser = Depends(require_role(*AUDIT_READERS)), db: Session = Depends(get_session)):
    return admin.policies(db)


@router.patch("/admin/policies/{rule_id}", response_model=PolicyOut, responses=WRITE_ERRORS)
def update_policy(rule_id: str, body: PolicyPatch, user: CurrentUser = Depends(require_role(CONTROLLER_ADMIN))):
    raise not_implemented("Policy edit")


@router.get("/admin/users", response_model=list[UserOut], responses=READ_ERRORS)
def list_users(user: CurrentUser = Depends(require_role(*AUDIT_READERS)), db: Session = Depends(get_session)):
    return admin.users(db)


@router.patch("/admin/users/{user_id}", response_model=UserOut, responses=WRITE_ERRORS)
def update_user(user_id: str, body: UserPatch, user: CurrentUser = Depends(require_role(CONTROLLER_ADMIN))):
    raise not_implemented("User edit")


@router.get("/admin/absences", response_model=list[AbsenceOut], responses=READ_ERRORS)
def list_absences(user: CurrentUser = Depends(require_role(*AUDIT_READERS)), db: Session = Depends(get_session)):
    return admin.absences(db)


@router.post("/admin/absences", response_model=AbsenceOut, status_code=201, responses=WRITE_ERRORS)
def create_absence(body: AbsenceIn, user: CurrentUser = Depends(require_role(CONTROLLER_ADMIN))):
    raise not_implemented("Absence create")
