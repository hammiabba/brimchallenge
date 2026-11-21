"""
FastAPI dependencies for identity and role checks. This is the only place identity is established.

- current_user: identity comes only from the signed session cookie, never from a header or the request body.
  The user row is loaded on every request; unknown or terminated users get 401.
- require_role(*roles): the single role gate. 403 when the caller's role isn't listed. Routes never inspect the
  role themselves; object-level rules (department scope, P07, P11, limits) live in app/services and controls.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from fastapi import Depends, Request
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.errors import ApiError
from app.auth import session as signed_session
from app.auth.roles import ALL_ROLES
from app.auth.settings import get_auth_settings
from app.config import get_settings
from app.db import models
from app.db.database import get_session


@dataclass(frozen=True)
class ActingFor:
    """An absent user whose work the current user may do as their named delegate (P08)."""

    user_id: str
    full_name: str
    starts_on: date
    ends_on: date | None


@dataclass(frozen=True)
class CurrentUser:
    user_id: str
    full_name: str
    title: str
    role: str
    department_id: str
    status: str
    acting_for: tuple[ActingFor, ...] = ()

    @property
    def acting_for_ids(self) -> frozenset[str]:
        return frozenset(a.user_id for a in self.acting_for)


def active_delegations(db: Session, user_id: str, as_of: date | None = None) -> tuple[ActingFor, ...]:
    """Absences (user_absences) where `user_id` is the named delegate and the as-of date falls in the range."""
    as_of = as_of or get_settings().as_of_date
    rows = db.execute(
        select(models.UserAbsence, models.User.full_name)
        .join(models.User, models.User.user_id == models.UserAbsence.user_id)
        .where(models.UserAbsence.delegate_user_id == user_id,
               models.UserAbsence.starts_on <= as_of,
               or_(models.UserAbsence.ends_on.is_(None), models.UserAbsence.ends_on >= as_of))
        .order_by(models.UserAbsence.starts_on)
    ).all()
    return tuple(ActingFor(a.user_id, name, a.starts_on, a.ends_on) for a, name in rows)


def load_current_user(db: Session, user_id: str) -> CurrentUser | None:
    """The user as the API sees them, or None if they don't exist or are terminated."""
    user = db.get(models.User, user_id)
    if user is None or user.status == "terminated":
        return None
    return CurrentUser(user_id=user.user_id, full_name=user.full_name, title=user.title, role=user.role,
                       department_id=user.department_id, status=user.status,
                       acting_for=active_delegations(db, user.user_id))


def current_user(request: Request, db: Session = Depends(get_session)) -> CurrentUser:
    token = request.cookies.get(get_auth_settings().session_cookie_name)
    if not token:
        raise ApiError(401, "auth.required", "Sign in to continue.")
    session = signed_session.verify(token)
    if session is None:
        raise ApiError(401, "auth.invalid_session", "Your session is invalid or has expired. Sign in again.",
                       clear_session=True)
    user = load_current_user(db, session.user_id)
    if user is None:
        raise ApiError(401, "auth.inactive_user", "This account can't sign in.", clear_session=True)
    request.state.user = user
    return user


def require_role(*roles: str) -> Callable[..., CurrentUser]:
    """Dependency factory: the current user, or 403 if their role isn't one of `roles`."""
    unknown = set(roles) - set(ALL_ROLES)
    if unknown or not roles:
        raise ValueError(f"require_role needs known roles, got {roles!r}")
    allowed = frozenset(roles)

    def _check(user: CurrentUser = Depends(current_user)) -> CurrentUser:
        if user.role not in allowed:
            raise ApiError(403, "auth.forbidden_role", f"Your role ({user.role}) can't do this.")
        return user

    _check.allowed_roles = allowed  # read by the route-coverage test
    return _check
