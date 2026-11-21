"""Shared bits for the routers: documented error responses and pagination parameters."""
from __future__ import annotations

from typing import Annotated

from fastapi import Query

from app.api.schemas_api import ErrorEnvelope

_E = {"model": ErrorEnvelope}
READ_ERRORS = {401: _E, 403: _E, 404: _E}
WRITE_ERRORS = {401: _E, 403: _E, 404: _E, 409: _E, 422: _E}

Limit = Annotated[int, Query(ge=1, le=200)]
Offset = Annotated[int, Query(ge=0)]
