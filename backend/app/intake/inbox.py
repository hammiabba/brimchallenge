"""
Process a batch of inbound emails: classify each one, then extract every invoice attachment.

Owner: Person A.
Input: list of email dicts (inbox/emails.json format); attachments are read from
`attachments_dir` (defaults to DATASET_DIR/incoming_invoices).
Output: list of (EmailTriage, [ExtractionOutcome, ...]), one outcome per processed attachment.

Each attachment becomes its own DraftBill (EM-029 has two). The sender address is
copied into SourceInfo so controls can check lookalike domains.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from app.config import get_settings
from app.extraction.pipeline import ExtractionOutcome, extract_outcome
from app.intake.classifier import classify
from app.reference.repository import ReferenceRepository
from app.shared.schemas import EmailTriage


def load_emails(path: Path | None = None) -> list[dict]:
    path = path or get_settings().dataset_dir / "inbox" / "emails.json"
    return json.loads(Path(path).read_text(encoding="utf-8"))


def process_inbox(emails: list[dict], *, attachments_dir: Path | None = None,
                  repo: ReferenceRepository | None = None, client=None,
                  extractor: Callable[..., ExtractionOutcome] = extract_outcome,
                  ) -> list[tuple[EmailTriage, list[ExtractionOutcome]]]:
    folder = Path(attachments_dir or get_settings().dataset_dir / "incoming_invoices")
    results = []
    for email in emails:
        triage = classify(email, client=client)
        outcomes = []
        for name in triage.attachments_to_process:
            path = folder / name
            if not path.is_file():
                outcomes.append(ExtractionOutcome(name, "", "failed", error=f"attachment not found: {path}"))
                continue
            outcomes.append(extractor(path.read_bytes(), name, email_id=email["email_id"],
                                      sender=email.get("from_address"), repo=repo, client=client))
        results.append((triage, outcomes))
    return results
