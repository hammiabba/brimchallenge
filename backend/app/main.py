"""
FastAPI entry point. Run from `backend/`: `uvicorn app.main:app --reload`.

Owner: API lane. Wiring only, no logic: middleware, error handlers and routers.

Middleware, outermost first: request id -> CORS -> origin check (CSRF) -> body size limit -> routes.
"""
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    routes_admin,
    routes_audit,
    routes_auth,
    routes_bills,
    routes_intake_jobs,
    routes_payments,
    routes_reference,
    routes_spend,
    routes_vendors,
)
from app.api.errors import install_error_handlers
from app.api.middleware import BodySizeLimitMiddleware, OriginCheckMiddleware, RequestIdMiddleware
from app.api.routes_intake import router as intake_router
from app.auth.deps import require_role
from app.auth.roles import AP_CLERK, CONTROLLER_ADMIN, FINANCE_MANAGER
from app.auth.settings import get_auth_settings
from app.config import get_settings

auth_settings = get_auth_settings()

app = FastAPI(title="Brim AP", version="0.1.0")

# add_middleware wraps the app, so the last one added runs first.
app.add_middleware(BodySizeLimitMiddleware, max_bytes=auth_settings.max_body_bytes)
app.add_middleware(OriginCheckMiddleware, allowed_origins=auth_settings.origins)
app.add_middleware(
    CORSMiddleware,
    allow_origins=auth_settings.origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "Idempotency-Key", "X-Request-ID"],
    expose_headers=["X-Request-ID"],
)
app.add_middleware(RequestIdMiddleware)

install_error_handlers(app)

# The intake router belongs to the intake lane; its role guard is applied here so that file stays untouched.
app.include_router(intake_router, dependencies=[Depends(require_role(AP_CLERK, FINANCE_MANAGER, CONTROLLER_ADMIN))])
app.include_router(routes_auth.router)
app.include_router(routes_bills.router)
app.include_router(routes_intake_jobs.router)
app.include_router(routes_payments.router)
app.include_router(routes_vendors.router)
app.include_router(routes_spend.router)
app.include_router(routes_admin.router)
app.include_router(routes_audit.router)
app.include_router(routes_reference.router)


@app.get("/health")
def health() -> dict:
    s = get_settings()
    return {"status": "ok", "as_of_date": s.as_of_date.isoformat(), "llm_enabled": s.llm_enabled}
