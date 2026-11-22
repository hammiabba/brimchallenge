"""Demo sign-in: pick a user, the server sets a signed session cookie. Identity never comes from a header or body
after this point; see app/auth/deps.py."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response
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
def picker_users(db: Session = Depends(get_session)) -> list[PickerUser]:
    """Active and on-leave users, each with their department's name. Terminated users aren't listed and can't sign
    in."""
    # An outer join, so a user whose department row is missing is still listed, with department_name null.
    rows = db.execute(select(models.User, models.Department.name)
                      .outerjoin(models.Department, models.Department.department_id == models.User.department_id)
                      .where(models.User.status != "terminated")
                      .order_by(models.User.user_id))
    return [PickerUser.model_validate(user).model_copy(update={"department_name": name}) for user, name in rows]


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


@router.get("/me", response_model=Me,
            responses={**READ_ERRORS, 204: {"description": "No valid session (only with `optional=true`)."}})
def me(request: Request, db: Session = Depends(get_session),
       optional: bool = Query(False, description="Answer 204 instead of 401 when no one is signed in, so a "
                                                 "signed-out visit isn't reported as an error.")) -> Me | Response:
    """The signed-in user. Without a valid session this is a 401, as on every other route; with `optional=true` it
    is a 204 with no body instead (and a bad or expired cookie is still cleared)."""
    if not optional:
        return me_out(db, current_user(request, db))
    try:
        user = current_user(request, db)
    except ApiError as error:
        if error.status != 401:
            raise
        # Signed out is the expected answer here, not a failure: no body, and the stale cookie (if any) removed.
        response = Response(status_code=204)
        if error.clear_session:
            response.delete_cookie(get_auth_settings().session_cookie_name, path="/")
        return response
    return me_out(db, user)
