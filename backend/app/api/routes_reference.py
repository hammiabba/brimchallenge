"""Reference data for forms and help text: flag explanations, departments, GL accounts. Any signed-in user."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.common import READ_ERRORS
from app.api.schemas_api import DepartmentOut, FlagHelpOut, GlAccountOut
from app.auth.deps import CurrentUser, require_role
from app.auth.roles import ALL_ROLES
from app.controls.flag_help import help_for
from app.db import models
from app.db.database import get_session
from app.shared.schemas import FLAG_CODES

router = APIRouter(prefix="/reference", tags=["reference"])


@router.get("/flag-help", response_model=dict[str, FlagHelpOut], responses=READ_ERRORS)
def flag_help(user: CurrentUser = Depends(require_role(*ALL_ROLES))):
    """Title, one-sentence help and severity for every flag code (from controls.flag_help)."""
    return {code: FlagHelpOut(**{k: v for k, v in help_for(code).items() if k != "code"}) for code in FLAG_CODES}


@router.get("/departments", response_model=list[DepartmentOut], responses=READ_ERRORS)
def departments(user: CurrentUser = Depends(require_role(*ALL_ROLES)), db: Session = Depends(get_session)):
    return list(db.scalars(select(models.Department).order_by(models.Department.department_id)))


@router.get("/gl-accounts", response_model=list[GlAccountOut], responses=READ_ERRORS)
def gl_accounts(user: CurrentUser = Depends(require_role(*ALL_ROLES)), db: Session = Depends(get_session)):
    return list(db.scalars(select(models.GlAccount).order_by(models.GlAccount.account_number)))
