"""Runs every historical invoice through the controls engine and prints what it catches.

    python scripts/replay_history.py

Good for the demo ("our engine would have caught these 4 double payments")
and for spotting false positives when you change a rule.
"""
import sys
from collections import Counter
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.controls import bill_from_history, load_refdata, run_controls  # noqa: E402
from app.controls.refdata import d  # noqa: E402

ref = load_refdata()
counts = Counter()
print("Problems found in Jan-Oct 2026 history\n")

for iid, inv in ref.invoices.items():
    bill = bill_from_history(ref, iid)
    # The schema has no received date, so date checks use ref.as_of. Replay each bill as of the day it arrived.
    result = run_controls(bill, ref=replace(ref, as_of=d(inv["received_date"])))
    found = [f for f in result.flags if f.severity != "info"]
    if not found:
        continue
    print(f"{iid}  {ref.vendors[inv['vendor_id']]['legal_name'][:32]:32}  ${bill.total:>10,.2f}  [{inv['status']}]")
    for f in found:
        counts[f.code] += 1
        print(f"    {f.severity.value.upper():5} {f.code}: {f.message}")
    print()

print("Summary")
for code, n in counts.most_common():
    print(f"  {code:28} {n}")
