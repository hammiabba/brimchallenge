"""Unreadable files fail cleanly, with one sentence a clerk can act on and no LLM call."""
import pytest

from app.extraction import filecheck, pipeline
from tests.conftest import INCOMING
from tests.extraction.test_pipeline import FakeClient, raw_invoice
from tests.pdfs import invoice_page, make_pdf

GOOD_PDF = make_pdf([invoice_page("A-1001")])
SCAN = (INCOMING / "scan_8049.png").read_bytes()


@pytest.mark.parametrize("data,name,expected", [
    (b"", "invoice.pdf", "empty (0 bytes)"),
    (GOOD_PDF[:300], "invoice.pdf", "damaged"),
    (b"%PDF-1.4\nnot really a pdf\n", "invoice.pdf", "damaged"),
    (b"PK\x03\x04" + b"\0" * 200, "invoice.pdf", "Word/Excel document"),
    (b"\xd0\xcf\x11\xe0" + b"\0" * 200, "invoice.pdf", "old-format Word/Excel"),
    (b"hello, this is text", "invoice.pdf", "not a format we can read"),
    (make_pdf([invoice_page("A-1")], user_password="secret"), "invoice.pdf", "password-protected"),
    (b"\x89PNG\r\n\x1a\n" + b"0" * 64, "scan.png", "image is damaged"),
    (b"hello", "notes.txt", "Unsupported file type .txt"),
    (b"hello", "README", "(no extension)"),
])
def test_problem_messages(data, name, expected):
    msg = filecheck.problem(data, name)
    assert msg and expected in msg
    assert "Traceback" not in msg and "Exception" not in msg


@pytest.mark.parametrize("data,name", [
    (GOOD_PDF, "invoice.pdf"),
    (make_pdf([invoice_page("A-1")], user_password=""), "owner-locked.pdf"),  # opens without a password
    (SCAN, "scan_8049.png"),
    (SCAN, "scan_8049.pdf"),       # a scan saved with the wrong extension is still readable
    (GOOD_PDF, "invoice.png"),
])
def test_readable_files_pass(data, name):
    assert filecheck.problem(data, name) is None


def test_every_sample_file_passes():
    for f in INCOMING.iterdir():
        assert filecheck.problem(f.read_bytes(), f.name) is None, f.name


def test_real_name_routes_by_content():
    assert filecheck.real_name(SCAN, "scan.pdf") == ("scan.pdf.png", "scan.pdf is a PNG image despite its name; "
                                                                     "read as an image")
    assert filecheck.real_name(GOOD_PDF, "x.jpg")[0] == "x.jpg.pdf"
    assert filecheck.real_name(GOOD_PDF, "x.pdf") == ("x.pdf", None)


@pytest.mark.parametrize("data,name,expected", [
    (b"", "empty.pdf", "empty"),
    (make_pdf([invoice_page("A-1")], user_password="secret"), "locked.pdf", "password-protected"),
    (b"PK\x03\x04" + b"\0" * 200, "renamed.pdf", "Word/Excel"),
])
def test_pipeline_fails_cleanly_without_calling_the_llm(repo, data, name, expected):
    client = FakeClient(raw_invoice())
    out = pipeline.extract_outcome(data, name, repo=repo, client=client)
    assert out.status == "failed" and out.draft is None
    assert expected in out.error
    assert len(out.file_hash) == 64  # still hashed, so a resend of the same broken file is recognisable
    assert client.calls == []


def test_pipeline_reads_a_misnamed_pdf(repo):
    client = FakeClient(raw_invoice())
    out = pipeline.extract_outcome(GOOD_PDF, "invoice.png", repo=repo, client=client)
    assert out.status == "ok" and out.text_method == "pdfplumber"
    assert any("is a PDF despite its name" in w for w in out.draft.extraction_warnings)


def test_reader_crash_becomes_a_clean_failure(repo, monkeypatch):
    def boom(*_):
        raise RuntimeError("internal parser state")

    monkeypatch.setattr(pipeline.text_layer, "get_text", boom)
    out = pipeline.extract_outcome(GOOD_PDF, "invoice.pdf", repo=repo, client=FakeClient(raw_invoice()))
    assert out.status == "failed" and "couldn't be read (RuntimeError)" in out.error
