"""
FastAPI entry point. Run from `backend/`: `uvicorn app.main:app --reload`.

Owner: DB team. Each feature mounts its own router here; keep this file to
wiring only, no logic.
"""
from fastapi import FastAPI

from app.api.routes_intake import router as intake_router
from app.config import get_settings

app = FastAPI(title="Brim AP", version="0.1.0")
app.include_router(intake_router)


@app.get("/health")
def health() -> dict:
    s = get_settings()
    return {"status": "ok", "as_of_date": s.as_of_date.isoformat(), "llm_enabled": s.llm_enabled}
