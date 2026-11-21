"""Incoming-batch logic on hand-built bills (no extraction, no network)."""
from decimal import Decimal as D

from app.controls.incoming import IncomingItem, render_report, run_batch, summary, top_findings, with_department
from app.shared.schemas import CodingSuggestion


def item(bill, name, email_id="EM-X", sender=None):
    return IncomingItem(file_name=name, status="ok", bill=bill, email_id=email_id, sender=sender)


def coded(bill, *depts):
    for line, dept in zip(bill.lines, depts, strict=False):
        line.coding = CodingSuggestion(gl_account="5010", department_id=dept, confidence=0.9, reason="test")
    bill.department_id = None
    return bill


# ---- department ----
def test_department_from_coding_when_invoice_has_none(make_bill):
    bill, source = with_department(coded(make_bill(dept="D07"), "D07"))
    assert bill.department_id == "D07" and source == "coding"


def test_invoice_department_wins(make_bill):
    bill, source = with_department(make_bill(dept="D01"))
    assert bill.department_id == "D01" and source == "invoice"


def test_no_department_anywhere(make_bill):
    bill = make_bill()
    bill.department_id = None
    assert with_department(bill) == (bill, None)


def test_routing_uses_the_suggested_department(ref, make_bill):
    [it] = run_batch([item(coded(make_bill(), "D07"), "a.pdf")], ref)
    assert it.department_source == "coding" and it.result.route[0].delegated_from == "U012"  # D07 manager on leave


# ---- one batch ----
def test_duplicate_inside_the_batch_is_caught(ref, make_bill):
    a = make_bill(number="IN-500", file_hash="h-a")
    b = make_bill(number="IN-500", file_hash="h-b")
    items = run_batch([item(a, "a.pdf", "EM-1"), item(b, "b.pdf", "EM-2")], ref)
    assert all(it.level == "hold" and "DUPLICATE_EXACT" in {f.code for f in it.result.flags} for it in items)
    assert any("Duplicates inside this batch: 2" in line for line in top_findings(items))


def test_split_inside_the_batch_is_caught(ref, make_bill):
    bills = [make_bill(vendor_id="V003", amount="4000.00", number=f"PX-{n}", file_hash=f"px{n}") for n in range(3)]
    items = run_batch([item(b, f"px{n}.pdf") for n, b in enumerate(bills)], ref)
    assert all("POSSIBLE_SPLIT" in {f.code for f in it.result.flags} for it in items)


# ---- ordering and levels ----
def test_problem_bills_come_first(ref, make_bill):
    clean = make_bill(number="OK-101", file_hash="ok")
    warn = make_bill(number="W-202", amount="2000.00", file_hash="w")
    warn.subtotal += D("10")  # SUBTOTAL_MISMATCH (warn)
    hold = make_bill(vendor_id="V004", province="BC", number="H-303", file_hash="h")  # unverified bank change
    failed = IncomingItem(file_name="bad.pdf", status="failed", error="no invoice number")
    items = run_batch([item(clean, "ok.pdf"), item(warn, "w.pdf"), item(hold, "h.pdf"), failed], ref)
    assert [(it.file_name, it.level) for it in items] == [
        ("bad.pdf", "unreadable"), ("h.pdf", "hold"), ("w.pdf", "review"), ("ok.pdf", "ok")]


def test_top_findings_lead_with_unreadable_then_blocks(ref, make_bill):
    hold = make_bill(vendor_id="V004", province="BC", file_hash="h")
    items = run_batch([item(hold, "h.pdf"), IncomingItem(file_name="bad.pdf", status="failed", error="x")], ref)
    top = top_findings(items)
    assert top[0].startswith("1 file(s) could not be read") and "bad.pdf" in top[0]
    assert top[1].startswith("BANK_CHANGE_UNVERIFIED: 1 bill(s): h.pdf")


# ---- report ----
def test_credit_note_is_not_routed_for_payment(ref, make_bill):
    credit = make_bill(amount="-500.00", file_hash="cn")
    credit.is_credit_note = True
    report = render_report(run_batch([item(credit, "cn.pdf")], ref))
    assert "CREDIT NOTE" in report and "route    none: credit note" in report


def test_report_sections_in_order(ref, make_bill):
    hold = make_bill(vendor_id="V004", province="BC", file_hash="h")
    clean = make_bill(number="OK-101", file_hash="ok")
    items = run_batch([item(clean, "ok.pdf"), item(hold, "h.pdf")], ref)
    report = render_report(items, [("EM-059", "not_ap", "Marketing")])
    order = [report.index(s) for s in ("TOP FINDINGS", "HOLD", "CAN PROCEED", "EMAILS WITH NO BILL", "SUMMARY")]
    assert order == sorted(order)
    assert report.index("h.pdf  [") < report.index("ok.pdf  [")


def test_summary_counts(ref, make_bill):
    usd = make_bill(currency="USD", vendor_id="V021", number="U-1", file_hash="u", description="Cloud hosting")
    unknown = make_bill(number="Z-1", file_hash="z")
    unknown.vendor.vendor_id = None
    items = run_batch([item(usd, "u.pdf"), item(unknown, "z.pdf"),
                       IncomingItem(file_name="bad.pdf", status="failed")], ref)
    s = summary(items)
    assert (s["files"], s["readable"], s["foreign_currency"], s["unknown_vendor"]) == (3, 2, 1, 1)
    assert s["levels"]["unreadable"] == 1 and s["levels"]["hold"] == 1  # unknown vendor blocks
