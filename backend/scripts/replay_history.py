"""Runs every historical invoice through the controls engine and prints what it catches.

    cd backend && python scripts/replay_history.py

Each bill is judged as of its own date (only earlier invoices, bank changes and user status changes count), so a
duplicate pair or split group is reported once, on its later bill. approvals.csv and payments.csv are checked too.
The logic lives in app/controls/history.py; this script only prints it.
"""
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.controls import load_refdata  # noqa: E402
from app.controls.history import replay  # noqa: E402
from app.shared.schemas import Severity  # noqa: E402


def money(x: Decimal) -> str:
    return f"${x:,.2f}"


def vendor_of(ref, ids: list[str]) -> str:
    inv = next((ref.invoices[i] for i in ids if i in ref.invoices), None)
    return ref.vendors.get(inv["vendor_id"], {}).get("legal_name", "?") if inv else "?"


def main() -> None:
    ref = load_refdata()
    r = replay(ref)
    by_kind: dict[str, list] = {}
    for f in r.findings:
        by_kind.setdefault(f.kind, []).append(f)
    confirmed = [g for g in r.doubles if g.confirmed]
    likely = [g for g in r.doubles if not g.confirmed]

    print(f"History replay: {len(ref.invoices)} invoices, each judged as of its own date\n")

    # ---- top findings ----
    print("TOP FINDINGS\n")
    n = 1
    for f in by_kind.get("paid_after_unverified_bank_change", []) + by_kind.get("due_after_unverified_bank_change", []):
        print(f"{n}. {f.message} {money(f.amount_cad)}.")
        n += 1
    print(f"\n{n}. Double payments, same invoice number (confirmed):")
    for g in confirmed:
        amount = money(g.extra_paid_cad) + " paid out extra" if g.paid >= 2 else money(g.at_risk_cad) + " at risk"
        print(f"     {' / '.join(g.ids):34} {vendor_of(ref, g.ids)[:30]:30} {g.status:22} {amount}")
    n += 1
    print(f"\n{n}. Likely double payments, AP payment + employee card charge (same vendor, amount, dates):")
    for g in likely:
        print(f"     {' / '.join(g.ids):34} {vendor_of(ref, g.ids)[:30]:30} {g.status:22} "
              f"{money(g.extra_paid_cad)} paid out extra")
    n += 1
    print(f"\n{n}. What the approval and payment records show:")
    for kind, title in (("self_approval", "Self-approved (P07)"),
                        ("po_over_balance_no_finance", "Over the PO, no finance manager step (P12)"),
                        ("approved_and_released", "Approved and released by the same person (P11)")):
        items = by_kind.get(kind, [])
        print(f"     {title}: {len(items) or 'none'}")
        for f in items:
            print(f"       - {f.message}")

    # ---- every flagged bill ----
    print("\n\nALL FLAGGED BILLS (warn and block)\n")
    for iid, res in r.results.items():
        found = [f for f in res.flags if f.severity != Severity.INFO]
        if not found:
            continue
        inv = ref.invoices[iid]
        print(f"{iid}  {ref.vendors[inv['vendor_id']]['legal_name'][:32]:32}  ${Decimal(inv['total']):>10,.2f}"
              f"  [{inv['status']}]")
        for f in found:
            print(f"    {f.severity.value.upper():5} {f.code}: {f.message}")
        print()

    # ---- summary ----
    paid_twice = [g for g in confirmed if g.paid >= 2]
    pending_twice = [g for g in confirmed if g.paid < 2]
    flagged = sum(1 for res in r.results.values() if any(f.severity != Severity.INFO for f in res.flags))
    print("SUMMARY (safe to quote: each bill, pair and group counted once)\n")
    print(f"  Invoices replayed                            {len(ref.invoices)}")
    print(f"  Bills with at least one warn/block flag       {flagged}")
    print(f"  Paid after an unverified bank change          {len(by_kind.get('paid_after_unverified_bank_change', []))}"
          f"  ({money(sum((f.amount_cad for f in by_kind.get('paid_after_unverified_bank_change', [])), Decimal(0)))})")
    print(f"  Approved/due after that change (hold now)     {len(by_kind.get('due_after_unverified_bank_change', []))}"
          f"  ({money(sum((f.amount_cad for f in by_kind.get('due_after_unverified_bank_change', [])), Decimal(0)))})")
    print(f"  Bills paid twice or more, confirmed           {len(paid_twice)}"
          f"  ({money(sum((g.extra_paid_cad for g in paid_twice), Decimal(0)))} paid out extra)")
    print(f"  Bills set to be paid twice, confirmed         {len(pending_twice)}"
          f"  ({money(sum((g.at_risk_cad for g in pending_twice), Decimal(0)))} at risk)")
    print(f"  Likely paid twice via employee card           {len(likely)}"
          f"  ({money(sum((g.extra_paid_cad for g in likely), Decimal(0)))} paid out extra)")
    print(f"  Self-approvals (P07)                          {len(by_kind.get('self_approval', []))}")
    print(f"  PO overruns without finance step (P12)        {len(by_kind.get('po_over_balance_no_finance', []))}")
    print(f"  Approved and released by one person (P11)     {len(by_kind.get('approved_and_released', []))}")
    print("\n  Bills per flag code:")
    for code, count in r.flag_counts().most_common():
        print(f"    {code:28} {count}")


if __name__ == "__main__":
    main()
