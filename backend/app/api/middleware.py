"""
ASGI middleware, written as plain ASGI classes so they wrap every route, including routers owned by other lanes.

- RequestIdMiddleware: one id per request (accepts a safe inbound X-Request-ID), echoed in the response header,
  in error bodies and in audit events (audit_events.request_id).
- BodySizeLimitMiddleware: refuses bodies over MAX_BODY_BYTES with 413, counting streamed bytes too, so an upload
  without a Content-Length can't get around it.
- OriginCheckMiddleware: CSRF guard. SameSite=Lax already keeps the cookie off cross-site requests, but every
  localhost port counts as the same site, so state-changing requests whose Origin isn't the frontend or the API
  itself are refused. Requests with no Origin (curl, server-to-server, tests) carry no browser cookie by accident
  and pass.
"""
from __future__ import annotations

import json
import re
import uuid
from contextvars import ContextVar
from urllib.parse import urlsplit

from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def get_request_id() -> str | None:
    return _request_id.get()


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers", []):
        if key == name:
            return value.decode("latin-1")
    return None


async def _send_error(send: Send, status: int, code: str, message: str) -> None:
    body = json.dumps({"error": {"code": code, "message": message, "details": None},
                       "request_id": get_request_id()}).encode()
    headers = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
    if rid := get_request_id():
        headers.append((b"x-request-id", rid.encode()))
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        inbound = _header(scope, b"x-request-id")
        rid = inbound if inbound and _SAFE_ID.match(inbound) else uuid.uuid4().hex
        token = _request_id.set(rid)
        scope.setdefault("state", {})["request_id"] = rid

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                message.setdefault("headers", [])
                message["headers"] = [*message["headers"], (b"x-request-id", rid.encode())]
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            _request_id.reset(token)


class PayloadTooLarge(StarletteHTTPException):
    def __init__(self, limit: int):
        super().__init__(413, f"Request body is larger than {limit // (1024 * 1024)} MB.")


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = _header(scope, b"content-length")
        if declared and declared.isdigit() and int(declared) > self.max_bytes:
            await _send_error(send, 413, "request.too_large",
                              f"Request body is larger than {self.max_bytes // (1024 * 1024)} MB.")
            return
        seen = 0

        async def counting_receive() -> Message:
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > self.max_bytes:
                    # An HTTPException subclass: FastAPI passes it through body parsing untouched, and the
                    # error handlers turn it into the standard 413 envelope.
                    raise PayloadTooLarge(self.max_bytes)
            return message

        await self.app(scope, counting_receive, send)


class OriginCheckMiddleware:
    def __init__(self, app: ASGIApp, allowed_origins: list[str]):
        self.app = app
        self.allowed = {o.rstrip("/").lower() for o in allowed_origins}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in UNSAFE_METHODS:
            await self.app(scope, receive, send)
            return
        origin = _header(scope, b"origin")
        if origin is None or self._allowed(origin, _header(scope, b"host")):
            await self.app(scope, receive, send)
            return
        await _send_error(send, 403, "auth.bad_origin", "Requests from this origin aren't allowed.")

    def _allowed(self, origin: str, host: str | None) -> bool:
        origin = origin.rstrip("/").lower()
        if origin in self.allowed:
            return True
        # Same-origin requests (e.g. the Swagger UI at /docs) send Origin equal to the API's own host.
        return bool(host) and urlsplit(origin).netloc == host.lower()
