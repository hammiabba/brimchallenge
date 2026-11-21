from datetime import date
from decimal import Decimal as D

import pytest

from app.intake.actions import (
    ActionKind,
    email_language,
    invoice_refs,
    invoice_status,
    suggest_action,
    vendor_candidates,
)
from app.intake.classifier import classify
from app.intake.inbox import load_emails


@pytest.fixture(scope="module")
def emails():
    return {e["email_id"]: e for e in load_emails()}


def act(email, repo):
    return suggest_action(email, classify(email), repo)


def mk(subject, body, attachments=(), sender="ar@vendor.example", name="Some Vendor"):
    return {"email_id": "EM-X", "from_name": name, "from_address": sender, "subject": subject, "body": body,
            "attachments": list(attachments)}


# ---------------------------------------------------------------- the four non-invoice sample emails

def test_em057_payment_inquiry_answered_from_payment_history(emails, repo):
    # Torque invoice 1743 = AP-00049, paid by EFT on 2026-03-09 (PAY-00047, BRIM-EFT-26388945).
    a = act(emails["EM-057"], repo)
    assert a.kind == ActionKind.ANSWER_STATUS
    assert a.vendor_id == "V044"
    st = a.invoice_status
    assert (st.invoice_id, st.status, st.total, st.invoice_date) == ("AP-00049", "paid", D("369.75"), date(2026, 2, 4))
    [p] = st.payments
    assert (p.payment_id, p.method, p.paid_date, p.reference) == ("PAY-00047", "EFT", date(2026, 3, 9),
                                                                   "BRIM-EFT-26388945")
    assert "paid on 2026-03-09 by EFT, reference BRIM-EFT-26388945" in a.message
    assert "2026-11-02" in a.message  # answers are as of the dataset date
    assert a.language == "en" and "BRIM-EFT-26388945" in a.reply_text
    assert "350265306" not in a.reply_text  # Torque's bank account never goes in a reply


def test_em058_missing_attachment_gets_a_resend_reply(emails, repo):
    a = act(emails["EM-058"], repo)
    assert a.kind == ActionKind.REQUEST_RESEND
    assert a.language == "en" and "resend" in a.reply_text and "Invoice attached" in a.reply_text


def test_em056_statement_is_reconciled_later_with_no_reply(emails, repo):
    a = act(emails["EM-056"], repo)
    assert a.kind == ActionKind.RECONCILE_LATER
    assert a.vendor_id == "V001" and a.reply_text is None  # Polar Freight


def test_em059_marketing_is_ignored(emails, repo):
    a = act(emails["EM-059"], repo)
    assert a.kind == ActionKind.IGNORE and a.reply_text is None
    assert a.vendor_id == "V025"  # Deskhive is a real vendor; its newsletter is still not AP


def test_invoice_emails_create_one_draft_per_attachment(emails, repo):
    a = act(emails["EM-029"], repo)
    assert a.kind == ActionKind.CREATE_DRAFTS
    assert "2 draft bill(s)" in a.message and "orionstrategypar_281.pdf" in a.message


def test_every_sample_email_gets_an_action(emails, repo):
    kinds = {eid: act(e, repo).kind for eid, e in emails.items()}
    assert set(kinds.values()) == set(ActionKind)
    assert sum(k == ActionKind.CREATE_DRAFTS for k in kinds.values()) == 55


# ---------------------------------------------------------------- unseen variants

def test_french_missing_attachment_reply_is_in_french(repo):
    a = act(mk("Facture 2291", "Bonjour, veuillez trouver ci-joint notre facture. Merci."), repo)
    assert a.kind == ActionKind.REQUEST_RESEND
    assert a.language == "fr" and a.reply_text.startswith("Bonjour") and "renvoyer" in a.reply_text


def test_french_inquiry_reply_in_french_with_payment_reference(repo):
    email = mk("Paiement facture 1743", "Bonjour, nous n'avons pas reçu votre paiement pour la facture 1743. "
               "Où en est le paiement?", sender="ar@torqueindustrial.example")
    a = act(email, repo)
    assert a.kind == ActionKind.ANSWER_STATUS and a.language == "fr"
    assert "payée le 2026-03-09" in a.reply_text and "BRIM-EFT-26388945" in a.reply_text


def test_unknown_invoice_number_says_not_found_and_asks_for_a_copy(repo):
    email = mk("Payment status", "Where is payment for invoice 99999?", sender="ar@torqueindustrial.example")
    a = act(email, repo)
    assert a.invoice_status.status == "not_found"
    assert "No invoice 99999" in a.message and "copy" in a.reply_text


def test_unknown_sender_is_not_answered(repo):
    a = act(mk("Payment status", "Where is payment for invoice 1743?", sender="ar@stranger.example",
               name="Stranger Co"), repo)
    assert a.kind == ActionKind.ANSWER_STATUS
    assert a.vendor_id is None and a.invoice_status is None and a.reply_text is None
    assert "identify the vendor" in a.message


def test_inquiry_without_invoice_number_asks_which_one(repo):
    a = act(mk("Payment status", "We have not seen payment yet. Could you confirm the status?",
               sender="ar@torqueindustrial.example"), repo)
    assert a.invoice_status is None and "no invoice number" in a.message


def test_same_number_from_another_vendor_is_not_used(repo):
    # 1743 exists for Torque (V044); asked by Polar Freight, it must not answer with Torque's invoice.
    a = act(mk("Payment status", "Where is payment for invoice 1743?", sender="ar@polarfreight.example",
               name="Polar Freight Lines Ltd."), repo)
    assert a.vendor_id == "V001" and a.invoice_status.status == "not_found"


def test_shared_ap_address_resolved_by_the_invoice_number(repo):
    # V001 and V051 share ar@polarfreight.example; only V001 has invoice 000961.
    a = act(mk("Payment status", "Where is payment for invoice 000961?", sender="ar@polarfreight.example",
               name="Accounts"), repo)
    assert a.vendor_id == "V001" and a.invoice_status.invoice_id == "AP-00393"
    assert "2 vendor records" in a.message


def test_shared_ap_address_without_a_known_invoice_is_not_answered(repo):
    a = act(mk("Payment status", "Where is payment for invoice 99999?", sender="ar@polarfreight.example",
               name="Accounts"), repo)
    assert a.vendor_id is None and a.invoice_status is None and "Identify the vendor" in a.message


def test_reformatted_number_matches_by_digits(repo):
    vendor = repo.vendor("V044")
    st = invoice_status(vendor, "INV-001743", "", repo)
    assert st.invoice_id == "AP-00049"


@pytest.mark.parametrize("status", ["scheduled", "approved", "rejected"])
def test_every_history_status_has_a_summary(repo, status):
    inv = repo.invoices()
    counts = inv.groupby(["vendor_id", "vendor_invoice_number"])["invoice_id"].transform("count")
    row = inv[(inv["status"] == status) & (counts == 1)].iloc[0]
    st = invoice_status(repo.vendor(row["vendor_id"]), row["vendor_invoice_number"], "", repo)
    assert st.status == status and st.summary.startswith(f"Invoice {row['vendor_invoice_number']}")


def test_outstanding_cheque_is_reported_as_not_cashed(repo):
    pays = repo.payments()
    p = pays[pays["status"] == "outstanding"].iloc[0]
    inv = repo.invoices().set_index("invoice_id").loc[p["invoice_id"]]
    st = invoice_status(repo.vendor(inv["vendor_id"]), inv["vendor_invoice_number"], "", repo)
    assert "has not been cashed yet" in st.summary


@pytest.mark.parametrize("text,expected", [
    ("Where is payment for invoice 1743?", ["1743"]),
    ("facture n° FA-000583 du 2026-03-01", ["FA-000583"]),
    ("Invoice #INV-01561 and invoice no. 2203", ["INV-01561", "2203"]),
    ("invoice 1743 dated 2026-02-04", ["1743"]),
    ("our invoice is late", []),
])
def test_invoice_refs(text, expected):
    assert invoice_refs(text) == expected


def test_resubmitted_number_answers_for_the_live_invoice(repo):
    # GR26-2821 (V037) is in history twice: AP-00026 rejected, AP-00007 paid.
    st = invoice_status(repo.vendor("V037"), "GR26-2821", "", repo)
    assert st.invoice_id == "AP-00007" and st.status == "paid"


def test_vendor_identified_by_name_when_address_unknown(repo):
    [v], how = vendor_candidates(mk("x", "y", sender="someone@gmail.example",
                                    name="Torque Industrial Maintenance"), repo)
    assert v["vendor_id"] == "V044" and how.startswith("sender name")


def test_shared_address_split_by_sender_name(repo):
    [v], how = vendor_candidates(mk("x", "y", sender="ar@polarfreight.example",
                                    name="Polar Freight Lines Limited"), repo)
    assert v["vendor_id"] == "V051" and "and name" in how


def test_email_language():
    assert email_language(mk("Invoice", "Hello, please find it attached.")) == "en"
    assert email_language(mk("Invoice 12", "Bonjour, veuillez trouver la facture.")) == "fr"
