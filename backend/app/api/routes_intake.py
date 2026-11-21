"""
Intake endpoints: thin HTTP wrappers around intake/ and extraction/.

Owner: Person A. All other routes belong to the DB team (see api/README.md).

TEMP: drafts are kept in an in-memory dict until the DB exists. They're lost on restart
and not shared between workers. The DB team replaces `_DRAFTS` with a repository call,
and adds role dependencies (ap_clerk for upload/run, AP roles for reading).
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.extraction.llm_parser import LLMUnavailableError
from app.extraction.pipeline import ExtractionIncomplete
from app.intake.inbox import load_emails, process_inbox
from app.intake.upload import ALLOWED_EXTS, process_upload
from app.shared.schemas import DraftBill

router = APIRouter(prefix="/intake", tags=["intake"])

# TEMP (until DB): file_hash -> DraftBill
_DRAFTS: dict[str, DraftBill] = {}


@router.post("/upload", response_model=DraftBill)
def upload(file: UploadFile = File(...)) -> DraftBill:
    name = file.filename or "upload"
    if Path(name).suffix.lower() not in ALLOWED_EXTS:
        raise HTTPException(415, f"Unsupported file type; allowed: {', '.join(sorted(ALLOWED_EXTS))}")
    try:
        draft = process_upload(file.file.read(), name)
    except LLMUnavailableError as exc:
        raise HTTPException(503, str(exc)) from exc
    except ExtractionIncomplete as exc:
        raise HTTPException(422, str(exc)) from exc
    _DRAFTS[draft.source.file_hash] = draft
    return draft


@router.post("/inbox/run")
def run_inbox() -> list[dict]:
    """Process the dataset inbox. Returns one entry per email with its triage and per-file status."""
    summary = []
    for triage, outcomes in process_inbox(load_emails()):
        for o in outcomes:
            if o.draft:
                _DRAFTS[o.file_hash] = o.draft
        summary.append({
            "triage": triage.model_dump(mode="json"),
            "files": [{"file_name": o.file_name, "file_hash": o.file_hash, "status": o.status, "error": o.error}
                      for o in outcomes],
        })
    return summary


@router.get("/drafts", response_model=list[DraftBill])
def list_drafts() -> list[DraftBill]:
    return list(_DRAFTS.values())
