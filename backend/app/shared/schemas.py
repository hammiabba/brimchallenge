"""
Shared data contract between the extraction, controls and DB teams.

RULES
- Everyone imports from this file. Nobody defines their own version.
- Changes are announced to the whole team before merging.
- Money: Decimal, 2 decimal places, in the invoice currency unless the name ends in _cad.
- Dates: ISO "YYYY-MM-DD" (datetime.date). The system's "today" is 2026-11-02.
- IDs reuse the dataset's IDs: V001, U007, D01, PO-2026-0001, C018, AP-00001.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------- enums

class EmailClass(str, Enum):
    INVOICE = "invoice"
    CREDIT_NOTE = "credit_note"
    STATEMENT = "statement"                      # EM-056
    PAYMENT_INQUIRY = "payment_inquiry"          # EM-057
    MISSING_ATTACHMENT = "missing_attachment"    # EM-058
    NOT_AP = "not_ap"                            # EM-059 marketing


class TaxCode(str, Enum):
    HST13 = "HST13"
    GST5 = "GST5"
    PST7_BC = "PST7_BC"
    QST9975 = "QST9975"
    EXEMPT = "EXEMPT"
    FOREIGN = "FOREIGN"


class LineType(str, Enum):
    GOODS = "goods"
    SERVICES = "services"


class Severity(str, Enum):
    BLOCK = "block"   # cannot be approved/paid until resolved
    WARN = "warn"     # needs a human to look; can be overridden with a comment
    INFO = "info"     # shown, no action needed


class MatchMethod(str, Enum):
    GST_NUMBER = "gst_number"
    BANK_ACCOUNT = "bank_account"
    EMAIL_DOMAIN = "email_domain"
    FUZZY_NAME = "fuzzy_name"
    NONE = "none"     # vendor not found in master


# ---------------------------------------------------------------- Person A output

class EmailTriage(BaseModel):
    email_id: str                         # "EM-029"
    email_class: EmailClass
    attachments_to_process: list[str]     # ["orionstrategypar-inv-029.pdf", "orionstrategypar_281.pdf"]
    reason: str                           # "Subject says 'Facture', has 2 PDF attachments"


class BankDetails(BaseModel):
    institution: Optional[str] = None     # "010"
    transit: Optional[str] = None         # "40238"
    account: Optional[str] = None         # "593014216"


class VendorOnInvoice(BaseModel):
    name_on_invoice: str
    gst_number: Optional[str] = None
    qst_number: Optional[str] = None
    address: Optional[str] = None
    bank: BankDetails = BankDetails()
    # filled by vendor resolution
    vendor_id: Optional[str] = None       # None = not in master
    match_method: MatchMethod = MatchMethod.NONE
    match_score: float = 0.0              # 0..1


class TaxLine(BaseModel):
    code: TaxCode
    rate: Decimal                         # 0.13
    amount: Decimal                       # 742.30 (negative on credit notes)


class CodingSuggestion(BaseModel):
    gl_account: str                       # "6420"
    department_id: str                    # "D07"
    confidence: float                     # 0..1
    reason: str                           # "18 of 20 past lines from this vendor coded 5010"
    accepted: bool = False                # set true when a clerk accepts or edits it


class InvoiceLine(BaseModel):
    line_no: int
    description: str
    quantity: Decimal
    unit_price: Decimal
    amount: Decimal
    line_type: LineType = LineType.SERVICES
    coding: Optional[CodingSuggestion] = None


class SourceInfo(BaseModel):
    email_id: Optional[str] = None        # None for manual uploads
    sender_address: Optional[str] = None  # "ar@harlowandstern-llp.example"
    file_name: str
    file_hash: str                        # sha256; also the cache key for LLM results
    language: str = "en"                  # "en" | "fr"
    was_ocr: bool = False


class DraftBill(BaseModel):
    source: SourceInfo
    vendor: VendorOnInvoice

    invoice_number: str
    invoice_date: date
    due_date: Optional[date] = None
    payment_terms_days: Optional[int] = None
    currency: str = "CAD"                 # "CAD" | "USD"
    is_credit_note: bool = False

    ship_to_province: Optional[str] = None   # from bill-to address: "ON", "QC", ...
    po_number: Optional[str] = None
    contract_id: Optional[str] = None
    requester_user_id: Optional[str] = None
    department_id: Optional[str] = None

    lines: list[InvoiceLine]
    subtotal: Decimal
    taxes: list[TaxLine] = []
    total: Decimal

    fx_rate_to_cad: Decimal = Decimal("1")
    total_cad: Decimal

    # extraction quality
    field_confidence: dict[str, float] = {}       # {"invoice_number": 0.98, "total": 0.6}
    extraction_warnings: list[str] = []           # ["subtotal + taxes != total"]


# ---------------------------------------------------------------- Person B output

class Flag(BaseModel):
    code: str                 # stable UPPER_SNAKE id, see FLAG_CODES below
    severity: Severity
    message: str              # plain-English sentence shown in the UI
    evidence: dict = {}       # {"expected": "GST5", "found": "HST13", "ship_to": "AB"}
    field: Optional[str] = None   # which field to highlight in the UI, e.g. "taxes"


class DuplicateMatch(BaseModel):
    kind: str                 # "exact" | "normalized" | "near" | "card_paid" | "cross_vendor"
    score: float              # 0..1
    matched_invoice_id: Optional[str] = None      # "AP-00317"
    matched_card_txn_id: Optional[str] = None     # "CT-00412"
    reasons: list[str]        # ["same vendor", "invoice no 583 == FA-000583 after normalizing"]


class ApprovalStep(BaseModel):
    step_no: int
    role: str                         # "dept_manager" | "finance_manager" | "controller_admin" | "cfo"
    user_id: str                      # who must act
    policy_ids: list[str]             # ["P02"] or ["P06"]
    reason: str                       # "Total $16,131.94 > $10,000"
    delegated_from: Optional[str] = None    # "U012" when U003 acts as delegate (P08)
    escalated_from: Optional[str] = None    # set when P07 self-approval escalation applied


class ControlsResult(BaseModel):
    """Everything Person B returns for one DraftBill. The DB team stores this."""
    flags: list[Flag]
    duplicates: list[DuplicateMatch]
    route: list[ApprovalStep]
    can_auto_proceed: bool            # False if any BLOCK flag
    recommendation: Optional[str] = None   # bonus: "Hold - bank details differ from master"


class PermissionDecision(BaseModel):
    """Return type of can_approve() / can_release()."""
    allowed: bool
    reason: str                       # "U003 approved this invoice (P11)"


# ---------------------------------------------------------------- DB team

class AuditEvent(BaseModel):
    event_id: str
    at: datetime
    actor_user_id: str
    actor_role: str
    on_behalf_of: Optional[str] = None    # delegation
    action: str                           # "invoice.approved", "payment.released", "vendor.bank_changed"
    entity_type: str                      # "invoice" | "payment" | "vendor" | "policy" | "user"
    entity_id: str
    before: Optional[dict] = None
    after: Optional[dict] = None
    comment: Optional[str] = None


# ---------------------------------------------------------------- flag catalogue
# Agree on these names up front so the UI can map codes to icons/help text.

FLAG_CODES = {
    # vendor
    "VENDOR_NOT_FOUND": "block",
    "VENDOR_NOT_ACTIVE": "block",
    "VENDOR_LOOKALIKE": "block",
    "GST_NUMBER_MISMATCH": "warn",
    "BANK_DETAILS_MISMATCH": "block",
    "BANK_CHANGE_UNVERIFIED": "block",
    "VENDOR_PENDING_REVIEW": "warn",
    "GST_NUMBER_MISSING": "warn",
    "SENDER_DOMAIN_MISMATCH": "warn",
    # tax / arithmetic
    "TAX_WRONG_FOR_PROVINCE": "block",
    "TAX_MISSING": "block",
    "PST_ON_SERVICES": "warn",
    "LINE_MATH_ERROR": "block",
    "SUBTOTAL_MISMATCH": "block",
    "TOTAL_MISMATCH": "block",
    # contract / PO
    "OVER_CONTRACT_RATE": "warn",
    "OVER_FUEL_SURCHARGE_CAP": "warn",
    "OVER_CONTRACT_NTE": "warn",
    "CONTRACT_EXPIRED": "warn",
    "PO_REQUIRED_MISSING": "block",
    "PO_OVER_BALANCE": "warn",
    "PO_CLOSED_OR_WRONG_VENDOR": "block",
    "PO_NOT_FOUND": "block",
    # duplicates / fraud
    "DUPLICATE_EXACT": "block",
    "DUPLICATE_LIKELY": "warn",
    "ALREADY_PAID_BY_CARD": "block",
    "POSSIBLE_SPLIT": "warn",
    # misc
    "CREDIT_NOTE": "info",
    "FOREIGN_CURRENCY": "info",
    "CURRENCY_UNSUPPORTED": "block",
    "DATE_ANOMALY": "warn",
    "LOW_EXTRACTION_CONFIDENCE": "warn",
    "REQUESTER_TERMINATED": "warn",
}


# ---------------------------------------------------------------- example
if __name__ == "__main__":
    bill = DraftBill(
        source=SourceInfo(email_id="EM-026", sender_address="ar@harlowandstern-llp.example",
                          file_name="Invoice HA26-2766.pdf", file_hash="sha256:..."),
        vendor=VendorOnInvoice(name_on_invoice="Harlow and Stern LLP", gst_number="503486760RT0001",
                               bank=BankDetails(institution="010", transit="40238", account="593014216"),
                               vendor_id="V052", match_method=MatchMethod.GST_NUMBER, match_score=1.0),
        invoice_number="HA26-2766", invoice_date=date(2026, 10, 27), due_date=date(2026, 11, 26),
        ship_to_province="ON", department_id="D01", requester_user_id="U013",
        lines=[InvoiceLine(line_no=1, description="Legal services - Commercial lease review",
                           quantity=Decimal("12"), unit_price=Decimal("450.00"), amount=Decimal("5400.00")),
               InvoiceLine(line_no=2, description="Disbursements and filing fees",
                           quantity=Decimal("1"), unit_price=Decimal("310.00"), amount=Decimal("310.00"))],
        subtotal=Decimal("5710.00"),
        taxes=[TaxLine(code=TaxCode.HST13, rate=Decimal("0.13"), amount=Decimal("742.30"))],
        total=Decimal("6452.30"), total_cad=Decimal("6452.30"),
    )
    result = ControlsResult(
        flags=[Flag(code="VENDOR_LOOKALIKE", severity=Severity.BLOCK,
                    message="'Harlow and Stern LLP' looks like existing vendor 'Harlow & Stern LLP' (V026) "
                            "but has a different GST number, bank account and email domain.",
                    evidence={"similar_vendor": "V026", "sender_domain": "harlowandstern-llp.example",
                              "known_domain": "harlow.example"}, field="vendor")],
        duplicates=[],
        route=[ApprovalStep(step_no=1, role="dept_manager", user_id="U007", policy_ids=["P01"],
                            reason="Total $6,452.30 ≤ $10,000"),
               ApprovalStep(step_no=2, role="finance_manager", user_id="U003", policy_ids=["P06"],
                            reason="Legal vendor needs finance approval")],
        can_auto_proceed=False,
        recommendation="Hold: possible impersonation of Harlow & Stern LLP. Verify by phone before approving.",
    )
    print(bill.model_dump_json(indent=2))
    print(result.model_dump_json(indent=2))
