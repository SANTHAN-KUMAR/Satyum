"""Discrimination tests for the realistic "hard corpus" (samples/hard/* and realistic_fixtures.py).

These prove the analyzers catch fraud on documents that LOOK legitimate — not just toy renders — so
the demo corpus is adversarial evidence, not scaffolding (CLAUDE.md §3.2/§8). Each pair would FAIL
against a constant return (a constant cannot pass the genuine artifact AND flag the forged one):

  * a professional multi-transaction statement that reconciles -> arithmetic VALID, suspicion 0;
  * the same with one income figure inflated -> arithmetic flags it with the exact broken invariants;
  * the statement PAdES-signed by the pinned demo CA -> Tier-1 source-verified;
  * the signed statement with a post-signing incremental edit -> Tier-1 tampered (coverage broken).

Fully synthetic and reproducible (no checked-in binary is required to run these; nothing hand-tuned).
"""

from __future__ import annotations

import importlib.util
import io
from pathlib import Path

import pytest

from app.contracts import AnalysisContext, Mode, SignalStatus
from forensics.arithmetic import ArithmeticConsistencyAnalyzer
from forensics.ocr import DocumentParseAnalyzer
from tests.realistic_fixtures import render_realistic_statement, statement_pdf_bytes
from tests.test_signature import _make_ca, _make_leaf, _sign_pdf

_TESSERACT = importlib.util.find_spec("pytesseract") is not None
_FITZ = importlib.util.find_spec("fitz") is not None


def _png(img) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _file_ctx(data: bytes, mime: str, name: str) -> AnalysisContext:
    return AnalysisContext(
        session_id="t", intake_mode=Mode.FILE, doc_type="financial_statement",
        file_bytes=data, file_name=name, file_mime=mime,
    )


def _arith_signal(png: bytes):
    """Run the real OCR -> arithmetic waterfall on a statement image; return the arithmetic signal."""
    ctx = _file_ctx(png, "image/png", "statement.png")
    DocumentParseAnalyzer().analyze(ctx)  # publishes ctx.shared['statement']
    return ArithmeticConsistencyAnalyzer().analyze(ctx)


# --- the realistic arithmetic pair (the income-inflation forgery) ------------------------------

@pytest.mark.skipif(not _TESSERACT, reason="tesseract OCR binary not available")
def test_realistic_genuine_statement_reconciles():
    sig = _arith_signal(_png(render_realistic_statement(tamper=False)))
    assert sig.status == SignalStatus.VALID
    assert sig.suspicion == 0.0, sig.reason
    assert not sig.measurements.get("violations")


@pytest.mark.skipif(not _TESSERACT, reason="tesseract OCR binary not available")
def test_realistic_tampered_statement_breaks_invariants():
    sig = _arith_signal(_png(render_realistic_statement(tamper=True)))
    assert sig.status == SignalStatus.VALID
    assert sig.suspicion >= 0.85, sig.reason
    kinds = {v["kind"] for v in sig.measurements["violations"]}
    # The inflated income figure must break the running-balance chain AND the credit total.
    assert "running_balance" in kinds, kinds
    assert "total_credits" in kinds, kinds


@pytest.mark.skipif(not _TESSERACT, reason="tesseract OCR binary not available")
def test_realistic_pair_would_fail_against_a_constant():
    """The §3.2 litmus on the realistic corpus: genuine clean < tampered flagged, strictly."""
    genuine = _arith_signal(_png(render_realistic_statement(tamper=False)))
    tampered = _arith_signal(_png(render_realistic_statement(tamper=True)))
    assert (genuine.suspicion or 0.0) < (tampered.suspicion or 0.0)


# --- the signed statement + shadow attack (Tier-1 on a document that looks legitimate) ---------

def _append_after_signature(signed_pdf: bytes) -> bytes:
    from pyhanko.pdf_utils import generic
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter

    iw = IncrementalPdfFileWriter(io.BytesIO(signed_pdf))
    iw.add_object(generic.TextStringObject("post-signing edit"))
    out = io.BytesIO()
    iw.write(out)
    return out.getvalue()


@pytest.fixture(scope="module")
def signed_statement():
    """(ca_pem, signed_pdf, shadow_pdf) for a PAdES-signed realistic statement + its shadow attack."""
    if not _FITZ:
        pytest.skip("PyMuPDF (fitz) not available")
    from cryptography.hazmat.primitives import serialization

    ca_key, ca_cert = _make_ca("Satyum DEMO Root CA (stand-in for CCA-India)")
    leaf_key, leaf_cert = _make_leaf(ca_key, ca_cert, "estatements.demo-bank.example")
    pdf = statement_pdf_bytes(render_realistic_statement(tamper=False))
    signed = _sign_pdf(pdf, leaf_key, leaf_cert, ca_cert)
    return (
        ca_cert.public_bytes(serialization.Encoding.PEM),
        signed,
        _append_after_signature(signed),
    )


def _sig_analyzer(tmp_path: Path, ca_pem: bytes):
    from verification.signature import PadesSignatureAnalyzer

    (tmp_path / "root.pem").write_bytes(ca_pem)
    return PadesSignatureAnalyzer(anchor_dir=str(tmp_path))


def test_signed_statement_pdf_is_source_verified(tmp_path, signed_statement):
    ca_pem, signed, _shadow = signed_statement
    sig = _sig_analyzer(tmp_path, ca_pem).analyze(
        _file_ctx(signed, "application/pdf", "statement.pdf")
    )
    assert sig.status == SignalStatus.VALID
    assert sig.suspicion == 0.0, sig.reason
    assert sig.measurements["signatures"][0]["covers_whole_file"] is True


def test_shadow_attacked_signed_statement_is_tampered(tmp_path, signed_statement):
    """The must-fail fixture on a realistic doc: a post-signing edit breaks /ByteRange coverage."""
    ca_pem, _signed, shadow = signed_statement
    sig = _sig_analyzer(tmp_path, ca_pem).analyze(
        _file_ctx(shadow, "application/pdf", "statement.pdf")
    )
    assert sig.suspicion == 1.0, sig.reason
    assert sig.measurements["signatures"][0]["covers_whole_file"] is False
