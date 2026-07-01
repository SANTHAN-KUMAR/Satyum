"""Discrimination tests for the document-derived PDF-only red flag (ADR-004 Layer-1 hardening, §3.2).

The flag must be driven by the issuer FOUND IN THE DOCUMENT (metadata + page-1 text), not a
client-supplied hint a forger can omit. Test PDFs are built in-memory with PyMuPDF (real text +
metadata) — no checked-in binaries, no hand-tuning. Every case would FAIL against a constant return.
"""

from __future__ import annotations

import pytest

from app.contracts import AnalysisContext, Mode, SignalStatus

pymupdf = pytest.importorskip("pymupdf")

from verification.provenance import (  # noqa: E402
    PROV_RESULT_SOURCE_AVOIDED,
    PdfOnlyRedFlagAnalyzer,
    detect_issuer,
    extract_issuer_from_document,
)


def _pdf(text: str = "", *, producer: str = "", author: str = "", title: str = "") -> bytes:
    """A one-page PDF carrying ``text`` on page 1 and optional document-info metadata."""
    doc = pymupdf.open()
    page = doc.new_page()
    if text:
        page.insert_text((72, 72), text, fontsize=11)
    meta = dict(doc.metadata or {})
    if producer:
        meta["producer"] = producer
    if author:
        meta["author"] = author
    if title:
        meta["title"] = title
    if producer or author or title:
        doc.set_metadata(meta)
    out = doc.tobytes()
    doc.close()
    return out


def _ctx(pdf: bytes, *, provenance_verified: bool = False, source_was_pullable: bool = False):
    ctx = AnalysisContext(
        session_id="t",
        intake_mode=Mode.FILE,
        file_bytes=pdf,
        file_name="doc.pdf",
        file_mime="application/pdf",
        source_was_pullable=source_was_pullable,
    )
    if provenance_verified:
        ctx.shared["provenance_verified"] = True
    return ctx


# --- detect_issuer: pure string logic -------------------------------------------------------------


def test_detect_issuer_names_and_keys():
    assert detect_issuer("ACCOUNT STATEMENT — State Bank of India, Mumbai") == "sbi"
    assert detect_issuer("Canara Bank e-statement") == "canara"
    assert detect_issuer("statement from HDFC for the period") == "hdfc"
    assert detect_issuer("Acme Widgets Pvt Ltd — tax invoice") is None
    # short key matches only as a whole word (no false positive inside another token)
    assert detect_issuer("the axisymmetric stress report") is None
    assert detect_issuer("branch code AXIS / 0042") == "axis"


def test_detect_issuer_masthead_wins_over_an_incidental_transaction_line():
    """KNOWN_ISSUES #5.3: a genuine Canara statement with an HDFC UPI line is Canara, not HDFC.

    The masthead issuer is printed at the top; a competitor name only appears deep in a transaction
    row. The earliest-appearing name must win. FAILS against the old first-in-registry-order logic
    (which returned 'hdfc' regardless of where in the document it appeared).
    """
    statement = (
        "CANARA BANK — Account Statement\n"
        "Branch: MG Road  Period: 01-06-2026 to 30-06-2026\n"
        "01-06-2026  UPI/HDFC BANK/9876543210/Rent   -15000.00\n"
        "05-06-2026  NEFT/ICICI BANK/salary          +80000.00\n"
    )
    assert detect_issuer(statement) == "canara"
    # And the reverse: an HDFC statement mentioning Canara lower down stays HDFC.
    reversed_stmt = (
        "HDFC BANK Ltd — e-Statement\n"
        "10-06-2026  IMPS/CANARA BANK/transfer  -2000.00\n"
    )
    assert detect_issuer(reversed_stmt) == "hdfc"


# --- extract_issuer_from_document: real PDFs ------------------------------------------------------


def test_extract_from_page_text():
    key, ev = extract_issuer_from_document(_pdf("State Bank of India\nAccount Statement\n"))
    assert key == "sbi" and ev == "document"


def test_extract_from_metadata_only():
    key, ev = extract_issuer_from_document(_pdf("Monthly Statement\nPage 1 of 3", producer="HDFC Bank Ltd"))
    assert key == "hdfc" and ev == "document"


def test_extract_none_for_unknown_issuer():
    key, _ = extract_issuer_from_document(_pdf("Acme Widgets Pvt Ltd invoice #42"))
    assert key is None


def test_extract_none_for_non_pdf():
    key, _ = extract_issuer_from_document(b"\x89PNG\r\n\x1a\n not a pdf at all")
    assert key is None


def test_extract_none_for_empty():
    assert extract_issuer_from_document(b"")[0] is None
    assert extract_issuer_from_document(None)[0] is None


# --- the analyzer decision ------------------------------------------------------------------------


def test_sourceable_unsigned_raises_flag():
    sig = PdfOnlyRedFlagAnalyzer().analyze(_ctx(_pdf("State Bank of India — Account Statement")))
    assert sig.status == SignalStatus.VALID
    assert sig.suspicion is not None and sig.suspicion > 0
    assert sig.measurements["red_flag"] == "pdf_only_when_pullable"
    assert sig.measurements["issuer"] == "sbi"
    assert sig.measurements["issuer_evidence"] == "document"
    assert sig.measurements["provenance_result"] == PROV_RESULT_SOURCE_AVOIDED


def test_unknown_issuer_no_flag():
    sig = PdfOnlyRedFlagAnalyzer().analyze(_ctx(_pdf("Acme Widgets Pvt Ltd invoice")))
    assert sig.status == SignalStatus.NOT_EVALUATED
    assert sig.suspicion is None


def test_verified_provenance_suppresses_flag():
    sig = PdfOnlyRedFlagAnalyzer().analyze(_ctx(_pdf("Canara Bank statement"), provenance_verified=True))
    assert sig.status == SignalStatus.NOT_EVALUATED
    assert "no avoidance" in sig.reason.lower()


def test_flag_fires_without_client_hint():
    """The hardening: a sourceable issuer in the DOCUMENT raises the flag even with NO client hint.

    Would FAIL against the old behaviour (which keyed solely on the omittable client field).
    """
    sig = PdfOnlyRedFlagAnalyzer().analyze(
        _ctx(_pdf("PUNJAB NATIONAL BANK\nStatement of Account"), source_was_pullable=False)
    )
    assert sig.status == SignalStatus.VALID
    assert sig.measurements["issuer"] == "pnb"
    assert sig.measurements["issuer_evidence"] == "document"


def test_discrimination_pair():
    """Same structure, only the issuer text differs -> flag vs no-flag. Fails against any constant."""
    az = PdfOnlyRedFlagAnalyzer()
    flagged = az.analyze(_ctx(_pdf("ICICI Bank — Account Statement")))
    clean = az.analyze(_ctx(_pdf("Nobody & Co — a random document")))
    assert flagged.status == SignalStatus.VALID and flagged.suspicion is not None
    assert clean.status == SignalStatus.NOT_EVALUATED


def test_image_falls_back_to_capability_hint():
    """Media with no readable text layer (an image): the analyzer falls back to the capability hint."""
    az = PdfOnlyRedFlagAnalyzer()
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    with_hint = az.analyze(_ctx(png, source_was_pullable=True))
    without = az.analyze(_ctx(png, source_was_pullable=False))
    assert with_hint.status == SignalStatus.VALID
    assert with_hint.measurements["issuer_evidence"] == "issuer-capability hint"
    assert without.status == SignalStatus.NOT_EVALUATED


def test_protocol_attributes():
    az = PdfOnlyRedFlagAnalyzer()
    assert az.name == "pdf_only_red_flag"
    assert az.layer == 1
    assert az.mode == Mode.FILE
    assert az.order == 20
