"""
Request and response models for the HTTP API. These are the API's contract with the frontend (the OpenAPI spec and
the generated TypeScript types come from here). The domain contract between backend modules stays in
app/shared/schemas.py.

Money rules:
- Out: `Money` serializes a Decimal as a string with exactly two decimals ("742.30"), never a JSON number.
- In: `MoneyIn` accepts only a string like "742.30" or "-15.00". A JSON number is refused (422), because a float
  can't represent most cent amounts exactly. Convert with app.services.money.parse_money.
- Rates, quantities and unit prices are exact decimal strings, as stored in the database.

Bank account numbers in responses are already masked for roles that may not see them (app.services.masking).
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, StringConstraints, WithJsonSchema

from app.intake.actions import SuggestedAction

MONEY_PATTERN = r"^-?\d{1,12}(\.\d{1,2})?$"

Money = Annotated[
    Decimal,
    PlainSerializer(lambda v: f"{v:.2f}", return_type=str, when_used="always"),
    WithJsonSchema({"type": "string", "pattern": r"^-?\d+\.\d{2}$", "examples": ["742.30"]}),
]
MoneyIn = Annotated[str, StringConstraints(strip_whitespace=True, pattern=MONEY_PATTERN),
                    WithJsonSchema({"type": "string", "pattern": MONEY_PATTERN, "examples": ["742.30"]})]
def _iso_utc(value: datetime) -> str:
    """DB timestamps are naive UTC; send every timestamp as ISO 8601 UTC with an explicit Z."""
    if value.tzinfo is not None:
        value = value.astimezone(UTC).replace(tzinfo=None)
    return value.isoformat(timespec="seconds") + "Z"


UtcDateTime = Annotated[
    datetime,
    PlainSerializer(_iso_utc, return_type=str, when_used="always"),
    WithJsonSchema({"type": "string", "format": "date-time", "examples": ["2026-11-02T15:00:00Z"]}),
]
DecimalText = Annotated[str, Field(description="Exact decimal as a string, e.g. '0.09975'")]
UserId = Annotated[str, StringConstraints(pattern=r"^U\d{3,}$")]
Comment = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]

BillStatus = Literal["needs_review", "on_hold", "pending_approval", "approved", "rejected", "scheduled", "paid",
                     "credit_open", "void"]
PaymentStatus = Literal["scheduled", "released", "settled", "outstanding", "failed", "cancelled"]
# GET /payments order: newest scheduled date first (the default) or oldest first. Each value maps to fixed
# ORDER BY clauses in services/payments.py; FastAPI refuses anything else with 422 before the query runs.
PaymentSort = Literal["scheduled_desc", "scheduled_asc"]
PaymentMethod = Literal["EFT", "CHEQUE", "CARD"]
VendorStatus = Literal["active", "on_hold", "pending_review"]
Role = Literal["employee", "ap_clerk", "approver", "finance_manager", "controller_admin", "auditor"]
UserStatus = Literal["active", "on_leave", "terminated"]

T = TypeVar("T")


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class InModel(BaseModel):
    """Request bodies refuse unknown fields, so a client can't slip in e.g. `user_id` or `status`."""

    model_config = ConfigDict(extra="forbid")


class Page(ApiModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


# ---------------------------------------------------------------- errors (documented in OpenAPI)

class ErrorBody(ApiModel):
    code: str
    message: str
    details: Any = None


class ErrorEnvelope(ApiModel):
    error: ErrorBody
    request_id: str | None = None


# ---------------------------------------------------------------- auth

class PickerUser(ApiModel):
    user_id: str
    full_name: str
    title: str
    role: Role
    department_id: str
    department_name: str | None = Field(
        None, description="The department's name from the departments table ('Operations'); null if unknown")
    status: UserStatus


class LoginIn(InModel):
    user_id: UserId


class ActingForOut(ApiModel):
    user_id: str
    full_name: str
    starts_on: date
    ends_on: date | None = None


class Me(ApiModel):
    user_id: str
    full_name: str
    title: str
    role: Role
    department_id: str
    status: UserStatus
    approval_limit_cad: Money | None = None
    release_limit_cad: Money | None = Field(
        None, description="Largest payment this user may release; '0.00' if they can't release, null if unlimited")
    acting_for: list[ActingForOut] = []


# ---------------------------------------------------------------- bills

class OpenFlagCounts(ApiModel):
    block: int = 0
    warn: int = 0
    info: int = 0


class CurrentStepOut(ApiModel):
    step_no: int
    role: str
    user_id: str | None
    delegated_from: str | None = None


class ActionState(ApiModel):
    allowed: bool
    reason: str | None = Field(None, description="Why not, in words the UI can show; or what allows it")


class BillSummary(ApiModel):
    bill_id: str
    status: BillStatus
    origin: Literal["history", "app"]
    vendor_id: str | None
    vendor_name: str | None
    vendor_invoice_number: str
    invoice_date: date
    due_date: date | None
    received_date: date
    currency: Literal["CAD", "USD"]
    total: Money
    total_cad: Money
    is_credit_note: bool
    department_id: str | None
    requester_user_id: str | None
    row_version: int
    open_flags: OpenFlagCounts = OpenFlagCounts()
    top_flag_code: str | None = None
    current_step: CurrentStepOut | None = None


class BillLineOut(ApiModel):
    line_no: int
    description: str
    quantity: DecimalText
    unit_price: DecimalText
    amount: Money
    line_type: Literal["goods", "services"]
    gst_hst_code: str | None
    pst_qst_code: str | None
    gl_account: str | None
    department_id: str | None
    suggested_gl_account: str | None
    suggested_department_id: str | None
    suggestion_confidence: float | None
    suggestion_reason: str | None
    coding_status: Literal["none", "suggested", "accepted", "overridden"]
    coded_by: str | None
    coded_at: UtcDateTime | None


class BillTaxOut(ApiModel):
    tax_code: str
    rate: DecimalText
    amount: Money


class FlagOut(ApiModel):
    id: int
    code: str
    severity: Literal["block", "warn", "info"]
    field: str | None
    message: str
    evidence: dict[str, Any]
    resolution: Literal["open", "overridden", "resolved"]
    resolved_by: str | None
    resolved_at: UtcDateTime | None
    resolution_comment: str | None


class RouteStepOut(ApiModel):
    step_no: int
    role: str
    user_id: str | None = Field(description="None when no eligible approver was found (needs assignment)")
    policy_ids: list[str]
    reason: str
    delegated_from: str | None
    escalated_from: str | None
    decision: Literal["approved", "rejected"] | None = None
    decided_by: str | None = None
    decided_at: UtcDateTime | None = None


class DuplicateOut(ApiModel):
    kind: str
    score: float
    matched_invoice_id: str | None = None
    matched_card_txn_id: str | None = None
    reasons: list[str] = []


class ControlsRunOut(ApiModel):
    run_id: int
    version: int
    evaluated_at: UtcDateTime
    can_auto_proceed: bool
    recommendation: str | None
    flags: list[FlagOut]
    route: list[RouteStepOut]
    duplicates: list[DuplicateOut] = []


class DecisionOut(ApiModel):
    decision_id: str
    step_no: int
    actor_user_id: str
    actor_role: str
    step_role: str | None
    on_behalf_of: str | None
    decision: Literal["approved", "rejected"]
    comment: str | None
    acted_at: UtcDateTime
    origin: Literal["history", "app"]


class PaymentSummary(ApiModel):
    payment_id: str
    bill_id: str
    vendor_id: str
    vendor_name: str | None
    method: PaymentMethod
    currency: Literal["CAD", "USD"]
    amount: Money
    amount_cad: Money
    scheduled_date: date
    paid_date: date | None
    status: PaymentStatus
    reference: str | None
    prepared_by: str | None
    released_by: str | None
    released_at: UtcDateTime | None


class AuditEventOut(ApiModel):
    seq: int
    event_id: str
    at: UtcDateTime
    actor_user_id: str
    actor_role: str
    on_behalf_of: str | None
    action: str
    entity_type: str
    entity_id: str
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    comment: str | None
    request_id: str | None


class AuditPage(ApiModel):
    items: list[AuditEventOut]
    next_after_seq: int | None = Field(None, description="Pass as after_seq to get the next page; None at the end")


class BillDetail(BillSummary):
    subtotal: Money
    fx_rate_to_cad: DecimalText
    fx_rate_date: date | None
    ship_to_province: str | None
    po_id: str | None
    contract_id: str | None
    source_email_id: str | None
    file_hash: str | None
    created_at: UtcDateTime
    created_by: str | None
    updated_at: UtcDateTime
    department_source: Literal["invoice", "submitter", "coding", "user", "history"] | None = Field(
        None, description="Where department_id came from. 'coding' means suggested from the line coding and not yet "
                          "confirmed by a person; editing the department makes it 'user'.")
    extracted: dict[str, Any] | None = Field(
        None, description="Frozen extraction snapshot from intake, with bank details masked for the caller's role")
    lines: list[BillLineOut]
    taxes: list[BillTaxOut]
    latest_run: ControlsRunOut | None
    decisions: list[DecisionOut]
    payments: list[PaymentSummary]
    audit: list[AuditEventOut]
    allowed_actions: dict[str, ActionState] = Field(
        default_factory=dict, description="What the signed-in user can do to this bill now, with the reason if not")


class BillHeaderPatch(InModel):
    row_version: int
    vendor_id: str | None = None
    vendor_invoice_number: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] | None = None
    invoice_date: date | None = None
    due_date: date | None = None
    po_id: str | None = None
    contract_id: str | None = None
    department_id: str | None = None
    requester_user_id: UserId | None = None
    ship_to_province: str | None = None


class LineCodingPatch(InModel):
    row_version: int
    gl_account: str
    department_id: str


class FlagResolveIn(InModel):
    row_version: int
    resolution: Literal["resolved", "overridden"]
    comment: Comment | None = None


class RowVersionIn(InModel):
    row_version: int


class DecisionIn(InModel):
    row_version: int
    comment: Comment | None = None


class RejectIn(InModel):
    row_version: int
    comment: Comment


class AssignIn(InModel):
    row_version: int
    user_id: UserId


class VoidIn(InModel):
    row_version: int
    comment: Comment


# ---------------------------------------------------------------- intake

class IntakeItemOut(ApiModel):
    item_id: int
    email_id: str | None
    file_name: str
    file_hash: str | None
    status: Literal["ok", "llm_skipped", "failed", "queued", "processing"]
    error: str | None
    warnings: list[str]
    bill_id: str | None
    created_at: UtcDateTime
    created_by: str | None


class JobOut(ApiModel):
    job_id: str
    status: Literal["queued", "running", "done", "failed"]
    started_by: str
    started_at: UtcDateTime
    finished_at: UtcDateTime | None = None
    total_emails: int = 0
    processed_emails: int = 0
    items: list[IntakeItemOut] = []
    error: str | None = None


# ---------------------------------------------------------------- payments

class BankAccountOut(ApiModel):
    id: int
    institution: str
    transit: str
    account: str = Field(description="Full number for AP, finance and controller; masked to the last 4 otherwise")
    account_last4: str
    masked: bool
    valid_from: date
    valid_to: date | None


class PaymentDetail(PaymentSummary):
    fx_rate_to_cad: DecimalText
    fx_rate_date: date | None
    discount_taken: Money
    bank_account: BankAccountOut | None
    bill: BillSummary
    lines: list[BillLineOut]
    decisions: list[DecisionOut]
    audit: list[AuditEventOut]
    allowed_actions: dict[str, ActionState] = Field(default_factory=dict)


class ScheduleIn(InModel):
    scheduled_date: date
    method: PaymentMethod = "EFT"


class CommentIn(InModel):
    comment: Comment | None = None


class StatusTotal(ApiModel):
    status: PaymentStatus
    count: int
    total_cad: Money


class PaymentDashboard(ApiModel):
    as_of: date
    by_status: list[StatusTotal]
    due_next_7_days_count: int
    due_next_7_days_cad: Money
    overdue_count: int
    overdue_cad: Money


# ---------------------------------------------------------------- vendors and bank changes

class VendorSummary(ApiModel):
    vendor_id: str
    legal_name: str
    category: str
    province_or_state: str
    country: str
    status: VendorStatus
    preferred_payment_method: PaymentMethod
    payment_terms_days: int
    requires_po: bool


class BankChangeOut(ApiModel):
    change_id: str
    vendor_id: str
    requested_at: UtcDateTime
    requested_by: str | None
    request_channel: Literal["phone_callback_verified", "vendor_portal", "email_request"]
    old_account_last4: str | None
    new_account_last4: str
    new_institution: str | None
    new_transit: str | None
    new_account: str | None = Field(description="Masked to the last 4 for roles without full bank access")
    verified_by_callback: bool
    status: Literal["pending_verification", "verified", "rejected"]
    verified_by: str | None
    verified_at: UtcDateTime | None
    origin: Literal["history", "app"]


class VendorDetail(VendorSummary):
    address: str
    gst_hst_number: str | None
    qst_number: str | None
    default_gl_account: str | None
    early_pay_discount: str | None
    accepts_card_payment: bool
    ap_contact_email: str
    onboarded_at: date
    origin: Literal["history", "app"]
    bank_account: BankAccountOut | None
    bank_changes: list[BankChangeOut]


class VendorIn(InModel):
    legal_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=200)]
    category: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=100)]
    address: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=300)]
    province_or_state: Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}$")]
    country: Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}$")]
    gst_hst_number: str | None = None
    qst_number: str | None = None
    default_gl_account: str | None = None
    payment_terms_days: Annotated[int, Field(ge=0, le=180)] = 30
    early_pay_discount: str | None = None
    preferred_payment_method: PaymentMethod = "EFT"
    accepts_card_payment: bool = False
    ap_contact_email: Annotated[str, StringConstraints(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")]
    requires_po: bool = False


class BankChangeIn(InModel):
    institution: Annotated[str, StringConstraints(pattern=r"^\d{3}$")]
    transit: Annotated[str, StringConstraints(pattern=r"^\d{5}$")]
    account: Annotated[str, StringConstraints(pattern=r"^\d{5,12}$")]
    request_channel: Literal["phone_callback_verified", "vendor_portal", "email_request"]


# ---------------------------------------------------------------- spend, delegation, admin

class SpendRow(ApiModel):
    key: str
    label: str
    bill_count: int
    total_cad: Money


class SpendReport(ApiModel):
    group_by: Literal["department", "vendor", "gl_account"]
    from_date: date | None
    to_date: date | None
    department_id: str | None = Field(None, description="Set when the report is limited to one department")
    rows: list[SpendRow]
    total_cad: Money


class DelegationIn(InModel):
    delegate_user_id: UserId
    starts_on: date
    ends_on: date | None = None


class PolicyOut(ApiModel):
    rule_id: str
    rule_type: Literal["approval", "payment_release", "match"]
    condition: str
    required: str
    notes: str | None
    updated_at: UtcDateTime
    updated_by: str | None


class PolicyPatch(InModel):
    condition: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3)] | None = None
    required: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3)] | None = None
    notes: str | None = None


class UserOut(ApiModel):
    user_id: str
    full_name: str
    email: str
    title: str
    department_id: str
    manager_id: str | None
    role: Role
    approval_limit_cad: Money
    work_province: str
    status: UserStatus
    status_since: date | None
    delegate_user_id: str | None
    hire_date: date


class UserPatch(InModel):
    role: Role | None = None
    status: UserStatus | None = None
    approval_limit_cad: MoneyIn | None = None
    department_id: str | None = None
    manager_id: UserId | None = None
    delegate_user_id: UserId | None = None


class AbsenceOut(ApiModel):
    id: int
    user_id: str
    delegate_user_id: str
    starts_on: date
    ends_on: date | None


class AbsenceIn(InModel):
    user_id: UserId
    delegate_user_id: UserId
    starts_on: date
    ends_on: date | None = None


# ---------------------------------------------------------------- reference data and inbox

class FlagHelpOut(ApiModel):
    title: str
    help: str
    severity: Literal["block", "warn", "info"]


class DepartmentOut(ApiModel):
    department_id: str
    name: str
    cost_centre: str
    manager_user_id: str


class GlAccountOut(ApiModel):
    account_number: str
    name: str
    account_type: str


class EmailOut(ApiModel):
    email_id: str
    from_name: str | None
    from_address: str
    subject: str
    received_at: UtcDateTime
    attachments: list[str]
    email_class: str | None
    triage_reason: str | None
    triaged_at: UtcDateTime | None
    items: list[IntakeItemOut] = []
    suggested_action: SuggestedAction | None = None  # intake lane: app.intake.review.action_for


# ---------------------------------------------------------------- early-payment discounts (controls.early_pay)

class EarlyPaySuggestionOut(ApiModel):
    bill_id: str
    vendor_id: str
    vendor_name: str | None
    status: str
    terms: str = Field(description='The vendor\'s terms in words, e.g. "2% off if paid within 10 days, net 30"')
    method: str
    invoice_date: date
    due_date: date
    discount_deadline: date | None = Field(None, description="Last day the money must arrive to earn the discount")
    pay_on: date = Field(description="Suggested date to send the payment")
    scheduled_date: date | None
    currency: Literal["CAD", "USD"]
    total: Money
    saving: Money = Field(description="In the bill's currency, compared with paying on the due date")
    saving_cad: Money
    pay_amount: Money
    action: Literal["take_discount", "pay_on_due_date", "pay_now", "reschedule"]
    reason: str
    notes: list[str]


class PastDiscountOut(ApiModel):
    payment_id: str
    bill_id: str
    vendor_id: str
    invoice_date: date
    paid_date: date
    days_to_pay: int
    discount_cad: Money


class EarlyPaySummary(ApiModel):
    bills: int
    with_discount_open: int
    saving_cad: Money
    to_reschedule: int
    pay_now: int


class EarlyPayHistory(ApiModel):
    taken: int
    taken_cad: Money
    missed: int
    missed_cad: Money
    missed_payments: list[PastDiscountOut]


class EarlyPayReport(ApiModel):
    as_of: date
    summary: EarlyPaySummary
    suggestions: list[EarlyPaySuggestionOut]
    history: EarlyPayHistory
# ---------------------------------------------------------------- bank reconciliation (controls.reconciliation)

class ReconIssueOut(ApiModel):
    code: str
    severity: Literal["info", "review"]
    message: str


class ReconLineOut(ApiModel):
    bank_txn_id: str
    posted_date: date
    description: str
    amount: Money = Field(description="Debit positive, credit negative")
    status: Literal["matched", "bank_fee", "unexplained"]
    payment_ids: list[str]
    bill_ids: list[str]
    vendor_id: str | None
    difference: Money | None = Field(None, description="Bank amount minus payment amount, when they differ")
    issues: list[ReconIssueOut]


class ReconPaymentOut(ApiModel):
    payment_id: str
    bill_id: str
    vendor_id: str
    method: str
    status: str
    amount_cad: Money
    on_date: date | None = Field(None, description="Paid date, or the scheduled date when not paid yet")
    bank_txn_id: str | None
    issues: list[ReconIssueOut]


class ReconDoublePaymentOut(ApiModel):
    bill_ids: list[str]
    card_txn_ids: list[str]
    payment_ids: list[str]
    bank_txn_ids: list[str]
    extra_payment_ids: list[str]
    at_risk_payment_ids: list[str]
    confirmed: bool
    extra_paid_cad: Money
    at_risk_cad: Money
    message: str


class ReconSummaryOut(ApiModel):
    lines: int
    debits_cad: Money
    matched: int
    matched_cad: Money
    bank_fees: int
    bank_fees_cad: Money
    unexplained: int
    unexplained_cad: Money
    double_payments: int
    double_paid_extra_cad: Money
    double_at_risk_cad: Money
    needs_review: int
    issues: dict[str, int]


class BankReconciliation(ApiModel):
    statement_from: date | None
    statement_to: date | None
    summary: ReconSummaryOut
    lines: list[ReconLineOut]
    payments: list[ReconPaymentOut]
    double_payments: list[ReconDoublePaymentOut]
