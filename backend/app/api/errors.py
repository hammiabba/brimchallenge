"""
One error format for every response: {"error": {"code", "message", "details"}, "request_id"}.

Services raise ApiError with a stable dotted code ("auth.forbidden_role", "bill.not_found", "conflict.stale").
Framework errors (HTTPException from FastAPI or another router, validation errors, stale rows, constraint
violations, unexpected exceptions) are converted to the same shape here, so the frontend reads one structure.

Errors raised as HTTPException (the intake routes, FastAPI's own 404/405) also keep a top-level "detail" string,
which those routes' existing tests and callers read.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.middleware import get_request_id

log = logging.getLogger(__name__)


class ApiError(Exception):
    """An expected failure with an HTTP status, a stable code and a message safe to show the user."""

    def __init__(self, status: int, code: str, message: str, details: dict[str, Any] | None = None, *,
                 clear_session: bool = False, headers: dict[str, str] | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details
        self.clear_session = clear_session
        self.headers = headers


def not_found(what: str, ident: str) -> ApiError:
    """404 used both for rows that don't exist and for rows outside the caller's scope, so existence never leaks."""
    return ApiError(404, f"{what}.not_found", f"No {what.replace('_', ' ')} {ident}.")


def not_implemented(feature: str) -> ApiError:
    return ApiError(501, "not_implemented", f"{feature} is not implemented yet.")


def envelope(status: int, code: str, message: str, details: Any = None, *, extra: dict | None = None,
             headers: dict[str, str] | None = None) -> JSONResponse:
    body: dict[str, Any] = {"error": {"code": code, "message": message, "details": details},
                            "request_id": get_request_id()}
    if extra:
        body.update(extra)
    return JSONResponse(body, status_code=status, headers=headers)


def _clean_validation_errors(errors: list[dict]) -> list[dict]:
    # Drop the submitted values: they can hold bank numbers or document text, and the client already has them.
    return [{"loc": list(e.get("loc", ())), "msg": e.get("msg"), "type": e.get("type")} for e in errors]


def install_error_handlers(app: FastAPI) -> None:
    from app.auth.settings import get_auth_settings

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        response = envelope(exc.status, exc.code, exc.message, exc.details, headers=exc.headers)
        if exc.clear_session:
            response.delete_cookie(get_auth_settings().session_cookie_name, path="/")
        return response

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        message = exc.detail if isinstance(exc.detail, str) else "Request failed."
        return envelope(exc.status_code, f"http.{exc.status_code}", message, extra={"detail": exc.detail},
                        headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return envelope(422, "request.invalid", "Some fields are missing or invalid.",
                        _clean_validation_errors(exc.errors()))

    @app.exception_handler(StaleDataError)
    async def _stale(_: Request, exc: StaleDataError) -> JSONResponse:
        return envelope(409, "conflict.stale", "Someone else changed this record. Reload and try again.")

    @app.exception_handler(IntegrityError)
    async def _integrity(_: Request, exc: IntegrityError) -> JSONResponse:
        # Only the constraint name goes out (e.g. ck_payments_releaser_not_preparer), never the SQL or values.
        text = str(exc.orig) if exc.orig is not None else ""
        constraint = text.split(":")[-1].strip() if "constraint" in text.lower() else None
        return envelope(409, "conflict.constraint", "The change breaks a data rule.", {"constraint": constraint})

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error (request %s)", get_request_id())
        return envelope(500, "server.error", "Something went wrong. Quote the request id if you report it.")
