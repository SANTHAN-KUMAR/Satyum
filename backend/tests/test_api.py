"""API-layer discrimination + robustness tests for POST /api/verify (and friends).

These prove the *wired* system — route → SessionManager → orchestrator → real analyzers → risk engine
→ TrustScore JSON — actually separates genuine from tampered, and that the ingestion guards reject
hostile uploads at the boundary (CLAUDE.md §10).

Discrimination (the §3.2 core): a genuine rendered statement PDF/PNG flows through the REAL
OCR→arithmetic waterfall and returns an APPROVED verdict; a single-balance-edited copy returns a
flagged (REJECTED/REVIEW) verdict with tamper-evidence regions. No constant return can satisfy both,
so the pair would FAIL against a constant — the litmus.

We mount the real route on an app whose registry holds the real ``DocumentParseAnalyzer`` +
``ArithmeticConsistencyAnalyzer`` (the production classes). This keeps the test deterministic and
free of the Tier-1 crypto deps (pyHanko/c2pa) while still exercising the genuine end-to-end path. The
full ``build_registry()`` is import-checked separately. The OCR path needs the system ``tesseract``
binary; the discrimination tests skip honestly if it (or Pillow rendering) is unavailable (§8).
"""

from __future__ import annotations

import importlib.util
import io

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont

from app.config import settings
from app.registry import AnalyzerRegistry
from app.routes.verify import router as verify_router
from app.session import SessionManager
from forensics.arithmetic import ArithmeticConsistencyAnalyzer
from forensics.ocr import DocumentParseAnalyzer
from risk.audit import AuditLedger

_TESSERACT = importlib.util.find_spec("pytesseract") is not None


# --- real statement fixture (rendered with PIL; nothing checked in / hand-tuned) ---------------

_FONT_CANDIDATES = (
    "/usr/share/fonts/liberation-mono-fonts/LiberationMono-Regular.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    "/usr/share/fonts/dejavu-sans-mono-fonts/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/dejavu/DejaVuSansMono.ttf",
)
_COLS = {"date": 40, "description": 230, "debit": 620, "credit": 830, "balance": 1040}
_HEADERS = (("date", "Date"), ("description", "Description"), ("debit", "Debit"),
            ("credit", "Credit"), ("balance", "Balance"))

# opening 10,000 -> +5,000 -> -2,000 -> +1,000 -> closing 14,000; debits 2,000; credits 6,000.
_GENUINE_ROWS = (
    ("02-Apr", "Salary", "", "5,000.00", "15,000.00"),
    ("05-Apr", "Rent", "2,000.00", "", "13,000.00"),
    ("10-Apr", "Refund", "", "1,000.00", "14,000.00"),
)


def _load_font(size: int):
    for path in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _render_statement(rows, font_size: int = 26) -> Image.Image:
    font = _load_font(font_size)
    width = 1300
    height = 120 + (len(rows) + 5) * 44
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)

    y = 40
    for name, label in _HEADERS:
        draw.text((_COLS[name], y), label, fill="black", font=font)
    y += 60

    draw.text((_COLS["date"], y), "01-Apr", fill="black", font=font)
    draw.text((_COLS["description"], y), "Opening Balance", fill="black", font=font)
    draw.text((_COLS["balance"], y), "10,000.00", fill="black", font=font)
    y += 44

    for date, desc, debit, credit, balance in rows:
        draw.text((_COLS["date"], y), date, fill="black", font=font)
        draw.text((_COLS["description"], y), desc, fill="black", font=font)
        if debit:
            draw.text((_COLS["debit"], y), debit, fill="black", font=font)
        if credit:
            draw.text((_COLS["credit"], y), credit, fill="black", font=font)
        draw.text((_COLS["balance"], y), balance, fill="black", font=font)
        y += 44

    draw.text((_COLS["description"], y), "Closing Balance", fill="black", font=font)
    draw.text((_COLS["balance"], y), "14,000.00", fill="black", font=font)
    y += 44
    draw.text((_COLS["description"], y), "Total", fill="black", font=font)
    draw.text((_COLS["debit"], y), "2,000.00", fill="black", font=font)
    draw.text((_COLS["credit"], y), "6,000.00", fill="black", font=font)
    return img


def _tampered_rows():
    rows = [list(r) for r in _GENUINE_ROWS]
    rows[0][4] = "16,000.00"  # ONE edited balance — breaks the running-balance chain
    return [tuple(r) for r in rows]


def _png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_app() -> FastAPI:
    """The real route mounted on a forensic-subset registry (OCR + arithmetic), with shared state."""
    app = FastAPI()
    app.state.ledger = AuditLedger()
    registry = AnalyzerRegistry()
    registry.register(DocumentParseAnalyzer())        # publishes ctx.shared['statement']
    registry.register(ArithmeticConsistencyAnalyzer())  # scores the consistency tamper signal
    app.state.registry = registry
    app.state.sessions = SessionManager()
    app.include_router(verify_router)
    return app


@pytest.fixture()
def client() -> TestClient:
    return TestClient(_make_app())


# --- 1. Discrimination: genuine -> APPROVED, tampered -> flagged --------------------------------

@pytest.mark.skipif(not _TESSERACT, reason="tesseract OCR not available")
def test_genuine_statement_routes_to_review(client: TestClient):
    # ADR-004 §7 #2: a lone unsigned statement image with clean arithmetic but no cross-source
    # corroboration and no provenance is indeterminate -> REVIEW, never auto-APPROVE. The arithmetic
    # engine still runs and finds no violation; what is missing is corroboration, not integrity.
    png = _png_bytes(_render_statement(_GENUINE_ROWS))
    resp = client.post(
        "/api/verify",
        files={"file": ("statement.png", png, "image/png")},
        data={"doc_type": "financial_statement"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["verdict"] == "REVIEW"
    # the arithmetic engine actually ran and found no violation (clean, but not sufficient alone)
    arith = [s for s in body["signals"] if s["name"] == "arithmetic_consistency"]
    assert arith and arith[0]["status"] == "VALID" and arith[0]["suspicion"] == 0.0


@pytest.mark.skipif(not _TESSERACT, reason="tesseract OCR not available")
def test_tampered_statement_is_flagged_with_evidence(client: TestClient):
    png = _png_bytes(_render_statement(_tampered_rows()))
    resp = client.post(
        "/api/verify",
        files={"file": ("statement.png", png, "image/png")},
        data={"doc_type": "financial_statement"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["verdict"] in ("REJECTED", "REVIEW")  # not APPROVED
    arith = [s for s in body["signals"] if s["name"] == "arithmetic_consistency"]
    assert arith and arith[0]["status"] == "VALID" and arith[0]["suspicion"] > 0.5
    # the evidence pack must surface the tampered region (provenance to a real detector)
    assert body["evidence_pack"]["tamper_evidence_regions"], "tamper must surface evidence regions"


# --- 2. Ingestion guards (run BEFORE any analyzer; no heavy deps) -------------------------------

def test_oversized_upload_is_rejected(client: TestClient):
    # One byte over the cap — must be rejected at the boundary, never parsed (§10).
    payload = b"%PDF-1.4\n" + b"0" * (settings.max_file_bytes + 1)
    resp = client.post(
        "/api/verify",
        files={"file": ("big.pdf", payload, "application/pdf")},
    )
    assert resp.status_code == 413


def test_non_document_upload_is_rejected(client: TestClient):
    # A text/JSON blob is not a PDF or image: rejected by the content-type + magic-byte guards.
    resp = client.post(
        "/api/verify",
        files={"file": ("notes.txt", b"this is not a document", "text/plain")},
    )
    assert resp.status_code in (415, 400)


def test_disguised_non_document_is_rejected_by_magic_bytes(client: TestClient):
    # Declared as PDF but the bytes are not — the magic-byte sniff must catch the lie.
    resp = client.post(
        "/api/verify",
        files={"file": ("fake.pdf", b"GIF89a not really a pdf", "application/pdf")},
    )
    assert resp.status_code == 415


def test_empty_upload_is_rejected(client: TestClient):
    resp = client.post(
        "/api/verify",
        files={"file": ("empty.pdf", b"", "application/pdf")},
    )
    assert resp.status_code == 400


def test_missing_file_field_is_422(client: TestClient):
    # No multipart file part at all -> FastAPI validation error at the boundary.
    resp = client.post("/api/verify", data={"doc_type": "financial_statement"})
    assert resp.status_code == 422


# --- 3. Session + audit wiring -----------------------------------------------------------------

@pytest.mark.skipif(not _TESSERACT, reason="tesseract OCR not available")
def test_verdict_is_recorded_in_the_tamper_evident_audit_chain():
    app = _make_app()
    client = TestClient(app)
    png = _png_bytes(_render_statement(_GENUINE_ROWS))
    resp = client.post(
        "/api/verify",
        files={"file": ("statement.png", png, "image/png")},
    )
    assert resp.status_code == 200
    ok, broken = app.state.ledger.verify_chain()
    assert ok and broken is None
    assert app.state.ledger.records(), "the verdict must be appended to the audit ledger"


def test_unknown_session_is_404(client: TestClient):
    resp = client.get("/api/session/does-not-exist")
    assert resp.status_code == 404


@pytest.mark.skipif(not _TESSERACT, reason="tesseract OCR not available")
def test_file_bytes_are_released_after_scoring(client: TestClient):
    # Privacy (§10): the route nulls ctx.file_bytes after scoring. We assert the session no longer
    # holds the document bytes (defence against accidental retention).
    app = _make_app()
    client = TestClient(app)
    png = _png_bytes(_render_statement(_GENUINE_ROWS))
    resp = client.post("/api/verify", files={"file": ("s.png", png, "image/png")})
    sid = resp.json()["session_id"]
    ctx = app.state.sessions.get(sid)
    assert ctx is not None
    assert ctx.file_bytes is None, "document bytes must not be retained after scoring"


# --- 4. Honest non-coverage: the full registry imports cleanly (integration guard) --------------

def test_full_registry_assembles_or_reports_missing_analyzer():
    """``build_registry()`` must import every analyzer. If a heavy dep is absent in this env the
    import fails loudly here (an integration error to surface), never silently dropping a detector.
    """
    pytest.importorskip("pikepdf", reason="Tier-2 metadata dep not installed in this environment")
    pytest.importorskip("pyhanko", reason="Tier-1 crypto dep not installed in this environment")
    pytest.importorskip("c2pa", reason="Tier-1 C2PA dep not installed in this environment")
    pytest.importorskip("imagehash", reason="pHash dep not installed in this environment")
    pytest.importorskip("fitz", reason="PyMuPDF dep not installed in this environment")
    pytest.importorskip("skimage", reason="scikit-image dep not installed in this environment")

    from app.registry_assembly import build_registry

    reg = build_registry()
    names = {a.name for a in reg.all()}
    # every assigned analyzer must be present
    expected = {
        "pades_signature", "c2pa_provenance", "pdf_only_red_flag",
        "document_parse", "arithmetic_consistency", "pdf_structure_metadata",
        "template_fingerprint", "font_layout", "copy_move", "phash_resubmission",
        "capture_rectify_quality", "antispoof_spectral_moire", "antispoof_specular_glare",
        "antispoof_temporal_entropy", "active_challenge",
    }
    assert expected <= names, f"missing analyzers: {expected - names}"
