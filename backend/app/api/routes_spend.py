"""Spend analytics. Approvers see their own department only; back-office roles see everything."""
from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends

from app.api.common import READ_ERRORS
from app.api.errors import not_implemented
from app.api.schemas_api import SpendReport
from app.auth.deps import CurrentUser, require_role
from app.auth.roles import APPROVER, BACK_OFFICE_READ

router = APIRouter(tags=["spend"])


@router.get("/spend", response_model=SpendReport, responses=READ_ERRORS)
def spend(user: CurrentUser = Depends(require_role(APPROVER, *BACK_OFFICE_READ)),
          group_by: Literal["department", "vendor", "gl_account"] = "department",
          from_date: date | None = None, to_date: date | None = None, department_id: str | None = None):
    raise not_implemented("Spend report")
