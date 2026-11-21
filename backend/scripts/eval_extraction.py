"""
Measure extraction accuracy against hand-checked golden files.

Owner: Person A.   Run from backend/:  python scripts/eval_extraction.py [--only-verified]

For each tests/golden/*.json, runs the extraction pipeline on the referenced file
(cached LLM results are reused, so reruns are free), compares field by field and prints:
  - per-field accuracy across all golden files
  - every mismatch: file, field, expected, got
Golden files with "verified": false are included but marked with "*". Check them by
hand and set "verified": true.

Compared fields: vendor_id, invoice_number, invoice_date, due_date, currency, is_credit_note,
subtotal, each tax (by code), total, ship_to_province, po_number, line_count.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # works even before `pip install -e`

from app.config import get_settings  # noqa: E402
from app.extraction.pipeline import extract_outcome  # noqa: E402
from app.shared.schemas import DraftBill  # noqa: E402

GOLDEN_DIR = Path(__file__).resolve().parent.parent / "tests" / "golden"
SCALAR_FIELDS = ("vendor_id", "invoice_number", "invoice_date", "due_date", "currency", "is_credit_note",
                 "subtotal", "total", "ship_to_province", "po_number", "line_count")
MONEY_FIELDS = {"subtotal", "total"}


def actual_fields(d: DraftBill) -> dict:
    return {
        "vendor_id": d.vendor.vendor_id, "invoice_number": d.invoice_number,
        "invoice_date": d.invoice_date.isoformat(), "due_date": d.due_date.isoformat() if d.due_date else None,
        "currency": d.currency, "is_credit_note": d.is_credit_note, "subtotal": d.subtotal, "total": d.total,
        "ship_to_province": d.ship_to_province, "po_number": d.po_number, "line_count": len(d.lines),
        "taxes": {t.code.value: t.amount for t in d.taxes},
    }


def same(field: str, expected, got) -> bool:
    if field in MONEY_FIELDS or field.startswith("tax:"):
        return expected is not None and got is not None and Decimal(str(expected)) == Decimal(str(got))
    return expected == got


def compare(expected: dict, d: DraftBill) -> list[tuple[str, object, object, bool]]:
    """Returns (field, expected, got, ok) for every compared field."""
    act = actual_fields(d)
    results = [(f, expected.get(f), act[f], same(f, expected.get(f), act[f])) for f in SCALAR_FIELDS]
    exp_taxes = {t["code"]: t["amount"] for t in expected.get("taxes", [])}
    for code in sorted(set(exp_taxes) | set(act["taxes"])):
        e, g = exp_taxes.get(code), act["taxes"].get(code)
        results.append((f"tax:{code}", e, g, same(f"tax:{code}", e, g)))
    return results


def main() -> int:
    ap = argparse.ArgumentParser(description="Per-field extraction accuracy vs golden files")
    ap.add_argument("--only-verified", action="store_true", help="skip golden files not yet checked by hand")
    args = ap.parse_args()

    incoming = get_settings().dataset_dir / "incoming_invoices"
    per_field: dict[str, list[bool]] = defaultdict(list)
    mismatches, skipped = [], []

    for path in sorted(GOLDEN_DIR.glob("*.json")):
        g = json.loads(path.read_text(encoding="utf-8"))
        if args.only_verified and not g.get("verified"):
            continue
        mark = "" if g.get("verified") else "*"
        data = (incoming / g["file"]).read_bytes()
        out = extract_outcome(data, g["file"], email_id=g.get("email_id"), sender=g.get("sender"))
        if out.draft is None:
            skipped.append((g["file"] + mark, out.status, out.error))
            continue
        for field, exp, got, ok in compare(g["expected"], out.draft):
            per_field["tax" if field.startswith("tax:") else field].append(ok)
            if not ok:
                mismatches.append((g["file"] + mark, field, exp, got))

    if per_field:
        print(f"{'field':<18} {'accuracy':>9}   n")
        for field, oks in per_field.items():
            print(f"{field:<18} {sum(oks) / len(oks):>8.0%}  {len(oks):>2}")
        total = [ok for oks in per_field.values() for ok in oks]
        print(f"{'OVERALL':<18} {sum(total) / len(total):>8.0%}  {len(total):>2}")

    if mismatches:
        print("\nMismatches (* = golden not yet verified by hand):")
        for file, field, exp, got in mismatches:
            print(f"  {file:<36} {field:<18} expected={exp!s:<14} got={got}")
    if skipped:
        print("\nNot evaluated:")
        for file, status, err in skipped:
            print(f"  {file:<36} {status}: {err}")
    if not per_field:
        print("\nNothing evaluated. Set ANTHROPIC_API_KEY (or populate the cache) and rerun.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
