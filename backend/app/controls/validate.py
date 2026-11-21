"""validate(bill, ref) -> list[Flag]

Every check is a small function: bill + reference data in, flags out.
validate() just runs them all. Nothing here writes to a database.

Flags only use codes and severities from schemas.FLAG_CODES; flag() enforces that.
"""
from __future__ import annotations

import re
from datetime import timedelta
from decimal import Decimal

from app.shared.schemas import FLAG_CODES, DraftBill, Flag, Severity

from .refdata import RefData, bill_id, d, is_credit, money, tax_amounts, vendor_id

TOL = Decimal("0.02")        # rounding tolerance per amount (2 cents)
TAX_TOL = Decimal("0.05")    # tax is rounded per line on some invoices, allow 5 cents
STALE_DAYS = 180


def flag(code: str, message: str, *, evidence: dict | None = None, field: str | None = None,
         policy: str | None = None) -> Flag:
    """The only way checks create flags. Severity comes from FLAG_CODES; an unknown code raises KeyError."""
    ev = dict(evidence or {})
    if policy:
        ev["policy"] = policy
    return Flag(code=code, severity=Severity(FLAG_CODES[code]), message=message, evidence=ev, field=field)


def _amt(x: Decimal) -> str:
    return f"${x:,.2f}"


# ---------------------------------------------------------------------------
# FX
# ---------------------------------------------------------------------------
def to_cad(bill: DraftBill, ref: RefData) -> tuple[Decimal, Decimal]:
    """Returns (total_cad, rate). CAD bills use rate 1."""
    if bill.currency == "CAD":
        return bill.total, Decimal("1")
    rate = ref.fx_rate(bill.invoice_date) if bill.invoice_date else None
    if rate is None:
        rate = ref.fx_rate(ref.as_of) or Decimal("1")
    return (bill.total * rate).quantize(Decimal("0.01")), rate


def check_fx(bill: DraftBill, ref: RefData) -> list[Flag]:
    if bill.currency == "CAD":
        return []
    cad, rate = to_cad(bill, ref)
    ev = {"currency": bill.currency, "rate": str(rate), "total_cad": str(cad)}
    if bill.currency != "USD":
        msg = (f"Currency {bill.currency} has no FX rates on file, so the CAD amount ({_amt(cad)}) is not reliable. "
               f"Convert it manually before approving.")
    elif ref.fx_rate(bill.invoice_date) is None:
        msg = f"No USD/CAD rate for {bill.invoice_date}; used the latest rate {rate} = CAD {_amt(cad)}."
    else:
        msg = f"USD {_amt(bill.total)} converted at {rate} = CAD {_amt(cad)} (rate of {bill.invoice_date})."
    return [flag("FOREIGN_CURRENCY", msg, evidence=ev, field="currency")]


# ---------------------------------------------------------------------------
# Vendor
# ---------------------------------------------------------------------------
def _norm_name(s: str) -> str:
    s = s.lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    junk = {"ltd", "limited", "inc", "incorporated", "llp", "co", "corp", "and", "the", "llc"}
    return " ".join(w for w in s.split() if w not in junk)


def _norm_tax_no(s: str | None) -> str:
    # OCR often reads 1 as ! or I and 0 as O, so fold those before comparing.
    s = (s or "").upper().replace(" ", "").replace("!", "1").replace("I", "1").replace("O", "0")
    return s


def lookalike_vendors(ref: RefData, vid: str) -> list[tuple[str, str]]:
    """Other vendor records that look like the same company: same normalized name or same bank account."""
    v = ref.vendors[vid]
    out = []
    for other in ref.vendors.values():
        if other["vendor_id"] == vid:
            continue
        if _norm_name(other["legal_name"]) == _norm_name(v["legal_name"]):
            out.append((other["vendor_id"], "same name once 'Ltd/Inc/&' are ignored"))
        elif v["bank_account"] and (other["bank_transit"], other["bank_account"]) == (v["bank_transit"], v["bank_account"]):
            out.append((other["vendor_id"], "same bank transit and account"))
    return out


def _invoice_count(ref: RefData, vid: str) -> int:
    return sum(1 for i in ref.invoices.values() if i["vendor_id"] == vid)


def check_vendor(bill: DraftBill, ref: RefData) -> list[Flag]:
    vid = vendor_id(bill)
    if not vid or vid not in ref.vendors:
        return [flag("VENDOR_NOT_FOUND",
                     f"'{bill.vendor.name_on_invoice}' is not in the vendor master. "
                     f"Onboard and approve the vendor before paying.",
                     policy="P05", field="vendor")]
    v = ref.vendors[vid]
    flags: list[Flag] = []

    # pending_review has no flag code; routing adds the P05 finance step instead.
    if v["status"] not in ("active", "pending_review"):
        flags.append(flag("VENDOR_NOT_ACTIVE", f"{v['legal_name']} is '{v['status']}' in the vendor master.",
                          field="vendor"))

    # GST number on the invoice vs master
    if bill.vendor.gst_number and v["gst_hst_number"]:
        if _norm_tax_no(bill.vendor.gst_number) != _norm_tax_no(v["gst_hst_number"]):
            flags.append(flag("GST_NUMBER_MISMATCH",
                              f"GST/HST number on invoice ({bill.vendor.gst_number}) does not match the master "
                              f"({v['gst_hst_number']}).",
                              evidence={"invoice": bill.vendor.gst_number, "master": v["gst_hst_number"]},
                              field="vendor.gst_number"))

    # Bank details on the invoice vs master
    bank = bill.vendor.bank
    if bank.account:
        inv_bank = (bank.institution or "", bank.transit or "", bank.account or "")
        master_bank = (v["bank_institution"], v["bank_transit"], v["bank_account"])
        if [x.lstrip("0") for x in inv_bank] != [x.lstrip("0") for x in master_bank]:
            flags.append(flag("BANK_DETAILS_MISMATCH",
                              "Bank details on the invoice differ from the vendor master. Treat as possible fraud: "
                              "verify by calling the vendor on a known number before any change.",
                              evidence={"invoice": "-".join(inv_bank), "master": "-".join(master_bank)},
                              field="vendor.bank"))

    # Most recent bank change in the history
    changes = sorted((c for c in ref.bank_changes if c["vendor_id"] == vid), key=lambda c: c["changed_at"])
    if changes and changes[-1]["verified_by_callback"] != "yes":
        last = changes[-1]
        flags.append(flag("BANK_CHANGE_UNVERIFIED",
                          f"Bank account changed on {last['changed_at']} via {last['request_channel']} "
                          f"(…{last['old_account_last4']} → …{last['new_account_last4']}) and was never verified by callback.",
                          evidence=last, field="vendor.bank"))

    # Lookalike records: only flag the bill when it sits on the suspicious copy, never on the real vendor.
    # Suspicious = fewer past invoices than the record it resembles, or not active (on hold, pending review).
    n_this = _invoice_count(ref, vid)
    for other_id, why in lookalike_vendors(ref, vid):
        if n_this < _invoice_count(ref, other_id) or v["status"] != "active":
            o = ref.vendors[other_id]
            ev = {"similar_vendor": other_id, "why": why, "this_status": v["status"],
                  "this_invoices": n_this, "similar_invoices": _invoice_count(ref, other_id)}
            if bill.source.sender_address:
                ev["sender_domain"] = bill.source.sender_address.split("@")[-1].lower()
                ev["known_domain"] = o["ap_contact_email"].split("@")[-1].lower()
            flags.append(flag("VENDOR_LOOKALIKE",
                              f"This bill is on {vid} {v['legal_name']}, which looks like existing vendor "
                              f"{other_id} {o['legal_name']} ({why}). Verify by phone before approving.",
                              evidence=ev, field="vendor"))
    return flags


# ---------------------------------------------------------------------------
# Tax
# ---------------------------------------------------------------------------
def expected_tax_codes(province: str, vendor: dict, line_type: str) -> tuple[str | None, str | None]:
    """(federal code, provincial code) that SHOULD apply. Place of supply = ship_to_province."""
    if vendor.get("country") and vendor["country"] != "CA":
        return "FOREIGN", None
    if vendor.get("category") == "Insurance":
        return "EXEMPT", None
    if province == "ON":
        return "HST13", None
    if province == "QC":
        return "GST5", "QST9975"
    if province == "BC":
        return "GST5", ("PST7_BC" if line_type == "goods" else None)
    if province in ("AB", "SK", "MB", "YT", "NT", "NU"):
        return "GST5", None
    return None, None  # NS/NB/NL/PE use HST rates we don't have codes for


def check_tax(bill: DraftBill, ref: RefData) -> list[Flag]:
    vid = vendor_id(bill)
    # No ship-to province / unsupported province: no flag code for "can't check", so nothing is raised.
    if not vid or vid not in ref.vendors or not bill.ship_to_province:
        return []
    v = ref.vendors[vid]
    rate = lambda code: Decimal(ref.tax_codes[code]["rate"]) if code else Decimal("0")

    exp_fed = exp_prov = Decimal("0")
    exp_codes: set[str] = set()
    for line in bill.lines:
        fed, prov = expected_tax_codes(bill.ship_to_province, v, line.line_type)
        if fed is None:
            return []
        exp_fed += line.amount * rate(fed)
        exp_prov += line.amount * rate(prov)
        exp_codes |= {c for c in (fed, prov) if c and rate(c)}
    exp_fed = exp_fed.quantize(Decimal("0.01"))
    exp_prov = exp_prov.quantize(Decimal("0.01"))

    fed_chg, prov_chg = tax_amounts(bill)
    charged_codes = {t.code.value for t in bill.taxes if t.amount}
    amounts_ok = abs(fed_chg - exp_fed) <= TAX_TOL and abs(prov_chg - exp_prov) <= TAX_TOL
    if amounts_ok and charged_codes <= exp_codes:
        return []

    where = bill.ship_to_province
    ev = {"ship_to": where, "expected_codes": sorted(exp_codes), "charged_codes": sorted(charged_codes),
          "expected_gst_hst": str(exp_fed), "expected_pst_qst": str(exp_prov),
          "charged_gst_hst": str(fed_chg), "charged_pst_qst": str(prov_chg)}
    charged = f"GST/HST {_amt(fed_chg)} + PST/QST {_amt(prov_chg)}"
    should = f"{_amt(exp_fed)} + {_amt(exp_prov)}"
    missing = [name for name, exp, chg in (("GST/HST", exp_fed, fed_chg), ("PST/QST", exp_prov, prov_chg))
               if abs(exp) > TAX_TOL and chg == 0]
    if missing:
        return [flag("TAX_MISSING",
                     f"No {' or '.join(missing)} charged. Delivery to {where} should carry {should}; "
                     f"invoice has {charged}. Ask the vendor for a corrected invoice.",
                     evidence=ev, field="taxes")]
    if where == "BC" and "PST7_BC" in charged_codes and prov_chg > exp_prov + TAX_TOL:
        return [flag("PST_ON_SERVICES",
                     f"BC PST charged on services: invoice has PST {_amt(prov_chg)}, but PST only applies to goods "
                     f"({_amt(exp_prov)}). Ask the vendor for a corrected invoice.",
                     evidence=ev, field="taxes")]
    return [flag("TAX_WRONG_FOR_PROVINCE",
                 f"Tax charged is {charged}, but delivery to {where} should be {should} "
                 f"({', '.join(sorted(exp_codes)) or 'no Canadian tax'}). Ask the vendor for a corrected invoice.",
                 evidence=ev, field="taxes")]


# ---------------------------------------------------------------------------
# Arithmetic
# ---------------------------------------------------------------------------
def check_arithmetic(bill: DraftBill, ref: RefData) -> list[Flag]:
    flags = []
    for l in bill.lines:
        if abs(l.quantity * l.unit_price - l.amount) > TOL:
            flags.append(flag("LINE_MATH_ERROR",
                              f"Line {l.line_no}: {l.quantity} × {_amt(l.unit_price)} = {_amt(l.quantity * l.unit_price)}, "
                              f"not {_amt(l.amount)}.", evidence={"line": l.line_no}, field="lines"))
    if bill.lines:
        s = sum((l.amount for l in bill.lines), Decimal("0"))
        if abs(s - bill.subtotal) > TOL:
            flags.append(flag("SUBTOTAL_MISMATCH",
                              f"Lines add up to {_amt(s)} but the subtotal says {_amt(bill.subtotal)}.",
                              evidence={"lines_sum": str(s), "subtotal": str(bill.subtotal)}, field="subtotal"))
    taxes = sum((t.amount for t in bill.taxes), Decimal("0"))
    t = bill.subtotal + taxes
    if abs(t - bill.total) > TOL:
        flags.append(flag("TOTAL_MISMATCH",
                          f"Subtotal + taxes = {_amt(t)} but the total says {_amt(bill.total)}.",
                          evidence={"computed": str(t), "total": str(bill.total)}, field="total"))
    return flags


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------
def _billed_same_month(bill: DraftBill, ref: RefData) -> Decimal:
    ym = bill.invoice_date.isoformat()[:7]
    return sum((money(i["subtotal"]) for i in ref.invoices.values()
                if i["vendor_id"] == vendor_id(bill) and i["invoice_id"] != bill_id(bill)
                and i["status"] != "rejected" and i["invoice_date"][:7] == ym), Decimal("0"))


def check_contract(bill: DraftBill, ref: RefData) -> list[Flag]:
    c = ref.contract_for(bill)
    if not c or is_credit(bill):
        return []
    flags = []
    if c["status"] == "expired" or (c["end_date"] and bill.invoice_date > d(c["end_date"])):
        flags.append(flag("CONTRACT_EXPIRED",
                          f"Contract {c['contract_id']} ended {c['end_date']}. Renew it or confirm the work was authorized.",
                          evidence={"contract": c["contract_id"], "end_date": c["end_date"]}, field="contract_id"))

    # Billing under the fixed fee has no flag code, so only "over" is raised.
    if c["billing_type"] == "fixed_monthly" and c["monthly_fee"]:
        fee = money(c["monthly_fee"])
        if bill.subtotal > fee + TOL:
            flags.append(flag("OVER_CONTRACT_RATE",
                              f"Billed {_amt(bill.subtotal)} before tax, contract {c['contract_id']} fee is {_amt(fee)}/month.",
                              evidence={"contract": c["contract_id"], "fee": str(fee), "billed": str(bill.subtotal)},
                              field="subtotal"))

    if c["fuel_surcharge_cap_pct"]:
        cap = Decimal(c["fuel_surcharge_cap_pct"])
        is_fuel = lambda l: "fuel surcharge" in l.description.lower() or "surcharge carburant" in l.description.lower()
        base = sum((l.amount for l in bill.lines if not is_fuel(l)), Decimal("0"))
        for l in (l for l in bill.lines if is_fuel(l)):
            m = re.search(r"([\d.,]+)\s*%", l.description)
            stated = Decimal(m.group(1).replace(",", ".")) if m else None
            actual = (l.amount / base * 100).quantize(Decimal("0.01")) if base else None
            worst = max(x for x in (stated, actual) if x is not None) if (stated or actual) else None
            if worst is not None and worst > cap:
                flags.append(flag("OVER_FUEL_SURCHARGE_CAP",
                                  f"Fuel surcharge is {worst}% of freight; contract {c['contract_id']} caps it at {cap}%.",
                                  evidence={"line": l.line_no, "stated_pct": str(stated), "actual_pct": str(actual),
                                            "cap": str(cap)}, field="lines"))

    if c["hourly_rate_cap"]:
        cap = money(c["hourly_rate_cap"])
        for l in bill.lines:
            hourly = "hour" in l.description.lower() or "heure" in l.description.lower() or l.quantity != 1
            if hourly and l.unit_price > cap + TOL:
                flags.append(flag("OVER_CONTRACT_RATE",
                                  f"Line {l.line_no} bills {_amt(l.unit_price)}/hr; contract {c['contract_id']} caps the rate at {_amt(cap)}.",
                                  evidence={"line": l.line_no, "rate": str(l.unit_price), "cap": str(cap)}, field="lines"))

    if c["not_to_exceed_monthly"]:
        nte = money(c["not_to_exceed_monthly"])
        month_total = _billed_same_month(bill, ref) + bill.subtotal
        if month_total > nte + TOL:
            flags.append(flag("OVER_CONTRACT_NTE",
                              f"This month's billing from this vendor would reach {_amt(month_total)}, "
                              f"over the {_amt(nte)} monthly limit in {c['contract_id']}.",
                              evidence={"contract": c["contract_id"], "month_total": str(month_total), "nte": str(nte)},
                              field="subtotal"))
    return flags


# ---------------------------------------------------------------------------
# Purchase order
# ---------------------------------------------------------------------------
def po_remaining(ref: RefData, po_id: str, exclude_bill: str | None = None) -> Decimal:
    po = ref.purchase_orders[po_id]
    used = sum((money(i["subtotal"]) for i in ref.invoices.values()
                if i["po_id"] == po_id and i["status"] != "rejected" and i["invoice_id"] != exclude_bill),
               Decimal("0"))
    return money(po["total_amount"]) - used


def check_po(bill: DraftBill, ref: RefData) -> list[Flag]:
    v = ref.vendors.get(vendor_id(bill) or "", {})
    requires_po = v.get("requires_po") == "yes"
    if not bill.po_number:
        if requires_po:
            return [flag("PO_REQUIRED_MISSING",
                         f"{v['legal_name']} requires a PO and the invoice has none. Hold until a PO is attached.",
                         policy="P13", field="po_number")]
        return []
    po = ref.purchase_orders.get(bill.po_number)
    if not po:
        # A PO number that doesn't exist only has a code when the vendor requires a PO.
        if requires_po:
            return [flag("PO_REQUIRED_MISSING",
                         f"PO {bill.po_number} doesn't exist, and {v['legal_name']} requires a valid PO.",
                         policy="P13", evidence={"po": bill.po_number}, field="po_number")]
        return []
    flags = []
    if po["vendor_id"] != vendor_id(bill):
        flags.append(flag("PO_CLOSED_OR_WRONG_VENDOR",
                          f"PO {bill.po_number} belongs to vendor {po['vendor_id']}, not this one.",
                          evidence={"po": bill.po_number, "po_vendor": po["vendor_id"]}, field="po_number"))
    remaining = po_remaining(ref, bill.po_number, exclude_bill=bill_id(bill))
    if po["status"] == "closed" and remaining <= TOL:
        flags.append(flag("PO_CLOSED_OR_WRONG_VENDOR", f"PO {bill.po_number} is closed and fully used.",
                          evidence={"po": bill.po_number, "po_status": "closed"}, field="po_number"))
    elif not is_credit(bill) and bill.subtotal > remaining + TOL:
        flags.append(flag("PO_OVER_BALANCE",
                          f"Invoice is {_amt(bill.subtotal)} before tax but PO {bill.po_number} only has {_amt(remaining)} left. "
                          f"A finance manager approval is added.",
                          policy="P12", evidence={"po_remaining": str(remaining)}, field="po_number"))
    return flags


# ---------------------------------------------------------------------------
# Dates, credit notes
# ---------------------------------------------------------------------------
def check_dates(bill: DraftBill, ref: RefData) -> list[Flag]:
    """The schema has no received date, so 'today' is ref.as_of (the system date)."""
    today = ref.as_of
    flags = []
    if bill.invoice_date > today:
        flags.append(flag("DATE_ANOMALY", f"Invoice is dated {bill.invoice_date}, which is in the future (today is {today}).",
                          evidence={"kind": "future", "invoice_date": str(bill.invoice_date)}, field="invoice_date"))
    if bill.due_date and bill.due_date < bill.invoice_date:
        flags.append(flag("DATE_ANOMALY", f"Due date {bill.due_date} is before the invoice date {bill.invoice_date}.",
                          evidence={"kind": "due_before_invoice", "due_date": str(bill.due_date)}, field="due_date"))
    if (today - bill.invoice_date) > timedelta(days=STALE_DAYS):
        flags.append(flag("DATE_ANOMALY",
                          f"Invoice is {(today - bill.invoice_date).days} days old. Check it wasn't already paid.",
                          evidence={"kind": "stale", "days_old": (today - bill.invoice_date).days}, field="invoice_date"))
    return flags


def check_credit_note(bill: DraftBill, ref: RefData) -> list[Flag]:
    if is_credit(bill):
        return [flag("CREDIT_NOTE",
                     f"This is a credit note for {_amt(abs(bill.total))}. Apply it against an open invoice from this "
                     f"vendor instead of paying it.", field="total")]
    return []


ALL_CHECKS = [check_vendor, check_tax, check_arithmetic, check_contract, check_po,
              check_fx, check_dates, check_credit_note]


def validate(bill: DraftBill, ref: RefData) -> list[Flag]:
    flags: list[Flag] = []
    for check in ALL_CHECKS:
        flags.extend(check(bill, ref))
    return flags


def has_blocking(flags: list[Flag]) -> bool:
    return any(f.severity == Severity.BLOCK for f in flags)
