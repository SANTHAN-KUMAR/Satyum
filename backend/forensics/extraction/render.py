"""Render a document page to a single :class:`PageImage` shared by the reader and the cross-read.

Both the VLM and the OCR cross-read must see the *same* pixels so a normalized bounding box from one
maps to the same cell in the other. This module renders once — a PDF page via PyMuPDF, an uploaded
image via PIL, or a rectified camera crop — and captures the pixel dimensions and (for PDFs) the
embedded text layer, which the router uses for free, deterministic script detection.

Lazy imports so a missing system dependency degrades to a fail-closed analyzer error, never an
import-time crash of the whole pipeline (CLAUDE.md §4). Untrusted bytes are opened with an explicit
filetype so a mislabeled upload cannot coerce another loader (defensive ingestion, §10).
"""

from __future__ import annotations

import io
import logging

from app.contracts import AnalysisContext
from forensics.extraction.interface import PageImage
from forensics.ocr import RENDER_DPI, is_pdf

logger = logging.getLogger(__name__)


def _png_and_size(pil_image) -> tuple[bytes, int, int]:
    buf = io.BytesIO()
    pil_image.save(buf, format="PNG")
    return buf.getvalue(), pil_image.width, pil_image.height


def _render_pdf(file_bytes: bytes) -> PageImage | None:
    import pymupdf

    doc = pymupdf.open(stream=file_bytes, filetype="pdf")
    try:
        if doc.page_count < 1:
            return None
        page = doc.load_page(0)
        pix = page.get_pixmap(dpi=RENDER_DPI)
        png_bytes = pix.tobytes("png")
        text_layer = page.get_text("text") or ""
    finally:
        doc.close()
    return PageImage(png_bytes=png_bytes, width=pix.width, height=pix.height, text_layer=text_layer)


def _render_image_bytes(file_bytes: bytes) -> PageImage | None:
    from PIL import Image

    img = Image.open(io.BytesIO(file_bytes)).convert("RGB")
    png_bytes, w, h = _png_and_size(img)
    return PageImage(png_bytes=png_bytes, width=w, height=h, text_layer="")


def _render_frame(frame) -> PageImage | None:
    import numpy as np
    from PIL import Image

    arr = np.asarray(frame)
    if arr.ndim == 3 and arr.shape[2] == 3:
        arr = arr[:, :, ::-1]  # BGR (OpenCV) → RGB
    img = Image.fromarray(arr.astype("uint8")).convert("RGB")
    png_bytes, w, h = _png_and_size(img)
    return PageImage(png_bytes=png_bytes, width=w, height=h, text_layer="")


def render_page(ctx: AnalysisContext) -> tuple[PageImage | None, str]:
    """Render the document under analysis to a :class:`PageImage`, or ``(None, reason)``.

    Returns ``(None, reason)`` for an empty/undecodable intake (honest "nothing to read"); raises
    ``ImportError`` only when a render dependency is missing, which the analyzer maps to a fail-closed
    ERROR. Never persists anything (CLAUDE.md §10).
    """
    if ctx.file_bytes is not None and is_pdf(ctx.file_bytes):
        page = _render_pdf(ctx.file_bytes)
        return (page, "pdf_page_1") if page is not None else (None, "pdf has no renderable pages")

    if ctx.file_bytes is not None:
        try:
            page = _render_image_bytes(ctx.file_bytes)
        except Exception as exc:  # noqa: BLE001 — undecodable upload is an honest "unreadable"
            logger.info("render: file bytes not a decodable image: %r", exc)
            return None, "file bytes are neither a PDF nor a decodable image"
        return page, "image_file"

    rectified = ctx.shared.get("rectified")
    frame = rectified if rectified is not None else (ctx.frames[-1] if ctx.frames else None)
    if frame is None:
        return None, "no file bytes, rectified crop, or camera frame available"
    try:
        page = _render_frame(frame)
    except Exception as exc:  # noqa: BLE001
        logger.info("render: frame not decodable: %r", exc)
        return None, "frame is not a decodable image array"
    return page, ("rectified_crop" if rectified is not None else "latest_frame")
