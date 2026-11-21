"""
Classify an inbound AP email → EmailTriage.

Owner: Person A.
Input: one email dict as in inbox/emails.json (email_id, from_address, subject, body, attachments).
Output: EmailTriage(email_id, email_class, attachments_to_process, reason).

Rules first, LLM only as a tie-break. The rules use English and French keyword sets
over subject + body together, because the two can be in different languages
(a French body under an English subject, and the reverse). Rule order matters:

  1. marketing / newsletter                     → not_ap
  2. statement of account                       → statement      (never creates bills)
  3. payment-status question, no attachment     → payment_inquiry
  4. has invoice-like attachments               → credit_note | invoice  (one bill per attachment)
  5. says "attached"/"invoice" but has none     → missing_attachment
  6. nothing matched                            → LLM if configured, else not_ap

Statement comes before missing_attachment on purpose: "Attached is your statement"
with no file is still a statement, and there's nothing to pay.

To change safely: add the email to tests/intake/test_classifier.py first. Keep keywords
generic (no vendor names).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from app.shared.schemas import EmailClass, EmailTriage

INVOICE_FILE_EXTS = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".gif", ".webp"}

_MARKETING = [
    r"\bsale\b", r"\d+\s?% off", r"\bshop now\b", r"\bunsubscribe\b", r"\bnewsletter\b", r"\bpromo(tion)?\b",
    r"\bwebinar\b", r"\bdiscount code\b", r"\bsoldes?\b", r"\brabais\b", r"\binfolettre\b", r"d[ée]sabonner",
    r"\blimited time\b", r"\bsave (up to|on)\b",
]
_MARKETING_SENDERS = re.compile(r"^(news|newsletter|marketing|promo|offers|no-?reply|info)@", re.I)

_STATEMENT = [r"statement of account", r"account statement", r"\bstatement\b.*\b(october|month|period)\b",
              r"relev[ée] de compte", r"[ée]tat de compte"]

_INQUIRY = [
    r"where is (the |our )?payment", r"(not|n't) (yet )?(seen|received) (the |our )?payment",
    r"payment status", r"status of (the |our )?payment", r"confirm the status", r"when will .* be paid",
    r"still (unpaid|outstanding)", r"paiement .*(pas|non) (encore )?re[çc]u", r"o[ùu] en est le paiement",
    r"statut du paiement", r"avons pas re[çc]u (votre|le) paiement",
]

_CREDIT = [r"credit note", r"credit memo", r"note de cr[ée]dit", r"\bavoir\b"]
# Credit-note numbering ("CN-FA-000413"); case-sensitive so it doesn't fire on ordinary words.
_CREDIT_NUMBER = re.compile(r"\bCN-?[A-Z0-9]")

_ATTACH_WORDS = [r"\battach", r"\benclosed\b", r"ci-joint", r"pi[èe]ce jointe", r"find (our|the) .*invoice",
                 r"veuillez trouver"]
_INVOICE_WORDS = [r"\binvoice\b", r"\bfacture\b", r"\bbill\b"]


def _hits(patterns: list[str], text: str) -> list[str]:
    return [p for p in patterns if re.search(p, text, re.IGNORECASE)]


def _invoice_attachments(attachments: list[str]) -> list[str]:
    return [a for a in attachments if Path(a).suffix.lower() in INVOICE_FILE_EXTS]


def classify_rules(email: dict) -> EmailTriage | None:
    """Deterministic classification; None when no rule is confident."""
    eid = email["email_id"]
    subject, body = email.get("subject") or "", email.get("body") or ""
    text = f"{subject}\n{body}"
    attachments = list(email.get("attachments") or [])
    docs = _invoice_attachments(attachments)
    sender = email.get("from_address") or ""

    def triage(cls: EmailClass, reason: str, to_process: list[str] | None = None) -> EmailTriage:
        return EmailTriage(email_id=eid, email_class=cls, attachments_to_process=to_process or [], reason=reason)

    marketing = _hits(_MARKETING, text) + (["marketing sender"] if _MARKETING_SENDERS.match(sender) else [])
    ap_words = _hits(_INVOICE_WORDS + _CREDIT + _STATEMENT, text)
    if not docs and len(marketing) >= 2 and not ap_words:
        return triage(EmailClass.NOT_AP, f"Marketing content ({len(marketing)} promotional signals), no invoice")

    if _hits(_STATEMENT, text):
        return triage(EmailClass.STATEMENT,
                      "Statement of account: lists balances, nothing to pay from this email"
                      + (f"; {len(attachments)} attachment(s) kept for reference" if attachments else ""))

    if not docs and _hits(_INQUIRY, text):
        return triage(EmailClass.PAYMENT_INQUIRY, "Vendor asks about the status of a payment; no invoice attached")

    if docs:
        skipped = [a for a in attachments if a not in docs]
        extra = f"; skipped non-invoice file(s): {', '.join(skipped)}" if skipped else ""
        n = f"{len(docs)} invoice file(s) attached" if len(docs) > 1 else "1 invoice file attached"
        if _hits(_CREDIT, text) or _CREDIT_NUMBER.search(text):
            return triage(EmailClass.CREDIT_NOTE, f"Credit note wording in subject/body; {n}{extra}", docs)
        return triage(EmailClass.INVOICE, f"{n}{extra}", docs)

    if _hits(_ATTACH_WORDS, text) or _hits(_INVOICE_WORDS, text):
        return triage(EmailClass.MISSING_ATTACHMENT,
                      "Email refers to an attached invoice but has no attachment: ask the vendor to resend")

    return None


# ---------------------------------------------------------------- LLM tie-break

class _LLMTriage(BaseModel):
    email_class: Literal["invoice", "credit_note", "statement", "payment_inquiry", "missing_attachment", "not_ap"]
    reason: str


_LLM_SYSTEM = (
    "You triage emails sent to an accounts-payable inbox. Classify the email into exactly one class: "
    "invoice, credit_note, statement, payment_inquiry, missing_attachment, not_ap. "
    "The subject and body may be in different languages (English/French). "
    "Give a one-sentence reason a clerk can read."
)


def classify(email: dict, client=None) -> EmailTriage:
    """Rules first; LLM only when the rules are unsure and a client/API key is available."""
    result = classify_rules(email)
    if result is not None:
        return result

    eid = email["email_id"]
    try:
        from app.extraction.llm_parser import make_client

        client = client or make_client()
    except Exception:
        return EmailTriage(email_id=eid, email_class=EmailClass.NOT_AP, attachments_to_process=[],
                           reason="No AP signal (no attachment, no invoice wording); LLM tie-break unavailable")

    from app.config import get_settings

    s = get_settings()
    msg = (f"From: {email.get('from_name', '')} <{email.get('from_address', '')}>\n"
           f"Subject: {email.get('subject', '')}\nAttachments: {email.get('attachments') or 'none'}\n\n"
           f"{email.get('body', '')}")
    try:
        resp = client.messages.parse(model=s.llm_model, max_tokens=1024, system=_LLM_SYSTEM,
                                     messages=[{"role": "user", "content": msg}],
                                     output_format=_LLMTriage, output_config={"effort": "low"})
        parsed = resp.parsed_output
    except Exception as exc:
        return EmailTriage(email_id=eid, email_class=EmailClass.NOT_AP, attachments_to_process=[],
                           reason=f"No AP signal; LLM tie-break failed ({type(exc).__name__})")
    if parsed is None:
        return EmailTriage(email_id=eid, email_class=EmailClass.NOT_AP, attachments_to_process=[],
                           reason="No AP signal; LLM tie-break returned nothing")
    cls = EmailClass(parsed.email_class)
    docs = _invoice_attachments(list(email.get("attachments") or []))
    to_process = docs if cls in (EmailClass.INVOICE, EmailClass.CREDIT_NOTE) else []
    return EmailTriage(email_id=eid, email_class=cls, attachments_to_process=to_process,
                       reason=f"(LLM) {parsed.reason}")
