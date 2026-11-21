"""
Suggested next step for a triaged email: what a clerk should do with it.

Owner: Person A.
Input: the email dict (inbox/emails.json format), its EmailTriage, and the repository.
Output: SuggestedAction(kind, message, reply_text?, language, invoice_status?).

  invoice / credit_note   → create_drafts     one draft bill per attachment
  missing_attachment      → request_resend    plus a reply asking for the file, in the email's language
  payment_inquiry         → answer_status     looks the invoice up in invoices.csv + payments.csv
  statement               → reconcile_later   no bill is created
  not_ap                  → ignore

Payment inquiries: the vendor is identified from the sender (exact AP contact address, then
domain, then a strict fuzzy match on the sender name), never from the invoice number alone, so a
number that exists for two vendors can't answer for the wrong one. The answer only uses what is
recorded (status, dates, method, payment reference); bank details are never put in a reply.

To change safely: add the email to tests/intake/test_actions.py first.
"""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Literal

import pandas as pd
from pydantic import BaseModel
from rapidfuzz import fuzz

from app.config import get_settings
from app.reference.repository import ReferenceRepository
from app.shared.schemas import EmailClass, EmailTriage

# Sender-name matches below this are not trusted to identify the vendor.
NAME_MATCH_MIN = 90


class ActionKind(StrEnum):
    CREATE_DRAFTS = "create_drafts"
    REQUEST_RESEND = "request_resend"
    ANSWER_STATUS = "answer_status"
    RECONCILE_LATER = "reconcile_later"
    IGNORE = "ignore"


class PaymentRecord(BaseModel):
    payment_id: str
    method: str
    status: str                       # settled | scheduled | outstanding (cheque not cashed yet)
    scheduled_date: date | None = None
    paid_date: date | None = None
    amount: Decimal
    currency: str
    reference: str


class InvoiceStatus(BaseModel):
    vendor_id: str
    vendor_name: str
    invoice_number: str               # as recorded in our books
    invoice_id: str | None = None     # None when we have no record of it
    invoice_date: date | None = None
    due_date: date | None = None
    total: Decimal | None = None
    currency: str | None = None
    status: str                       # paid | scheduled | approved | rejected | not_found | ...
    payments: list[PaymentRecord] = []
    summary: str                      # one sentence for the clerk


class SuggestedAction(BaseModel):
    kind: ActionKind
    message: str                      # what the clerk should do, in English (the UI language)
    language: Literal["en", "fr"]     # language of the email, used for reply_text
    reply_text: str | None = None     # ready-to-send reply to the sender, when one is useful
    vendor_id: str | None = None
    invoice_status: InvoiceStatus | None = None


# ---------------------------------------------------------------- language

_FR_EMAIL_MARKERS = ("bonjour", "merci", "veuillez", "facture", "ci-joint", "paiement", "nous ", "votre",
                     "cordialement", "pièce jointe", "relevé")


def email_language(email: dict) -> Literal["en", "fr"]:
    """Language of the body (what we reply to); the subject only breaks a tie."""
    def score(text: str) -> int:
        t = text.lower()
        return sum(1 for w in _FR_EMAIL_MARKERS if w in t)

    body, subject = email.get("body") or "", email.get("subject") or ""
    return "fr" if score(body) >= 2 or (score(body) == 1 and score(subject) >= 1) else "en"


# ---------------------------------------------------------------- vendor + invoice lookup

def _domain(address: str | None) -> str:
    return address.rsplit("@", 1)[-1].strip().lower() if address and "@" in address else ""


def _best_by_name(cands: pd.DataFrame, name: str) -> pd.DataFrame:
    """The single candidate whose legal name clearly matches the sender name, else nothing."""
    if not name or cands.empty:
        return cands.iloc[0:0]
    scores = cands["legal_name"].map(lambda n: fuzz.token_set_ratio(n.lower(), name.lower()))
    top = scores.max()
    return cands[scores == top] if top >= NAME_MATCH_MIN and (scores == top).sum() == 1 else cands.iloc[0:0]


def vendor_candidates(email: dict, repo: ReferenceRepository) -> tuple[list[dict], str]:
    """Vendor records that could have sent the email, and how we know. Strongest evidence first.

    Usually one record. Several when two master records share an AP address (the master has
    duplicate/lookalike records, e.g. two "Polar Freight Lines" entries) and the sender name
    doesn't tell them apart; the caller then needs other evidence (the invoice number).
    """
    vendors = repo.vendors()
    sender = (email.get("from_address") or "").strip().lower()
    name = (email.get("from_name") or "").strip()
    dom = _domain(sender)
    for hits, how in ((vendors[vendors["ap_contact_email"].str.lower() == sender], f"sender address {sender}"),
                      (vendors[vendors["ap_contact_email"].map(_domain) == dom], f"sender domain {dom}")):
        if not sender or hits.empty:
            continue
        if len(hits) > 1 and len(named := _best_by_name(hits, name)) == 1:
            hits, how = named, f"{how} and name '{name}'"
        return [r.to_dict() for _, r in hits.iterrows()], how
    named = _best_by_name(vendors, name)
    if len(named) == 1:
        return [named.iloc[0].to_dict()], f"sender name '{name}'"
    return [], "sender not in the vendor master"


_INVOICE_REF = re.compile(
    r"\b(?:invoices?|factures?|inv)\b\.?\s*(?:no\.?|number|num[ée]ro|n[°ºo]\.?|#)?\s*:?\s*"
    r"([A-Z]{0,4}[-/]?[A-Z0-9/-]*\d[A-Z0-9/-]*)",
    re.IGNORECASE,
)
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def invoice_refs(text: str) -> list[str]:
    """Invoice numbers mentioned in free text ("invoice 1743", "facture n° FA-000583", "INV #01561")."""
    refs = [m.strip("-/") for m in _INVOICE_REF.findall(text)]
    return list(dict.fromkeys(r for r in refs if r and not _ISO_DATE.match(r)))


def _norm(number: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", number.upper()).lstrip("0")


def _digits(number: str) -> str:
    return re.sub(r"\D", "", number).lstrip("0")


def _find_invoice(vendor_id: str, ref: str, text: str, repo: ReferenceRepository) -> pd.Series | None:
    inv = repo.invoices()
    mine = inv[inv["vendor_id"] == vendor_id]
    hits = mine[mine["vendor_invoice_number"].map(_norm) == _norm(ref)]
    if hits.empty and _digits(ref):
        # "583" for "FA-000583": accept only if the digits identify one invoice.
        hits = mine[mine["vendor_invoice_number"].map(_digits) == _digits(ref)]
    if len(hits) > 1:
        # Several candidates: prefer the one whose invoice date the email mentions.
        dated = hits[hits["invoice_date"].map(lambda d: bool(d) and d in text)]
        hits = dated if len(dated) == 1 else hits
    if len(hits) > 1:
        # History has resubmissions under the same number (one rejected, one paid): answer for the live one.
        live = hits[hits["status"] != "rejected"]
        hits = live if len(live) == 1 else hits
    return hits.iloc[0] if len(hits) == 1 else None


def _d(s: str) -> date | None:
    return date.fromisoformat(s) if s else None


def _money(d: Decimal, currency: str) -> str:
    return f"{d:,.2f} {currency}"


def invoice_status(vendor: dict, ref: str, text: str, repo: ReferenceRepository) -> InvoiceStatus:
    vid, vname = vendor["vendor_id"], vendor["legal_name"]
    row = _find_invoice(vid, ref, text, repo)
    if row is None:
        return InvoiceStatus(vendor_id=vid, vendor_name=vname, invoice_number=ref, status="not_found",
                             summary=f"No invoice {ref} from {vname} in our AP records; it may never have "
                                     f"been received.")
    pays = repo.payments()
    payments = [
        PaymentRecord(payment_id=p.payment_id, method=p.method, status=p.status,
                      scheduled_date=_d(p.scheduled_date), paid_date=_d(p.paid_date),
                      amount=Decimal(p.amount), currency=p.currency, reference=p.reference)
        for p in pays[pays["invoice_id"] == row["invoice_id"]].itertuples(index=False)
    ]
    total, cur = Decimal(row["total"]), row["currency"]
    head = f"Invoice {row['vendor_invoice_number']} ({row['invoice_id']}, {_money(total, cur)}, dated " \
           f"{row['invoice_date']})"
    settled = [p for p in payments if p.status == "settled"]
    outstanding = [p for p in payments if p.status == "outstanding"]
    scheduled = [p for p in payments if p.status == "scheduled"]
    if settled:
        p = settled[-1]
        summary = f"{head} was paid on {p.paid_date} by {p.method}, reference {p.reference}."
    elif outstanding:
        p = outstanding[-1]
        summary = (f"{head}: cheque {p.reference} was issued on {p.paid_date or p.scheduled_date} "
                   f"and has not been cashed yet.")
    elif scheduled:
        p = scheduled[-1]
        summary = f"{head} is scheduled for payment on {p.scheduled_date} by {p.method}."
    elif row["status"] == "rejected":
        summary = f"{head} was rejected and will not be paid as issued."
    else:
        summary = f"{head} is {row['status']} and not yet scheduled for payment; due {row['due_date']}."
    return InvoiceStatus(vendor_id=vid, vendor_name=vname, invoice_number=row["vendor_invoice_number"],
                         invoice_id=row["invoice_id"], invoice_date=_d(row["invoice_date"]),
                         due_date=_d(row["due_date"]), total=total, currency=cur, status=row["status"],
                         payments=payments, summary=summary)


# ---------------------------------------------------------------- replies

def _status_reply(st: InvoiceStatus, lang: str) -> str:
    paid = next((p for p in reversed(st.payments) if p.status == "settled"), None)
    sched = next((p for p in reversed(st.payments) if p.status in ("scheduled", "outstanding")), None)
    if lang == "fr":
        if st.status == "not_found":
            body = (f"Nous ne trouvons pas la facture {st.invoice_number} dans nos dossiers. "
                    f"Pourriez-vous nous en envoyer une copie?")
        elif paid:
            body = (f"La facture {st.invoice_number} du {st.invoice_date} a été payée le {paid.paid_date} "
                    f"par {paid.method} ({_money(paid.amount, paid.currency)}), référence {paid.reference}.")
        elif sched:
            body = (f"Le paiement de la facture {st.invoice_number} est prévu le "
                    f"{sched.paid_date or sched.scheduled_date} par {sched.method}, référence {sched.reference}.")
        else:
            body = f"La facture {st.invoice_number} est en cours de traitement. Nous vous reviendrons sous peu."
        return f"Bonjour,\n\n{body}\n\nCordialement,\nComptes fournisseurs, Harborline Logistics"
    if st.status == "not_found":
        body = f"We can't find invoice {st.invoice_number} in our records. Could you send us a copy?"
    elif paid:
        body = (f"Invoice {st.invoice_number} dated {st.invoice_date} was paid on {paid.paid_date} by "
                f"{paid.method} ({_money(paid.amount, paid.currency)}), reference {paid.reference}.")
    elif sched:
        body = (f"Payment of invoice {st.invoice_number} is scheduled for {sched.paid_date or sched.scheduled_date} "
                f"by {sched.method}, reference {sched.reference}.")
    else:
        body = f"Invoice {st.invoice_number} is being processed. We'll follow up shortly."
    return f"Hello,\n\n{body}\n\nBest regards,\nAccounts Payable, Harborline Logistics"


def _resend_reply(email: dict, lang: str) -> str:
    subject = email.get("subject") or ""
    if lang == "fr":
        return ("Bonjour,\n\nNous avons bien reçu votre courriel"
                + (f" « {subject} »" if subject else "")
                + ", mais aucune facture n'y était jointe. Pourriez-vous nous la renvoyer en PDF?"
                  "\n\nCordialement,\nComptes fournisseurs, Harborline Logistics")
    return ("Hello,\n\nWe received your email" + (f" \"{subject}\"" if subject else "")
            + ", but no invoice was attached. Could you please resend it as a PDF?"
              "\n\nBest regards,\nAccounts Payable, Harborline Logistics")


# ---------------------------------------------------------------- entry point

def suggest_action(email: dict, triage: EmailTriage, repo: ReferenceRepository) -> SuggestedAction:
    lang = email_language(email)
    cls = triage.email_class
    if cls in (EmailClass.INVOICE, EmailClass.CREDIT_NOTE):
        files = triage.attachments_to_process
        kind_word = "credit note" if cls == EmailClass.CREDIT_NOTE else "draft bill"
        return SuggestedAction(kind=ActionKind.CREATE_DRAFTS, language=lang,
                               message=f"Create {len(files)} {kind_word}(s) from: {', '.join(files)}")

    cands, how = vendor_candidates(email, repo)
    vendor = cands[0] if len(cands) == 1 else None
    vid = vendor["vendor_id"] if vendor else None
    if vendor:
        who = f"{vendor['legal_name']} ({vid}, from {how})"
    elif cands:
        who = f"sender matching {len(cands)} vendor records ({', '.join(c['vendor_id'] for c in cands)}, from {how})"
    else:
        who = f"unknown sender ({how})"

    if cls == EmailClass.MISSING_ATTACHMENT:
        return SuggestedAction(kind=ActionKind.REQUEST_RESEND, language=lang, vendor_id=vid,
                               reply_text=_resend_reply(email, lang),
                               message=f"Email from {who} mentions an invoice but has no attachment. "
                                       f"Send the reply asking for the file.")
    if cls == EmailClass.STATEMENT:
        return SuggestedAction(kind=ActionKind.RECONCILE_LATER, language=lang, vendor_id=vid,
                               message=f"Statement of account from {who}. No bill created; reconcile it "
                                       f"against open items at month end.")
    if cls == EmailClass.PAYMENT_INQUIRY:
        return _answer_inquiry(email, lang, cands, who, repo)
    return SuggestedAction(kind=ActionKind.IGNORE, language=lang, vendor_id=vid,
                           message=f"Not an AP email ({triage.reason}). No action needed.")


def _answer_inquiry(email: dict, lang: str, cands: list[dict], who: str,
                    repo: ReferenceRepository) -> SuggestedAction:
    text = f"{email.get('subject') or ''}\n{email.get('body') or ''}"
    refs = invoice_refs(text)
    as_of = get_settings().as_of_date
    if not cands:
        return SuggestedAction(kind=ActionKind.ANSWER_STATUS, language=lang,
                               message=f"Payment question from {who}: identify the vendor before answering"
                                       + (f" (mentions invoice {', '.join(refs)})." if refs else "."))
    single = cands[0]["vendor_id"] if len(cands) == 1 else None
    if not refs:
        return SuggestedAction(kind=ActionKind.ANSWER_STATUS, language=lang, vendor_id=single,
                               message=f"Payment question from {who}, but no invoice number is mentioned. "
                                       f"Ask which invoice they mean.")
    statuses = [invoice_status(v, r, text, repo) for r in refs for v in cands]
    found = [s for s in statuses if s.status != "not_found"]
    if len({s.vendor_id for s in found}) > 1:
        # The same number exists under two candidate records: a clerk has to decide which one.
        ids = ", ".join(sorted({s.vendor_id for s in found}))
        return SuggestedAction(kind=ActionKind.ANSWER_STATUS, language=lang,
                               message=f"Payment question from {who}: invoice {found[0].invoice_number} exists "
                                       f"under {ids}. Check which record is meant before answering.")
    if not found and single is None:
        return SuggestedAction(kind=ActionKind.ANSWER_STATUS, language=lang,
                               message=f"Payment question from {who}: no invoice {', '.join(refs)} under any of "
                                       f"them. Identify the vendor before answering.")
    best = found[0] if found else statuses[0]
    n = len(refs)
    others = "" if n == 1 else f" ({n} invoice numbers mentioned; answering {best.invoice_number})"
    return SuggestedAction(kind=ActionKind.ANSWER_STATUS, language=lang, vendor_id=best.vendor_id,
                           invoice_status=best, reply_text=_status_reply(best, lang),
                           message=f"Payment question from {who}. As of {as_of}: {best.summary}{others}")
