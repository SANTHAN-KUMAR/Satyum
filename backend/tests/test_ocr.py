"""Discrimination tests for the OCR bridge (``forensics.ocr.DocumentParseAnalyzer``).

This module proves the bridge does real work end-to-end, OCR -> arithmetic engine:

  * a GENUINE rendered statement round-trips the right numbers and, fed through the already-built
    ``ArithmeticConsistencyAnalyzer``, **passes** (suspicion 0);
  * a SINGLE-EDITED image (one balance figure changed) is **flagged** with localized evidence —
    the whole point: the verdict moves with the pixels;
  * a heavily-blurred / garbage image yields low confidence -> **NOT_EVALUATED**, publishes no
    statement, and therefore is **never** a false "tampered" (BUILD-MANIFEST OCR honesty guard).

Every fixture is generated programmatically with PIL (no checked-in binary, nothing hand-tuned).
The genuine/tampered pair would FAIL against a constant return (a constant cannot make a genuine
statement pass AND a tampered one flag), satisfying the §3.2 constant-return litmus.

The PDF render path is exercised when PyMuPDF is importable and skipped honestly otherwise (§8:
"can't test it for real yet -> say so", never a shallow proxy).
"""

from __future__ import annotations

import importlib.util
import io
from decimal import Decimal

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from app.contracts import AnalysisContext, Mode, SignalStatus
from forensics.arithmetic import ArithmeticConsistencyAnalyzer, check_consistency
from forensics.ocr import (
    DocumentParseAnalyzer,
    _Column,
    _count_unstructured_money,
    _is_currency_like,
    _ocr_words,
    _Word,
    build_statement,
    is_pdf,
    page_boundary_pairs,
    parse_money,
    text_layer_words,
    text_layer_words_per_page,
)

# --- Fixture generation: a real, monospaced bank-statement table -------------------------------

# Candidate monospace fonts across common Linux distros; fall back to PIL's bitmap font so the
# tests run anywhere. A monospace face keeps column x-positions clean for the table render.
_FONT_CANDIDATES = (
    "/usr/share/fonts/liberation-mono-fonts/LiberationMono-Regular.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    "/usr/share/fonts/dejavu-sans-mono-fonts/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/dejavu/DejaVuSansMono.ttf",
)

# Fixed column x-origins (pixels). Wide gaps so OCR cleanly separates the columns.
_COLS = {"date": 40, "description": 230, "debit": 620, "credit": 830, "balance": 1040}
_HEADERS = (("date", "Date"), ("description", "Description"), ("debit", "Debit"),
            ("credit", "Credit"), ("balance", "Balance"))

# A statement whose arithmetic reconciles exactly:
#   opening 10,000 -> +5,000 -> -2,000 -> +1,000 -> closing 14,000
# totals: debits 2,000 ; credits 6,000. (date, description, debit, credit, balance)
_GENUINE_ROWS = (
    ("02-Apr", "Salary", "", "5,000.00", "15,000.00"),
    ("05-Apr", "Rent", "2,000.00", "", "13,000.00"),
    ("10-Apr", "Refund", "", "1,000.00", "14,000.00"),
)


def _load_font(size: int) -> ImageFont.ImageFont:
    for path in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _render_statement(rows, opening="10,000.00", closing="14,000.00",
                      total_debit="2,000.00", total_credit="6,000.00",
                      font_size: int = 26) -> Image.Image:
    """Render a clean monospaced statement table to a white-background RGB image."""
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
    draw.text((_COLS["balance"], y), opening, fill="black", font=font)
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
    draw.text((_COLS["balance"], y), closing, fill="black", font=font)
    y += 44
    draw.text((_COLS["description"], y), "Total", fill="black", font=font)
    draw.text((_COLS["debit"], y), total_debit, fill="black", font=font)
    draw.text((_COLS["credit"], y), total_credit, fill="black", font=font)
    return img


def _tampered_rows():
    """The genuine rows with ONE balance figure inflated (15,000.00 -> 16,000.00)."""
    rows = [list(r) for r in _GENUINE_ROWS]
    rows[0][4] = "16,000.00"  # the single edit that breaks the running-balance chain
    return [tuple(r) for r in rows]


def _png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _file_ctx(img: Image.Image) -> AnalysisContext:
    return AnalysisContext(
        session_id="t", intake_mode=Mode.FILE, doc_type="financial_statement",
        file_bytes=_png_bytes(img),
    )


# --- 1. Genuine: parse round-trips the right numbers and the arithmetic engine PASSES -----------

def test_genuine_statement_parses_correct_numbers():
    img = _render_statement(_GENUINE_ROWS)
    words = _ocr_words(img)
    stmt = build_statement(words)
    assert stmt is not None, "the clean table must be located and parsed"

    assert stmt.opening_balance == Decimal("10000.00")
    assert stmt.closing_balance == Decimal("14000.00")
    assert stmt.stated_total_debits == Decimal("2000.00")
    assert stmt.stated_total_credits == Decimal("6000.00")

    balances = [t.balance for t in stmt.transactions]
    assert balances == [Decimal("15000.00"), Decimal("13000.00"), Decimal("14000.00")]
    debits = [t.debit for t in stmt.transactions]
    credits = [t.credit for t in stmt.transactions]
    assert debits == [None, Decimal("2000.00"), None]
    assert credits == [Decimal("5000.00"), None, Decimal("1000.00")]
    # every parsed balance carries a locatable evidence box for the underwriter
    assert all(t.balance_bbox is not None for t in stmt.transactions)
    # a clean statement whose figures all land in the table must NOT be flagged incomplete — otherwise
    # the completeness abstain would false-pend a genuine document (the exact failure we must avoid).
    assert stmt.unstructured_money_tokens == 0


# --- Completeness signal: the fingerprint of an incomplete extraction ---------------------------
# A currency-formatted figure the parser could not place into the table means the ledger is
# incomplete, so a downstream imbalance may be an extraction gap (a hidden fee/charge), not fraud.
# These prove the signal is discriminative and conservative (reference numbers never trigger it).


@pytest.mark.parametrize("token,expected", [
    ("1,234.56", True),      # thousands-grouped with a 2-decimal fraction
    ("12,345", True),        # thousands-grouped
    ("2,00,000.00", True),   # Indian grouping
    ("500.00", True),        # bare 2-decimal amount
    ("₹1,500.00", True),     # with a currency marker
    ("1234567", False),      # a bare integer run — a cheque / reference / customer id, NOT money
    ("2026", False),         # a year
    ("ABCDE1234F", False),   # a PAN
    ("", False),
])
def test_is_currency_like_discriminates_money_from_reference_numbers(token, expected):
    assert _is_currency_like(token) is expected


def _w(text: str, left: int) -> _Word:
    # a body word (top well below any header) with a small box; x_center = left + width/2
    return _Word(text=text, left=left, top=500, width=60, height=20, conf=0.9)


def test_count_unstructured_money_flags_out_of_column_amounts_only():
    columns = {
        "date": _Column("date", 0, 100),
        "debit": _Column("debit", 100, 200),
        "balance": _Column("balance", 200, 300),
    }
    header_bottom = 100.0
    words = [
        _w("01-06-2026", 10),     # date column
        _w("2,000.00", 130),      # debit column (in-column money — not counted)
        _w("13,000.00", 230),     # balance column (in-column money — not counted)
        _w("500.00", 400),        # OUT of every column, currency-formatted -> an uncaptured fee
        _w("9876543210", 420),    # OUT of columns but a reference number -> NOT counted
    ]
    # exactly one uncaptured monetary figure; the reference number does not inflate the count
    assert _count_unstructured_money(words, columns, header_bottom) == 1


# --- Born-digital text-layer extraction: exact, OCR-free, VLM-free (ADR-004 Tier 2) -------------
# A born-digital bank PDF carries the exact printed text + geometry. Reading it directly gives the
# deterministic statement parser exact input — no OCR misparse, no VLM/cloud dependency. These prove
# the text-layer path is preferred and parses the EXACT figures, and that it degrades to OCR for scans.

_TL_COLS_PT = {"date": 40, "description": 120, "debit": 300, "credit": 400, "balance": 500}


def _put_table(page, rows, opening, closing, total_debit, total_credit, charge=None, y=50):
    """Insert a statement table onto a pymupdf page at column x-positions; return the next y."""
    for name in ("date", "description", "debit", "credit", "balance"):
        page.insert_text((_TL_COLS_PT[name], y), name.capitalize(), fontsize=10)
    y += 26
    if opening is not None:
        page.insert_text((_TL_COLS_PT["date"], y), "01-Apr", fontsize=10)
        page.insert_text((_TL_COLS_PT["description"], y), "Opening Balance", fontsize=10)
        page.insert_text((_TL_COLS_PT["balance"], y), opening, fontsize=10)
        y += 22
    for date, desc, debit, credit, balance in rows:
        page.insert_text((_TL_COLS_PT["date"], y), date, fontsize=10)
        page.insert_text((_TL_COLS_PT["description"], y), desc, fontsize=10)
        if debit:
            page.insert_text((_TL_COLS_PT["debit"], y), debit, fontsize=10)
        if credit:
            page.insert_text((_TL_COLS_PT["credit"], y), credit, fontsize=10)
        page.insert_text((_TL_COLS_PT["balance"], y), balance, fontsize=10)
        y += 22
    if charge is not None:  # a SUMMARY fee row: label + amount in the debit column, NO running balance
        page.insert_text((_TL_COLS_PT["description"], y), "Service Charges", fontsize=10)
        page.insert_text((_TL_COLS_PT["debit"], y), charge, fontsize=10)
        y += 22
    if closing is not None:
        page.insert_text((_TL_COLS_PT["description"], y), "Closing Balance", fontsize=10)
        page.insert_text((_TL_COLS_PT["balance"], y), closing, fontsize=10)
        y += 22
    if total_debit is not None:
        page.insert_text((_TL_COLS_PT["description"], y), "Total", fontsize=10)
        page.insert_text((_TL_COLS_PT["debit"], y), total_debit, fontsize=10)
        page.insert_text((_TL_COLS_PT["credit"], y), total_credit, fontsize=10)
    return y


def _born_digital_pdf(rows=_GENUINE_ROWS, opening="10,000.00", closing="14,000.00",
                      total_debit="2,000.00", total_credit="6,000.00", charge=None) -> bytes:
    """A one-page PDF with a REAL text layer (pymupdf insert_text), not a raster — born-digital."""
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    _put_table(page, rows, opening, closing, total_debit, total_credit, charge=charge)
    out = doc.tobytes()
    doc.close()
    return out


def _two_page_pdf(page1_closing: str, page2_opening: str) -> bytes:
    """A 2-page born-digital PDF; the zipper checks page-1 closing carries to page-2 opening.

    Page 1 carries two transactions (so its own chain is assertable, as any real statement page is);
    the caller sets the page-1 stated closing and the page-2 stated opening to make the boundary match
    or break.
    """
    import pymupdf

    doc = pymupdf.open()
    p1 = doc.new_page(width=612, height=792)
    _put_table(p1, [("02-Apr", "Salary", "", "5,000.00", "15,000.00"),
                    ("08-Apr", "Bonus", "", "3,000.00", "18,000.00")],
               opening="10,000.00", closing=page1_closing, total_debit=None, total_credit=None)
    p2 = doc.new_page(width=612, height=792)
    _put_table(p2, [("12-Apr", "Rent", "2,000.00", "", "16,000.00")],
               opening=page2_opening, closing="16,000.00", total_debit=None, total_credit=None)
    out = doc.tobytes()
    doc.close()
    return out


def test_text_layer_words_reads_exact_born_digital_geometry():
    words = text_layer_words(_born_digital_pdf())
    assert words is not None and words, "a born-digital PDF must yield text-layer words"
    assert all(w.conf == 1.0 for w in words)  # a text-layer glyph is not a probabilistic read
    texts = {w.text for w in words}
    assert "15,000.00" in texts and "Balance" in texts  # exact strings, not OCR approximations


def test_born_digital_statement_parsed_exactly_from_text_layer():
    words = text_layer_words(_born_digital_pdf())
    assert words is not None
    stmt = build_statement(words)
    assert stmt is not None
    # EXACT figures — no OCR error is possible on a text layer.
    assert stmt.opening_balance == Decimal("10000.00")
    assert stmt.closing_balance == Decimal("14000.00")
    assert [t.balance for t in stmt.transactions] == [
        Decimal("15000.00"), Decimal("13000.00"), Decimal("14000.00")
    ]
    assert stmt.stated_total_debits == Decimal("2000.00")
    assert stmt.stated_total_credits == Decimal("6000.00")


def test_document_parse_prefers_text_layer_and_reconciles():
    """The analyzer sources the statement from the text layer for a born-digital PDF, and it reconciles."""
    ctx = AnalysisContext(
        session_id="t", intake_mode=Mode.FILE, doc_type="financial_statement",
        file_bytes=_born_digital_pdf(),
    )
    sig = DocumentParseAnalyzer().analyze(ctx)
    assert sig.measurements.get("statement_source") == "pdf_text_layer"
    stmt = ctx.shared["statement"]
    result = check_consistency(stmt)
    assert result.evaluated and not result.violations  # exact input -> reconciles, no false flag


def test_text_layer_words_none_for_non_pdf_image():
    # a raster image (no text layer) must return None so the caller falls back to OCR-on-raster
    assert text_layer_words(_png_bytes(_render_statement(_GENUINE_ROWS))) is None


def test_born_digital_stated_charge_extracted_and_reconciles():
    """A summary 'Service Charges' row (fee, no running balance) is captured and folds into the math.

    opening 10,000 -> +5,000 -> -2,000 -> +1,000 (last balance 14,000); a 50 service charge brings the
    closing to 13,950. build_statement must capture stated_charges=50 (NOT as a transaction) and the
    engine must then reconcile cleanly — KNOWN_ISSUES #4 hidden-fee case, end to end from the text layer.
    """
    pdf = _born_digital_pdf(charge="50.00", closing="13,950.00")
    words = text_layer_words(pdf)
    assert words is not None
    stmt = build_statement(words)
    assert stmt is not None
    assert stmt.stated_charges == Decimal("50.00")
    assert len(stmt.transactions) == 3  # the charge is NOT counted as a transaction row
    result = check_consistency(stmt)
    assert result.evaluated and not result.violations  # the stated fee explains the residual -> clean


def test_multipage_zipper_pairs_continuous_and_broken():
    """page_boundary_pairs reads each page's boundary balance; a deleted page breaks continuity."""
    ok_pairs = page_boundary_pairs(text_layer_words_per_page(_two_page_pdf("18,000.00", "18,000.00")))
    assert ok_pairs == [(Decimal("18000.00"), Decimal("18000.00"))]  # closing[1] == opening[2]

    broken_pairs = page_boundary_pairs(text_layer_words_per_page(_two_page_pdf("18,000.00", "9,000.00")))
    assert broken_pairs == [(Decimal("18000.00"), Decimal("9000.00"))]
    # and the engine scores that discontinuity as tampering
    p1_words = text_layer_words(_two_page_pdf("18,000.00", "9,000.00"))
    assert p1_words is not None
    stmt = build_statement(p1_words)
    assert stmt is not None
    stmt.page_boundaries = broken_pairs
    result = check_consistency(stmt)
    assert any(v.kind == "page_zipper" for v in result.violations)


def test_document_parse_populates_page_boundaries_for_multipage():
    ctx = AnalysisContext(
        session_id="t", intake_mode=Mode.FILE, doc_type="financial_statement",
        file_bytes=_two_page_pdf("18,000.00", "18,000.00"),
    )
    sig = DocumentParseAnalyzer().analyze(ctx)
    assert sig.measurements.get("statement_source") == "pdf_text_layer"
    assert sig.measurements.get("page_boundaries_checked") == 1
    assert ctx.shared["statement"].page_boundaries == [(Decimal("18000.00"), Decimal("18000.00"))]


def test_genuine_end_to_end_ocr_then_arithmetic_passes():
    ctx = _file_ctx(_render_statement(_GENUINE_ROWS))

    parse_sig = DocumentParseAnalyzer().analyze(ctx)
    # The bridge extracts; it does not score tampering -> NOT_EVALUATED with a confidence reading.
    assert parse_sig.status == SignalStatus.NOT_EVALUATED
    assert parse_sig.suspicion is None
    assert parse_sig.measurements["ocr_confidence"] > 0.45
    assert isinstance(ctx.shared.get("statement"), type(ctx.shared["statement"]))
    # ctx.shared['ocr'] is the canonical LIST shape the font/layout analyzer consumes (the bridge
    # the review found broken). Assert the real contract: a list of word dicts with full geometry.
    ocr_words = ctx.shared.get("ocr")
    assert isinstance(ocr_words, list) and len(ocr_words) > 0
    assert {"text", "left", "top", "width", "height", "conf", "line_num", "block_num"} <= ocr_words[0].keys()
    assert parse_sig.measurements["word_count"] == len(ocr_words)
    # and the rendered page raster is published so FILE-mode image forensics can run
    assert ctx.shared.get("page_image") is not None

    arith_sig = ArithmeticConsistencyAnalyzer().analyze(ctx)
    assert arith_sig.status == SignalStatus.VALID
    assert arith_sig.suspicion == 0.0  # a genuine statement reconciles -> clean


def test_file_mode_forensics_actually_evaluate_end_to_end():
    """Regression for the review's C2/C3: on a FILE statement the OCR bridge must (C2) feed the
    font/layout analyzer the canonical word-list shape and (C3) publish a page raster so the image
    forensics can run — instead of every CV forensic silently returning NOT_EVALUATED on a real
    upload. A green unit suite missed this because the layout tests injected the list shape directly.
    """
    from forensics.layout import FontLayoutAnalyzer

    ctx = _file_ctx(_render_statement(_GENUINE_ROWS))
    DocumentParseAnalyzer().analyze(ctx)

    # C2 — the bridge published the list shape, so font/layout is applicable and is NOT dead-ended.
    layout = FontLayoutAnalyzer()
    assert layout.applicable(ctx) is True
    assert "no OCR word geometry" not in layout.analyze(ctx).reason
    # C3 — a page raster is published, the prerequisite for FILE-mode image forensics.
    assert ctx.shared.get("page_image") is not None


# --- 2. Adversarial: a single edited image is FLAGGED end-to-end --------------------------------

def test_single_edited_image_is_flagged_end_to_end():
    ctx = _file_ctx(_render_statement(_tampered_rows()))

    parse_sig = DocumentParseAnalyzer().analyze(ctx)
    assert parse_sig.status == SignalStatus.NOT_EVALUATED  # bridge still only extracts
    assert "statement" in ctx.shared, "a confident, located table must still be published"

    arith_sig = ArithmeticConsistencyAnalyzer().analyze(ctx)
    assert arith_sig.status == SignalStatus.VALID
    assert arith_sig.suspicion is not None and arith_sig.suspicion >= 0.85, (
        "one edited balance must break the running-balance chain"
    )
    # the break must be localized to a real cell, traced to the arithmetic detector
    assert arith_sig.evidence_regions, "a caught edit must surface a locatable region"
    kinds = {v["kind"] for v in arith_sig.measurements["violations"]}
    assert "running_balance" in kinds


def test_genuine_vs_tampered_image_discriminate():
    """The core discrimination: identical pipeline, opposite verdicts. Fails against a constant."""
    genuine_ctx = _file_ctx(_render_statement(_GENUINE_ROWS))
    tampered_ctx = _file_ctx(_render_statement(_tampered_rows()))

    DocumentParseAnalyzer().analyze(genuine_ctx)
    DocumentParseAnalyzer().analyze(tampered_ctx)

    genuine = ArithmeticConsistencyAnalyzer().analyze(genuine_ctx)
    tampered = ArithmeticConsistencyAnalyzer().analyze(tampered_ctx)

    assert genuine.status == tampered.status == SignalStatus.VALID
    # No constant return could satisfy both of these at once:
    assert genuine.suspicion == 0.0
    assert tampered.suspicion >= 0.85
    assert tampered.suspicion > genuine.suspicion


# --- 3. Honesty: a garbage / blurred image is NOT_EVALUATED, never a false "tampered" -----------

def _garbage_image() -> Image.Image:
    rng = np.random.default_rng(7)
    noise = rng.integers(0, 256, size=(700, 1000, 3), dtype=np.uint8)
    return Image.fromarray(noise).filter(ImageFilter.GaussianBlur(6))


def test_garbage_image_is_not_evaluated_not_falsely_tampered():
    ctx = _file_ctx(_garbage_image())

    parse_sig = DocumentParseAnalyzer().analyze(ctx)
    assert parse_sig.status == SignalStatus.NOT_EVALUATED
    assert parse_sig.suspicion is None  # never a fabricated pass or fail
    assert "statement" not in ctx.shared, "no statement may be published from unreadable input"

    # And the downstream engine therefore cannot manufacture a tamper verdict from nothing.
    arith_sig = ArithmeticConsistencyAnalyzer().analyze(ctx)
    assert arith_sig.status == SignalStatus.NOT_EVALUATED
    assert arith_sig.suspicion is None


def test_blurred_genuine_statement_below_gate_is_pending_not_tampered():
    """A real statement blurred past readability must read 'pending', not 'tampered' (the §3.4 gate)."""
    blurred = _render_statement(_GENUINE_ROWS).filter(ImageFilter.GaussianBlur(9))
    ctx = _file_ctx(blurred)

    parse_sig = DocumentParseAnalyzer().analyze(ctx)
    if parse_sig.status == SignalStatus.NOT_EVALUATED and "statement" not in ctx.shared:
        # Confidence collapsed or the table could not be located -> honestly pending.
        arith_sig = ArithmeticConsistencyAnalyzer().analyze(ctx)
        assert arith_sig.status in (SignalStatus.NOT_EVALUATED,)
        assert arith_sig.suspicion is None
    else:
        # If it stayed readable, it must still parse as GENUINE (a benign blur is not tampering).
        arith_sig = ArithmeticConsistencyAnalyzer().analyze(ctx)
        assert arith_sig.status == SignalStatus.VALID
        assert arith_sig.suspicion == 0.0


# --- 4. Camera path: a rectified BGR frame is parsed the same way -------------------------------

def test_rectified_camera_frame_is_parsed():
    img = _render_statement(_GENUINE_ROWS)
    rgb = np.asarray(img)
    bgr = rgb[:, :, ::-1].copy()  # OpenCV BGR convention

    ctx = AnalysisContext(session_id="cam", intake_mode=Mode.CAMERA)
    ctx.shared["rectified"] = bgr
    az = DocumentParseAnalyzer()
    assert az.applicable(ctx) is True

    sig = az.analyze(ctx)
    assert sig.status == SignalStatus.NOT_EVALUATED
    assert sig.measurements["source"] == "rectified_crop"
    assert "statement" in ctx.shared

    arith = ArithmeticConsistencyAnalyzer().analyze(ctx)
    assert arith.status == SignalStatus.VALID and arith.suspicion == 0.0


def test_not_applicable_without_any_input():
    az = DocumentParseAnalyzer()
    empty = AnalysisContext(session_id="x", intake_mode=Mode.FILE)
    assert az.applicable(empty) is False


# --- 5. Money parser discrimination (the cell-level primitive) ----------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("10,000.00", Decimal("10000.00")),
    ("₹ 1,23,456.78", Decimal("123456.78")),
    ("Rs. 5,000", Decimal("5000")),
    ("2000.50 Cr", Decimal("2000.50")),
    ("15, 000. 00", Decimal("15000.00")),  # OCR-fragmented figure
    ("-450.00", Decimal("-450.00")),
])
def test_parse_money_reads_real_figures(raw, expected):
    assert parse_money(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "Salary", "N/A", "—", "abc", "12.345.678"])
def test_parse_money_rejects_non_numbers(raw):
    # A non-number must yield None (a MISSING figure), never a fabricated 0 (BUILD-MANIFEST guard).
    assert parse_money(raw) is None


# --- 6. PDF render path (PyMuPDF) — real when available, honestly skipped otherwise -------------

_HAS_PYMUPDF = importlib.util.find_spec("pymupdf") is not None


@pytest.mark.skipif(not _HAS_PYMUPDF, reason="PyMuPDF not installed in this environment")
def test_pdf_intake_renders_and_parses_end_to_end():
    # Wrap the rendered statement raster in a real single-page PDF (Pillow's PDF writer), then drive
    # it through the analyzer's PDF branch (PyMuPDF render -> OCR -> statement).
    img = _render_statement(_GENUINE_ROWS)
    buf = io.BytesIO()
    img.save(buf, format="PDF", resolution=200.0)
    pdf_bytes = buf.getvalue()
    assert is_pdf(pdf_bytes)

    ctx = AnalysisContext(
        session_id="pdf", intake_mode=Mode.FILE, doc_type="financial_statement",
        file_bytes=pdf_bytes,
    )
    parse_sig = DocumentParseAnalyzer().analyze(ctx)
    assert parse_sig.status == SignalStatus.NOT_EVALUATED
    assert parse_sig.measurements["source"] == "pdf_page_1"
    assert "statement" in ctx.shared

    arith = ArithmeticConsistencyAnalyzer().analyze(ctx)
    assert arith.status == SignalStatus.VALID and arith.suspicion == 0.0
