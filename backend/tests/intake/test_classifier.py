import pytest

from app.intake.classifier import classify, classify_rules
from app.intake.inbox import load_emails, process_inbox
from app.shared.schemas import EmailClass


@pytest.fixture(scope="module")
def emails():
    return {e["email_id"]: e for e in load_emails()}


@pytest.mark.parametrize("eid,expected", [
    ("EM-056", EmailClass.STATEMENT),          # "Attached is your statement", no file
    ("EM-057", EmailClass.PAYMENT_INQUIRY),
    ("EM-058", EmailClass.MISSING_ATTACHMENT),
    ("EM-059", EmailClass.NOT_AP),
    ("EM-042", EmailClass.CREDIT_NOTE),        # French subject, CN- number
    ("EM-025", EmailClass.CREDIT_NOTE),
    ("EM-003", EmailClass.INVOICE),            # French body
    ("EM-005", EmailClass.INVOICE),            # "Payment due: invoice ..." with an attachment is an invoice
])
def test_known_emails(emails, eid, expected):
    t = classify(emails[eid])
    assert t.email_class == expected, t.reason
    assert t.reason


def test_two_attachments_two_bills(emails):
    t = classify(emails["EM-029"])
    assert t.email_class == EmailClass.INVOICE
    assert t.attachments_to_process == ["orionstrategypar-inv-029.pdf", "orionstrategypar_281.pdf"]


def test_no_bills_for_non_invoice_classes(emails):
    for eid in ("EM-056", "EM-057", "EM-058", "EM-059"):
        assert classify(emails[eid]).attachments_to_process == []


def test_every_sample_email_is_classified_by_rules(emails):
    # The LLM tie-break should be the exception; on the sample inbox the rules decide everything.
    assert all(classify_rules(e) is not None for e in emails.values())


# --- unseen variants (guards against overfitting to the sample wording)

def mk(subject, body, attachments=(), sender="ar@vendor.example"):
    return {"email_id": "EM-X", "from_address": sender, "subject": subject, "body": body,
            "attachments": list(attachments)}


def test_english_subject_french_body_missing_attachment():
    t = classify(mk("Invoice 123", "Bonjour, veuillez trouver ci-joint notre facture."))
    assert t.email_class == EmailClass.MISSING_ATTACHMENT


def test_french_payment_inquiry():
    t = classify(mk("Paiement facture 88", "Bonjour, nous n'avons pas reçu votre paiement. Où en est le paiement?"))
    assert t.email_class == EmailClass.PAYMENT_INQUIRY


def test_french_statement():
    assert classify(mk("Relevé de compte - octobre", "Voici votre relevé.")).email_class == EmailClass.STATEMENT


def test_credit_note_wording_with_attachment():
    t = classify(mk("Note de crédit 55", "Ci-joint.", ["cn55.pdf"]))
    assert t.email_class == EmailClass.CREDIT_NOTE and t.attachments_to_process == ["cn55.pdf"]


def test_non_invoice_attachment_is_skipped():
    t = classify(mk("Invoice 9", "Attached.", ["inv9.pdf", "terms.docx"]))
    assert t.attachments_to_process == ["inv9.pdf"]
    assert "terms.docx" in t.reason


def test_no_signal_without_llm_falls_back_to_not_ap():
    t = classify(mk("Hello", "Just checking in."))
    assert t.email_class == EmailClass.NOT_AP
    assert "unavailable" in t.reason


def test_process_inbox_one_outcome_per_attachment(emails):
    seen = []

    def fake_extractor(data, name, **kw):
        seen.append((name, kw["email_id"], kw["sender"]))
        from app.extraction.pipeline import ExtractionOutcome
        return ExtractionOutcome(name, "h", "llm_skipped")

    results = process_inbox([emails["EM-029"], emails["EM-058"]], extractor=fake_extractor)
    assert [len(o) for _, o in results] == [2, 0]
    assert seen[0] == ("orionstrategypar-inv-029.pdf", "EM-029", "ar@orionstrategy.example")
