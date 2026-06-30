"""Realistic adversarial document fixtures — the "hard corpus" for demos and discrimination tests.

The toy ``_render_statement`` in ``test_ocr`` proves the engine *logic*; these build documents that
LOOK like real bank artifacts so a skeptical reviewer believes the system survives real fraud, while
staying fully synthetic and reproducible (no customer data, nothing hand-tuned — CLAUDE.md §3.2/§10):

  * a professional-looking multi-transaction **statement that reconciles exactly** (genuine), and
  * the same statement with **one income figure surgically inflated** so it still looks clean to the
    eye but breaks the running-balance / totals / net-reconciliation invariants (the classic
    income-inflation forgery), and
  * the statement rendered into a **PDF** so it can be PAdES-signed (Tier-1 source verification) and
    then shadow-attacked (a post-signing incremental edit).

Imported by both ``samples/generate.py`` (writes the drag-and-drop corpus) and ``test_hard_fixtures``
(asserts the real pipeline catches them). The numbers are computed with ``Decimal`` so the genuine
statement reconciles to the cent and the tamper provably breaks an invariant — not the other way round.
"""

from __future__ import annotations

import io
from decimal import Decimal

from PIL import Image, ImageDraw

try:  # pytest imports this as a package (tests.realistic_fixtures); generate.py as a top-level module
    from tests.test_ocr import _load_font
except ModuleNotFoundError:  # noqa: F401 — fallback for the top-level import context
    from test_ocr import _load_font

# Column x-origins (px) — wide, clean gaps so deterministic OCR separates the columns reliably. The
# header words are the bare synonyms the OCR column detector keys on ("Debit"/"Credit"/"Balance").
_COLS = {"date": 50, "description": 250, "debit": 760, "credit": 980, "balance": 1200}
_HEADERS = (
    ("date", "Date"), ("description", "Description"), ("debit", "Debit"),
    ("credit", "Credit"), ("balance", "Balance"),
)

_OPENING = Decimal("100000.00")

# (date, description, debit, credit) — a month of realistic activity that reconciles exactly.
_TXNS: tuple[tuple[str, str, Decimal | None, Decimal | None], ...] = (
    ("02-Apr", "Salary - DEMO CORP PVT LTD", None, Decimal("85000.00")),
    ("04-Apr", "ATM Cash Withdrawal", Decimal("10000.00"), None),
    ("06-Apr", "Rent Payment - April", Decimal("25000.00"), None),
    ("09-Apr", "UPI - SuperMart Groceries", Decimal("4200.00"), None),
    ("12-Apr", "Electricity Bill - DISCOM", Decimal("3150.00"), None),
    ("15-Apr", "Salary Advance", None, Decimal("15000.00")),
    ("17-Apr", "Mobile Recharge", Decimal("999.00"), None),
    ("19-Apr", "UPI - HP Fuel Station", Decimal("2500.00"), None),
    ("22-Apr", "Savings Interest Credit", None, Decimal("1250.00")),
    ("25-Apr", "Insurance Premium - LIC", Decimal("8000.00"), None),
    ("27-Apr", "Refund - Online Merchant", None, Decimal("3000.00")),
    ("29-Apr", "UPI - Cafe Coffee", Decimal("1800.00"), None),
)

# The single income figure a forger inflates (the row's printed credit), in rupees. The printed
# balances/totals stay at their genuine values, so the inflated credit no longer reconciles.
_INCOME_INFLATION = Decimal("100000.00")
# Index into _TXNS of the salary credit that gets inflated in the tampered statement.
TAMPER_TXN_INDEX = 0


def _fmt(d: Decimal) -> str:
    return f"{d:,.2f}"


def build_statement_rows(*, tamper: bool = False):
    """Return ``(rows, opening, closing, total_debit, total_credit)`` for the statement.

    ``rows`` are ``(date, description, debit_str, credit_str, balance_str)`` including the opening
    row. When ``tamper`` is set, the salary credit at :data:`TAMPER_TXN_INDEX` is displayed inflated
    by :data:`_INCOME_INFLATION` while every printed balance and total stays genuine — so the running
    balance, the credit total, and the net reconciliation all break at/after that row.
    """
    bal = _OPENING
    total_debit = Decimal("0")
    total_credit = Decimal("0")
    rows: list[tuple[str, str, str, str, str]] = [
        ("01-Apr", "Opening Balance", "", "", _fmt(bal))
    ]
    for i, (date, desc, debit, credit) in enumerate(_TXNS):
        if debit:
            bal -= debit
            total_debit += debit
        if credit:
            bal += credit
            total_credit += credit
        shown_credit = credit
        if tamper and i == TAMPER_TXN_INDEX and credit is not None:
            shown_credit = credit + _INCOME_INFLATION  # inflate the PRINTED credit only
        rows.append((
            date, desc,
            _fmt(debit) if debit else "",
            _fmt(shown_credit) if shown_credit else "",
            _fmt(bal),  # printed running balance stays genuine
        ))
    return rows, _OPENING, bal, total_debit, total_credit


def render_realistic_statement(*, tamper: bool = False) -> Image.Image:
    """Render a professional-looking bank statement (branded header, shaded rows, totals) to an image.

    Visually a real statement; structurally OCR-robust (clean columns, monospace numerals). The
    genuine render reconciles exactly; the tampered render carries one inflated income figure.
    """
    rows, _opening, closing, total_debit, total_credit = build_statement_rows(tamper=tamper)
    font_h = _load_font(30)
    font = _load_font(24)
    font_sm = _load_font(20)

    width = 1480
    row_h = 46
    top = 250
    height = top + (len(rows) + 4) * row_h + 80
    img = Image.new("RGB", (width, height), "white")
    d = ImageDraw.Draw(img)

    # Branded header band.
    d.rectangle((0, 0, width, 150), fill=(15, 32, 60))
    d.text((50, 40), "DEMO BANK OF INDIA", fill="white", font=font_h)
    d.text((50, 92), "Account Statement  -  Savings Account", fill=(180, 205, 235), font=font_sm)
    d.text((950, 40), "A/C Holder: ASHA RAO", fill="white", font=font_sm)
    d.text((950, 72), "A/C No: XXXXXX4821", fill=(180, 205, 235), font=font_sm)
    d.text((950, 104), "Period: 01-Apr to 30-Apr 2026", fill=(180, 205, 235), font=font_sm)

    # Column headers + rule.
    y = 190
    for name, label in _HEADERS:
        d.text((_COLS[name], y), label, fill=(15, 32, 60), font=font_sm)
    d.line((40, y + 34, width - 40, y + 34), fill=(15, 32, 60), width=2)

    # Transaction rows with alternating shading.
    y = top
    for i, (date, desc, debit, credit, balance) in enumerate(rows):
        if i % 2 == 1:
            d.rectangle((40, y - 6, width - 40, y + row_h - 12), fill=(244, 247, 251))
        d.text((_COLS["date"], y), date, fill="black", font=font)
        d.text((_COLS["description"], y), desc, fill="black", font=font)
        if debit:
            d.text((_COLS["debit"], y), debit, fill="black", font=font)
        if credit:
            d.text((_COLS["credit"], y), credit, fill="black", font=font)
        d.text((_COLS["balance"], y), balance, fill="black", font=font)
        y += row_h

    # Totals + closing balance.
    d.line((40, y, width - 40, y), fill=(15, 32, 60), width=2)
    y += 14
    d.text((_COLS["description"], y), "Total", fill="black", font=font)
    d.text((_COLS["debit"], y), _fmt(total_debit), fill="black", font=font)
    d.text((_COLS["credit"], y), _fmt(total_credit), fill="black", font=font)
    y += row_h
    d.text((_COLS["description"], y), "Closing Balance", fill="black", font=font)
    d.text((_COLS["balance"], y), _fmt(closing), fill="black", font=font)
    return img


def statement_pdf_bytes(statement: Image.Image) -> bytes:
    """Render a statement image into a single-page PDF (PyMuPDF), embedding it as a compact JPEG.

    Produces a real, parseable PDF that ``verification.signature`` can PAdES-sign — so Tier-1 can be
    demonstrated on a document that visibly *looks* like a bank e-statement, not a blank page.
    """
    import fitz  # PyMuPDF

    rgb = statement.convert("RGB")
    jpeg = io.BytesIO()
    rgb.save(jpeg, format="JPEG", quality=80)  # compact embed (keeps the signed PDF small)
    jpeg_bytes = jpeg.getvalue()

    w_pt = rgb.width * 0.5  # 0.5 px->pt ~ 144 DPI page
    h_pt = rgb.height * 0.5
    doc = fitz.open()
    page = doc.new_page(width=w_pt, height=h_pt)
    page.insert_image(fitz.Rect(0, 0, w_pt, h_pt), stream=jpeg_bytes)
    out = doc.tobytes()
    doc.close()
    return out
