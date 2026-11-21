"""Extracts every incoming invoice and runs the controls on all of them as one batch.

    cd backend && python scripts/run_incoming.py [--out PATH]

1. Emails (dataset inbox) are triaged and each invoice attachment is extracted with the email's sender address
   (Person A's intake/extraction code, unchanged). Files in incoming_invoices/ that no email processed are
   extracted too, without a sender.
2. run_controls() runs on every readable bill with the whole batch, so duplicates and splits inside the batch
   are caught. Logic and report: app/controls/incoming.py.
3. Prints the report (problem bills first) and, with --out, also writes it to a file.

Needs ANTHROPIC_API_KEY in the repo-root .env for files that aren't in the extraction cache yet.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402
from app.controls.incoming import IncomingItem, render_report, run_batch  # noqa: E402
from app.extraction.pipeline import extract_outcome  # noqa: E402
from app.intake.inbox import load_emails, process_inbox  # noqa: E402


def item(outcome, email_id=None, email_class=None, sender=None) -> IncomingItem:
    return IncomingItem(file_name=outcome.file_name, status=outcome.status, bill=outcome.draft,
                        email_id=email_id, email_class=email_class, sender=sender, error=outcome.error)


def main() -> int:
    ap = argparse.ArgumentParser(description="Run the controls on the incoming batch.")
    ap.add_argument("--out", type=Path, default=None, help="also write the report to this file")
    args = ap.parse_args()

    s = get_settings()
    if not s.llm_enabled:
        print("ANTHROPIC_API_KEY not set: only cached extractions can be read.\n")

    emails = sorted(load_emails(), key=lambda e: e["email_id"])
    sender_of = {e["email_id"]: e.get("from_address") for e in emails}
    items, no_bill, seen = [], [], set()
    for triage, outcomes in process_inbox(emails):
        if not outcomes:
            no_bill.append((triage.email_id, triage.email_class.value, triage.reason))
        for o in outcomes:
            seen.add(o.file_name)
            items.append(item(o, triage.email_id, triage.email_class.value, sender_of.get(triage.email_id)))

    folder = s.dataset_dir / "incoming_invoices"
    for path in sorted(p for p in folder.iterdir() if p.is_file() and p.name not in seen):
        items.append(item(extract_outcome(path.read_bytes(), path.name)))

    report = render_report(run_batch(items), no_bill)
    print(report)
    if args.out:
        args.out.write_text(report + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
