"""Demo sign-in: pick a user, the server sets a signed session cookie. Identity never comes from a header or body
after this point; see app/auth/deps.py."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.common import READ_ERRORS
from app.api.errors import ApiError
from app.api.schemas_api import LoginIn, Me, PickerUser
from app.auth import session as signed_session
from app.auth.deps import CurrentUser, current_user, load_current_user
from app.auth.settings import get_auth_settings
from app.db import models
from app.db.audit import AuditAction
from app.db.database import get_session, get_write_session
from app.services import users
from app.services.events import record

router = APIRouter(prefix="/auth", tags=["auth"])


def me_out(db: Session, user: CurrentUser) -> Me:
    approval_limit, release_limit = users.limits(db, user)
    return Me(user_id=user.user_id, full_name=user.full_name, title=user.title, role=user.role,
              department_id=user.department_id, status=user.status, approval_limit_cad=approval_limit,
              release_limit_cad=release_limit,
              acting_for=[{"user_id": a.user_id, "full_name": a.full_name, "starts_on": a.starts_on,
                           "ends_on": a.ends_on} for a in user.acting_for])


@router.get("/users", response_model=list[PickerUser], summary="Users for the demo sign-in picker")
def picker_users(db: Session = Depends(get_session)) -> list[models.User]:
    """Active and on-leave users. Terminated users aren't listed and can't sign in."""
    return list(db.scalars(select(models.User).where(models.User.status != "terminated")
                           .order_by(models.User.user_id)))


@router.post("/login", response_model=Me, responses=READ_ERRORS)
def login(body: LoginIn, response: Response, db: Session = Depends(get_write_session)) -> Me:
    user = load_current_user(db, body.user_id)
    if user is None:
        raise ApiError(401, "auth.invalid_user", "This account can't sign in.")
    record(db, actor_user_id=user.user_id, actor_role=user.role, action=AuditAction.AUTH_LOGIN, entity_type="user",
           entity_id=user.user_id)
    db.commit()
    s = get_auth_settings()
    response.set_cookie(s.session_cookie_name, signed_session.issue(user.user_id), max_age=s.session_ttl_hours * 3600,
                        httponly=True, samesite="lax", secure=s.secure_cookie, path="/")
    return me_out(db, user)


@router.post("/logout", status_code=204, responses=READ_ERRORS)
def logout(response: Response, user: CurrentUser = Depends(current_user),
           db: Session = Depends(get_write_session)) -> Response:
    record(db, actor_user_id=user.user_id, actor_role=user.role, action=AuditAction.AUTH_LOGOUT, entity_type="user",
           entity_id=user.user_id)
    db.commit()
    response.status_code = 204
    response.delete_cookie(get_auth_settings().session_cookie_name, path="/")
    return response


@router.get("/me", response_model=Me, responses=READ_ERRORS)
def me(user: CurrentUser = Depends(current_user), db: Session = Depends(get_session)) -> Me:
    return me_out(db, user)
