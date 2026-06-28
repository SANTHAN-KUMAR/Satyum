"""Tier-2 BRIDGE analyzer: document image/PDF -> structured ``StatementData`` for the engine.

This module is the *parser*, not a *scorer*. Its single job is to read a bank statement (a PDF
page or a rectified camera crop) into the exact :class:`forensics.arithmetic.StatementData` shape
the already-built arithmetic-consistency engine consumes, and publish it on
``ctx.shared['statement']`` (with the raw OCR words on ``ctx.shared['ocr']``). It deliberately
emits **NOT_EVALUATED** for its own signal: extracting numbers is not the same as judging them —
tamper scoring belongs to ``ArithmeticConsistencyAnalyzer`` downstream (CLAUDE.md §4, single
responsibility). The only measurement it reports is ``ocr_confidence``.

Real technique (no fake signal, CLAUDE.md §3.1):
  * PDF intake  -> render page 1 with PyMuPDF (``page.get_pixmap(dpi=...)``) to a raster image.
  * camera intake -> use the rectified crop published by the boundary/rectify analyzer, else the
    latest buffered frame.
  * Tesseract via ``pytesseract.image_to_data(..., output_type=Output.DICT)`` gives every word a
    bounding box and a 0..100 confidence.
  * Locate the transaction table by its **header words** (Date / Description / Debit / Credit /
    Balance) and their x-centres; assign each later word to a column by x-overlap; group words into
    rows by their text-line index; parse money cells with a robust ``Decimal`` parser.

CRITICAL HONESTY (BUILD-MANIFEST "OCR field extraction" guard, CLAUDE.md §3.4): if mean word
confidence is below ``settings.ocr_min_confidence`` *or* the header columns cannot be located, the
affected fields are left **None** — so the arithmetic engine returns NOT_EVALUATED rather than
scoring fabricated numbers. A low-confidence/garbled scan therefore renders "unreadable — pending",
never a false "tampered". We never invent a figure to fill a gap.

Honest bound: this parser targets the common Date|Description|Debit|Credit|Balance tabular layout
on a reasonably clean render. Multi-line descriptions, merged/rotated cells, and exotic layouts are
out of scope — they degrade to fewer parsed rows (and thus NOT_EVALUATED downstream), never to a
fabricated reconciliation.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import numpy as np

from app.config import settings
from app.contracts import AnalysisContext, LayerSignal, Mode
from forensics.arithmetic import StatementData, Transaction

BBox = tuple[float, float, float, float]

# --- Render / OCR tunables ----------------------------------------------------------------------
# 200 DPI is the BUILD-MANIFEST target: enough detail for Tesseract on body text without bloating
# the raster. Not a detection threshold, so not a calibrated constant.
RENDER_DPI = 200
# Tesseract emits conf in [0, 100]; settings.ocr_min_confidence is the [0, 1] gate. Normalise.
_CONF_SCALE = 100.0

# Header tokens that identify each logical column. Matched case-insensitively as whole words.
_HEADER_SYNONYMS: dict[str, tuple[str, ...]] = {
    "date": ("date", "txndate", "valuedate", "value"),
    "description": ("description", "particulars", "narration", "details", "remarks"),
    "debit": ("debit", "withdrawal", "withdrawals", "dr", "paid"),
    "credit": ("credit", "deposit", "deposits", "cr", "received"),
    "balance": ("balance", "closingbalance", "runningbalance"),
}

# Label tokens that mark the opening/closing-balance and column-total summary rows.
_OPENING_TOKENS = ("opening", "openingbalance", "broughtforward", "b/f", "bf", "openingbal")
_CLOSING_TOKENS = ("closing", "closingbalance", "carriedforward", "c/f", "cf", "closingbal")
_TOTAL_TOKENS = ("total", "totals", "grandtotal")

# A money cell: optional currency sign, grouped digits, optional decimals, optional trailing Dr/Cr.
_MONEY_RE = re.compile(
    r"""^[\s₹$€£rs.]*            # leading currency / 'Rs.' noise
        (?P<num>-?\d{1,3}(?:,\d{2,3})*(?:\.\d{1,2})?|-?\d+(?:\.\d{1,2})?)
        \s*(?:dr|cr)?\.?$        # optional trailing Dr/Cr marker
    """,
    re.IGNORECASE | re.VERBOSE,
)


@dataclass
class _Word:
    """One OCR token with its pixel box and 0..1 confidence."""

    text: str
    left: int
    top: int
    width: int
    height: int
    conf: float  # normalised to [0, 1]

    @property
    def x_center(self) -> float:
        return self.left + self.width / 2.0

    @property
    def bbox(self) -> BBox:
        return (float(self.left), float(self.top), float(self.width), float(self.height))


@dataclass
class _Column:
    name: str
    x_left: float
    x_right: float

    def contains(self, x: float) -> bool:
        return self.x_left <= x < self.x_right


def _norm(token: str) -> str:
    """Lower-case and strip non-alphanumerics so 'B/F' -> 'bf', 'Closing Bal.' tokens normalise."""
    return re.sub(r"[^a-z0-9]", "", token.lower())


def parse_money(raw: str) -> Decimal | None:
    """Parse a printed money cell to ``Decimal``; return ``None`` if it is not a number.

    Strips currency symbols / 'Rs.' / thousands separators and an optional trailing Dr/Cr marker.
    Returns ``None`` (never 0, never a guess) for anything non-numeric — so a blank or unreadable
    cell propagates as a *missing* figure, not a fabricated zero.
    """
    if raw is None:
        return None
    # Tesseract routinely splits one printed figure into fragments with spaces, e.g.
    # "15,000.00" -> "15, 000. 00". Within a single column cell these are pieces of ONE number, so
    # we drop internal whitespace before matching. We do NOT drop other separators, so a genuine
    # two-number cell (which shouldn't occur after column bucketing) still fails to parse.
    cleaned = re.sub(r"\s+", "", raw)
    if not cleaned:
        return None
    m = _MONEY_RE.match(cleaned)
    if m is None:
        return None
    digits = m.group("num").replace(",", "")
    try:
        return Decimal(digits)
    except InvalidOperation:
        return None


def is_pdf(data: bytes) -> bool:
    """True if the bytes begin with the PDF magic header (allowing a small leading BOM/whitespace)."""
    if not data:
        return False
    head = data[:1024].lstrip(b"\x00\r\n\t ")
    return head.startswith(b"%PDF-")


def _render_pdf_page(file_bytes: bytes, dpi: int = RENDER_DPI):
    """Render page 1 of an in-memory PDF to a PIL ``Image`` via PyMuPDF.

    Imported lazily so a missing system dep surfaces as an analyzer ERROR (fail-closed), never an
    import-time crash of the whole pipeline. Opened with ``filetype='pdf'`` so a mislabeled upload
    cannot coerce the parser into another loader (defensive ingestion, CLAUDE.md §10).
    """
    import pymupdf  # PyMuPDF; also importable as ``fitz``
    from PIL import Image

    doc = pymupdf.open(stream=file_bytes, filetype="pdf")
    try:
        if doc.page_count < 1:
            return None
        page = doc.load_page(0)
        pix = page.get_pixmap(dpi=dpi)
        png_bytes = pix.tobytes("png")
    finally:
        doc.close()
    return Image.open(io.BytesIO(png_bytes)).convert("RGB")


def _image_from_context(ctx: AnalysisContext):
    """Resolve the image to OCR: rendered PDF page, the rectified crop, or the latest frame.

    Returns ``(pil_image, source_str)`` or ``(None, reason)``. Camera frames are NumPy BGR arrays
    (OpenCV convention); converted to RGB PIL without persisting anything (CLAUDE.md §10).
    """
    from PIL import Image

    if ctx.file_bytes is not None and is_pdf(ctx.file_bytes):
        img = _render_pdf_page(ctx.file_bytes)
        if img is None:
            return None, "pdf has no renderable pages"
        return img, "pdf_page_1"

    if ctx.file_bytes is not None:
        # A non-PDF file upload (image statement). Decode defensively via PIL.
        try:
            img = Image.open(io.BytesIO(ctx.file_bytes)).convert("RGB")
        except Exception:  # noqa: BLE001 — any decode failure is an honest "unreadable", not a pass
            return None, "file bytes are neither a PDF nor a decodable image"
        return img, "image_file"

    rectified = ctx.shared.get("rectified")
    frame = rectified if rectified is not None else (ctx.frames[-1] if ctx.frames else None)
    if frame is None:
        return None, "no file bytes, rectified crop, or camera frame available"

    arr = frame
    if hasattr(arr, "ndim"):  # NumPy array (BGR from OpenCV) -> RGB PIL
        import numpy as np

        arr = np.asarray(arr)
        if arr.ndim == 3 and arr.shape[2] == 3:
            arr = arr[:, :, ::-1]  # BGR -> RGB
        img = Image.fromarray(arr.astype("uint8"))
        return img.convert("RGB"), ("rectified_crop" if rectified is not None else "latest_frame")
    return None, "frame is not a decodable image array"


def _ocr_words(image) -> list[_Word]:
    """Run Tesseract TSV extraction and return real word tokens (level==5) with boxes + confidence."""
    import pytesseract
    from pytesseract import Output

    data = pytesseract.image_to_data(image, output_type=Output.DICT)
    words: list[_Word] = []
    n = len(data["text"])
    for i in range(n):
        text = (data["text"][i] or "").strip()
        if not text:
            continue
        conf_raw = data["conf"][i]
        try:
            conf = float(conf_raw)
        except (TypeError, ValueError):
            conf = -1.0
        if conf < 0:  # -1 marks non-word levels (block/par/line); skip
            continue
        words.append(
            _Word(
                text=text,
                left=int(data["left"][i]),
                top=int(data["top"][i]),
                width=int(data["width"][i]),
                height=int(data["height"][i]),
                conf=conf / _CONF_SCALE,
            )
        )
    return words


def _mean_confidence(words: list[_Word]) -> float:
    if not words:
        return 0.0
    return sum(w.conf for w in words) / len(words)


def _median_height(words: list[_Word]) -> float:
    heights = sorted(w.height for w in words)
    if not heights:
        return 0.0
    mid = len(heights) // 2
    if len(heights) % 2:
        return float(heights[mid])
    return (heights[mid - 1] + heights[mid]) / 2.0


def _cluster_rows(words: list[_Word]) -> list[list[_Word]]:
    """Cluster words into visual rows by vertical position.

    Multi-column statements defeat Tesseract's per-block line numbering (each whitespace-separated
    column becomes its own ``block_num``), so a header or a transaction row is NOT one Tesseract
    line. We instead band words by their vertical centre: words whose centres fall within roughly
    one text-height of each other belong to the same printed row. This is the standard geometric
    row-reconstruction for tabular OCR and is what lets a Date|Debit|Credit|Balance row be read as a
    single record.
    """
    if not words:
        return []
    band = max(_median_height(words) * 0.8, 6.0)  # half-line tolerance; floor for tiny text
    ordered = sorted(words, key=lambda w: w.top + w.height / 2.0)
    rows: list[list[_Word]] = []
    current: list[_Word] = [ordered[0]]
    current_y = ordered[0].top + ordered[0].height / 2.0
    for w in ordered[1:]:
        wy = w.top + w.height / 2.0
        if wy - current_y <= band:
            current.append(w)
        else:
            rows.append(current)
            current = [w]
        current_y = wy
    rows.append(current)
    return [sorted(r, key=lambda w: w.left) for r in rows]


def _detect_columns(words: list[_Word]) -> tuple[dict[str, _Column] | None, float | None]:
    """Find the header row and turn the header words into x-bounded columns.

    Returns ``(columns_by_name, header_bottom_y)`` or ``(None, None)`` if a usable header (the
    balance column plus at least one movement column) is not present. Header words are matched by
    synonym, banded into the visual row that carries the most distinct column labels, and the
    column x-boundaries are the midpoints between adjacent header centres — so each later word lands
    in exactly one column.
    """
    header_hits: list[tuple[str, _Word]] = []
    for w in words:
        key = _norm(w.text)
        for col_name, synonyms in _HEADER_SYNONYMS.items():
            if key in synonyms:
                header_hits.append((col_name, w))
                break

    if not header_hits:
        return None, None

    # Band the header hits by vertical position; the header is the band with the most distinct
    # column names. This survives Tesseract splitting each column into its own block.
    hit_words = [w for _, w in header_hits]
    name_of = {id(w): name for name, w in header_hits}
    best_band: list[_Word] = []
    best_distinct = 0
    for row in _cluster_rows(hit_words):
        distinct = len({name_of[id(w)] for w in row})
        if distinct > best_distinct:
            best_distinct = distinct
            best_band = row

    # Keep the first (left-most) occurrence of each column name in the header band.
    centres: dict[str, _Word] = {}
    for w in sorted(best_band, key=lambda w: w.left):
        centres.setdefault(name_of[id(w)], w)

    # Need balance + at least one movement column to assert any invariant downstream.
    if "balance" not in centres or not ({"debit", "credit"} & set(centres)):
        return None, None

    ordered = sorted(centres.items(), key=lambda kv: kv[1].x_center)
    columns: dict[str, _Column] = {}
    for idx, (col_name, w) in enumerate(ordered):
        left = float("-inf") if idx == 0 else (ordered[idx - 1][1].x_center + w.x_center) / 2.0
        right = (
            float("inf")
            if idx == len(ordered) - 1
            else (w.x_center + ordered[idx + 1][1].x_center) / 2.0
        )
        columns[col_name] = _Column(col_name, left, right)

    header_bottom = max(w.top + w.height for w in best_band)
    return columns, header_bottom


def _group_rows(words: list[_Word], header_bottom: float) -> list[list[_Word]]:
    """Group the words strictly BELOW the header band into visual rows, left-to-right ordered."""
    body = [w for w in words if (w.top + w.height / 2.0) > header_bottom]
    return _cluster_rows(body)


def _row_cells(row: list[_Word], columns: dict[str, _Column]) -> dict[str, list[_Word]]:
    """Bucket each word in a row into its column by x-centre."""
    cells: dict[str, list[_Word]] = {name: [] for name in columns}
    for w in row:
        for name, col in columns.items():
            if col.contains(w.x_center):
                cells[name].append(w)
                break
    return cells


def _cell_text(cell: list[_Word]) -> str:
    return " ".join(w.text for w in cell)


def _union_bbox(cell: list[_Word]) -> BBox | None:
    """Axis-aligned bounding box that encloses every token in the cell (the evidence region)."""
    if not cell:
        return None
    x0 = min(w.left for w in cell)
    y0 = min(w.top for w in cell)
    x1 = max(w.left + w.width for w in cell)
    y1 = max(w.top + w.height for w in cell)
    return (float(x0), float(y0), float(x1 - x0), float(y1 - y0))


def _cell_money(cell: list[_Word]) -> tuple[Decimal | None, BBox | None]:
    """Parse the money figure printed in a cell; return its value and the cell's bounding box.

    Tesseract often fragments one figure (e.g. ``15,000.00`` -> ``['15,', '000.', '00']``), so we
    parse the whole cell text (whitespace-stripped inside ``parse_money``) and report the union box
    of all its tokens as the evidence region. Falls back to a single clean token if the join fails.
    """
    joined = parse_money(_cell_text(cell))
    if joined is not None:
        return joined, _union_bbox(cell)
    for w in reversed(cell):
        value = parse_money(w.text)
        if value is not None:
            return value, w.bbox
    return None, None


def build_statement(words: list[_Word]) -> StatementData | None:
    """Assemble a :class:`StatementData` from OCR words, or ``None`` if the table is not locatable.

    Honesty contract: every figure comes from a parsed cell. A summary row (Opening / Closing /
    Total) sets the corresponding stated field; ordinary rows become ``Transaction`` records with a
    ``balance_bbox`` so the arithmetic engine can localise a broken invariant. Unparseable cells stay
    ``None`` — never zero-filled.
    """
    columns, header_bottom = _detect_columns(words)
    if columns is None or header_bottom is None:
        return None

    stmt = StatementData()
    txn_index = 0

    for row in _group_rows(words, header_bottom):
        cells = _row_cells(row, columns)
        # A summary label ("Opening Balance", "Total") can land outside the description column, so we
        # match summary keywords against the whole row's normalised text, not just one cell.
        row_label = _norm(" ".join(w.text for w in row))

        balance_val, balance_bbox = _cell_money(cells.get("balance", []))
        debit_val, _ = _cell_money(cells.get("debit", []))
        credit_val, _ = _cell_money(cells.get("credit", []))

        def _has(tokens: tuple[str, ...], _label: str = row_label) -> bool:
            return any(tok in _label for tok in tokens)

        # --- summary rows ---------------------------------------------------------------------
        if _has(_OPENING_TOKENS) and balance_val is not None and debit_val is None and credit_val is None:
            stmt.opening_balance = balance_val
            continue
        if _has(_CLOSING_TOKENS) and balance_val is not None and debit_val is None and credit_val is None:
            stmt.closing_balance = balance_val
            continue
        if _has(_TOTAL_TOKENS) and (debit_val is not None or credit_val is not None) and balance_val is None:
            if debit_val is not None:
                stmt.stated_total_debits = debit_val
            if credit_val is not None:
                stmt.stated_total_credits = credit_val
            continue

        # --- ordinary transaction row ---------------------------------------------------------
        if balance_val is None and debit_val is None and credit_val is None:
            continue  # no numeric content -> not a transaction line
        date_text = _cell_text(cells.get("date", [])).strip() or None
        desc_text = _cell_text(cells.get("description", [])).strip() or None
        stmt.transactions.append(
            Transaction(
                index=txn_index,
                debit=debit_val,
                credit=credit_val,
                balance=balance_val,
                date=date_text,
                description=desc_text,
                balance_bbox=balance_bbox,
            )
        )
        txn_index += 1

    # If we found no opening balance but the first row carries one and movements follow, we still
    # leave opening None rather than guessing — the arithmetic engine will honestly NOT_EVALUATE.
    if not stmt.transactions:
        return None
    return stmt


def _to_bgr(pil_image) -> np.ndarray:
    """PIL image -> H×W×3 uint8 BGR array (the same channel convention the rectify analyzer uses)."""
    return np.asarray(pil_image.convert("RGB"))[:, :, ::-1].copy()


def ocr_word_dicts(words: list[_Word]) -> list[dict[str, Any]]:
    """The canonical ``ctx.shared['ocr']`` LIST shape consumed by ``FontLayoutAnalyzer``.

    One dict per word — ``{text,left,top,width,height,conf,line_num,block_num}``. Tesseract's own
    per-block line numbering is unreliable on multi-column tables (each column becomes its own
    block), so we group words into visual rows geometrically (the same ``_cluster_rows`` the table
    parser uses) and use the row index as ``line_num`` — giving the layout analyzer real same-line
    word groups to compare typography across.
    """
    out: list[dict[str, Any]] = []
    for line_num, row in enumerate(_cluster_rows(words)):
        for w in row:
            out.append(
                {
                    "text": w.text, "left": w.left, "top": w.top,
                    "width": w.width, "height": w.height, "conf": w.conf,
                    "line_num": line_num, "block_num": 0,
                }
            )
    return out


class DocumentParseAnalyzer:
    """Tier-2 bridge: OCR a statement into ``ctx.shared['statement']`` for the arithmetic engine.

    Returns its OWN signal as NOT_EVALUATED with an ``ocr_confidence`` measurement — it extracts, it
    does not score tampering. Downstream ``ArithmeticConsistencyAnalyzer`` reads the published
    statement and produces the actual VALID tamper signal.
    """

    name = "document_parse"
    layer = 3
    mode = Mode.ANY  # a PDF page or a rectified camera crop alike
    order = 5  # runs before the arithmetic engine in the layer-3 waterfall

    def applicable(self, ctx: AnalysisContext) -> bool:
        return ctx.file_bytes is not None or bool(ctx.frames) or "rectified" in ctx.shared

    def analyze(self, ctx: AnalysisContext) -> LayerSignal:
        try:
            image, source = _image_from_context(ctx)
        except ImportError as exc:  # missing system dep (tesseract/pymupdf) -> fail-closed
            return LayerSignal.error(
                self.name, self.layer, self.mode, f"render dependency unavailable: {exc}"
            )
        except Exception as exc:  # noqa: BLE001 — any render failure is fail-closed, never a pass
            return LayerSignal.error(self.name, self.layer, self.mode, f"render failed: {exc}")

        if image is None:
            return LayerSignal.not_evaluated(self.name, self.layer, self.mode, source)

        # Publish the document raster so the image-level Tier-2 forensics (copy-move, template,
        # pHash, font/layout) run on a FILE upload too, not only the camera path (ADR-002 Tier 2).
        # BGR to match the rectified-crop channel convention the consumers expect.
        try:
            ctx.shared["page_image"] = _to_bgr(image)
        except Exception:  # noqa: BLE001 — raster publishing must never break the parser
            pass

        try:
            words = _ocr_words(image)
        except ImportError as exc:
            return LayerSignal.error(
                self.name, self.layer, self.mode, f"OCR dependency unavailable: {exc}"
            )
        except Exception as exc:  # noqa: BLE001 — Tesseract failure -> fail-closed
            return LayerSignal.error(self.name, self.layer, self.mode, f"OCR failed: {exc}")

        mean_conf = _mean_confidence(words)
        measurements: dict[str, Any] = {
            "ocr_confidence": mean_conf,
            "word_count": len(words),
            "source": source,
            "min_confidence_gate": settings.ocr_min_confidence,
        }

        # HONEST GATE 1: too unreadable to trust any number -> publish nothing, never a fake value.
        if mean_conf < settings.ocr_min_confidence:
            return LayerSignal.not_evaluated(
                self.name,
                self.layer,
                self.mode,
                f"mean OCR confidence {mean_conf:.2f} < gate {settings.ocr_min_confidence:.2f} "
                "— statement unreadable, left pending (not 'tampered')",
                **measurements,
            )

        # Text is readable -> publish OCR word geometry (canonical list shape) for the font/layout
        # analyzer. Deliberately withheld on the unreadable scan above so typography is never
        # assessed on OCR noise (which would manufacture false "tampering").
        ctx.shared["ocr"] = ocr_word_dicts(words)

        statement = build_statement(words)

        # HONEST GATE 2: confident text but no locatable transaction table -> no statement published.
        if statement is None:
            return LayerSignal.not_evaluated(
                self.name,
                self.layer,
                self.mode,
                "transaction table (Date/Debit/Credit/Balance columns) not located — "
                "no statement extracted",
                **measurements,
            )

        ctx.shared["statement"] = statement
        measurements["transactions_parsed"] = len(statement.transactions)
        measurements["opening_balance_found"] = statement.opening_balance is not None
        measurements["closing_balance_found"] = statement.closing_balance is not None

        return LayerSignal.not_evaluated(
            self.name,
            self.layer,
            self.mode,
            f"parsed {len(statement.transactions)} transaction row(s) at mean confidence "
            f"{mean_conf:.2f}; statement published for the arithmetic engine",
            **measurements,
        )
