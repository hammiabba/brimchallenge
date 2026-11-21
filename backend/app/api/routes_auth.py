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
from app.db.database import get_session

router = APIRouter(prefix="/auth", tags=["auth"])


def me_out(user: CurrentUser) -> Me:
    return Me(user_id=user.user_id, full_name=user.full_name, title=user.title, role=user.role,
              department_id=user.department_id, status=user.status,
              acting_for=[{"user_id": a.user_id, "full_name": a.full_name, "starts_on": a.starts_on,
                           "ends_on": a.ends_on} for a in user.acting_for])


@router.get("/users", response_model=list[PickerUser], summary="Users for the demo sign-in picker")
def picker_users(db: Session = Depends(get_session)) -> list[models.User]:
    """Active and on-leave users. Terminated users aren't listed and can't sign in."""
    return list(db.scalars(select(models.User).where(models.User.status != "terminated")
                           .order_by(models.User.user_id)))


@router.post("/login", response_model=Me, responses=READ_ERRORS)
def login(body: LoginIn, response: Response, db: Session = Depends(get_session)) -> Me:
    user = load_current_user(db, body.user_id)
    if user is None:
        raise ApiError(401, "auth.invalid_user", "This account can't sign in.")
    s = get_auth_settings()
    response.set_cookie(s.session_cookie_name, signed_session.issue(user.user_id), max_age=s.session_ttl_hours * 3600,
                        httponly=True, samesite="lax", secure=s.secure_cookie, path="/")
    return me_out(user)


@router.post("/logout", status_code=204, responses=READ_ERRORS)
def logout(response: Response, _: CurrentUser = Depends(current_user)) -> Response:
    response.status_code = 204
    response.delete_cookie(get_auth_settings().session_cookie_name, path="/")
    return response


@router.get("/me", response_model=Me, responses=READ_ERRORS)
def me(user: CurrentUser = Depends(current_user)) -> Me:
    return me_out(user)
