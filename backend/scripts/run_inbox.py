"""
Process every email in the dataset inbox and write the results to backend/output/.

Owner: Person A.   Run from backend/:  python scripts/run_inbox.py [--emails PATH]

Writes:
  output/drafts/<email_id>__<file>.json   one per attachment: DraftBill, or a placeholder with
                                          status "llm_skipped"/"failed" and a text preview
  output/summary.json                     triage + per-file status for every email
Prints a table: email → class → attachments → status.

Works without an API key: classification and the text layer still run, and each
attachment gets an "LLM skipped" placeholder. Cached LLM results are used when present.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # works even before `pip install -e`

from app.config import get_settings  # noqa: E402
from app.intake.inbox import load_emails, process_inbox  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--emails", type=Path, default=None, help="emails.json (default: dataset inbox)")
    args = ap.parse_args()

    s = get_settings()
    out_dir = s.output_dir
    drafts_dir = out_dir / "drafts"
    drafts_dir.mkdir(parents=True, exist_ok=True)
    if not s.llm_enabled:
        print("ANTHROPIC_API_KEY not set: running classification + text layer only (cached LLM results are used).\n")

    emails = sorted(load_emails(args.emails), key=lambda e: e["email_id"])
    results = process_inbox(emails)

    summary, rows, statuses = [], [], Counter()
    for triage, outcomes in results:
        files = []
        for o in outcomes:
            statuses[o.status] += 1
            safe = re.sub(r"[^A-Za-z0-9._-]+", "_", o.file_name)
            (drafts_dir / f"{triage.email_id}__{safe}.json").write_text(
                json.dumps({"email_id": triage.email_id, **o.to_dict()}, indent=2, ensure_ascii=False),
                encoding="utf-8")
            d = o.draft
            files.append({"file_name": o.file_name, "status": o.status, "error": o.error,
                          "vendor_id": d.vendor.vendor_id if d else None,
                          "invoice_number": d.invoice_number if d else None,
                          "total": str(d.total) if d else None, "currency": d.currency if d else None,
                          "warnings": len(d.extraction_warnings) if d else len(o.warnings)})
        summary.append({"triage": triage.model_dump(mode="json"), "files": files})
        if not files:
            rows.append((triage.email_id, triage.email_class.value, "-", "no bill", "", "", triage.reason))
        for f in files:
            rows.append((triage.email_id, triage.email_class.value, f["file_name"], f["status"],
                         f["vendor_id"] or "", f"{f['total'] or ''} {f['currency'] or ''}".strip(),
                         f["error"] or ""))

    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    headers = ("email", "class", "attachment", "status", "vendor", "total", "note")
    widths = [min(max(len(str(r[i])) for r in [headers, *rows]), 40) for i in range(len(headers))]
    fmt = "  ".join(f"{{:<{w}.{w}}}" for w in widths)
    print(fmt.format(*headers))
    print(fmt.format(*("-" * w for w in widths)))
    for r in rows:
        print(fmt.format(*map(str, r)))

    classes = Counter(t.email_class.value for t, _ in results)
    print(f"\n{len(results)} emails: " + ", ".join(f"{k}={v}" for k, v in sorted(classes.items())))
    print(f"{sum(statuses.values())} attachments: " + ", ".join(f"{k}={v}" for k, v in sorted(statuses.items())))
    print(f"Output: {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
