"""Generate Satyum's synthetic test-document corpus — the drag-and-drop kit for judges/reviewers.

Run this to (re)produce every sample under ``samples/``. Each artifact is FULLY SYNTHETIC (no real
customer data, CLAUDE.md §10) and reproducible from this one script, so nothing here is a hand-tuned
fixture (§3.2). The demo CA's PRIVATE key is generated in memory and NEVER written — only the PUBLIC
root lands in ``samples/trust/`` so Tier-1 can verify the genuine signed PDF.

It reuses the repo's own test-proven builders (no new fake machinery): the same OCR statement renderer
and PAdES signing helpers the test-suite asserts against. What each file demonstrates and its expected
verdict is documented in ``samples/README.md``.

Usage:
    python samples/generate.py            # writes into ./samples/
    python samples/generate.py /tmp/out   # writes into a different directory
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_BACKEND = _REPO / "backend"
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "tests"))

from cryptography.hazmat.primitives import serialization  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

# Real, test-asserted builders — the same code the suite proves discriminates.
from test_ocr import (  # noqa: E402
    _GENUINE_ROWS,
    _load_font,
    _png_bytes,
    _render_statement,
    _tampered_rows,
)
from test_signature import _MINIMAL_PDF, _make_ca, _make_leaf, _sign_pdf  # noqa: E402


def _append_after_signature(signed_pdf: bytes) -> bytes:
    """Append bytes AFTER the signed /ByteRange — the PAdES shadow / incremental-update attack."""
    from pyhanko.pdf_utils import generic
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter

    iw = IncrementalPdfFileWriter(io.BytesIO(signed_pdf))
    iw.add_object(generic.TextStringObject("payload injected after the signature"))
    out = io.BytesIO()
    iw.write(out)
    return out.getvalue()


def _render_identity_doc(title: str, fields: dict[str, str]) -> Image.Image:
    """A simple, OCR-robust identity-style document: a title and labelled identity fields.

    Rendered large and well-spaced so deterministic OCR reads the identifiers reliably — these feed
    the cross-document identity graph (the values, not the pixels, are the point).
    """
    font_title = _load_font(34)
    font = _load_font(28)
    width = 900
    height = 140 + len(fields) * 56
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    draw.text((40, 36), title, fill="black", font=font_title)
    draw.line((40, 92, width - 40, 92), fill="black", width=2)
    y = 120
    for label, value in fields.items():
        draw.text((40, y), f"{label}: {value}", fill="black", font=font)
        y += 56
    return img


def main(out_dir: str) -> None:
    out = Path(out_dir)
    dirs = {
        "trust": out / "trust",
        "statements": out / "statements",
        "pdfs": out / "pdfs",
        "match": out / "bundle_consistent",
        "mismatch": out / "bundle_mismatch",
    }
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)

    # --- PKI: an in-memory demo CA. Only the PUBLIC root is written (§10 — never a private key). ---
    ca_key, ca_cert = _make_ca("Satyum DEMO Root CA (stand-in for CCA-India)")
    (dirs["trust"] / "demo_ca_root.pem").write_bytes(
        ca_cert.public_bytes(serialization.Encoding.PEM)
    )

    # --- Tier-1 signed-PDF samples ------------------------------------------------------------
    leaf_key, leaf_cert = _make_leaf(ca_key, ca_cert, "statements.demo-bank.example")
    genuine_signed = _sign_pdf(_MINIMAL_PDF, leaf_key, leaf_cert, ca_cert)
    (dirs["pdfs"] / "genuine_signed.pdf").write_bytes(genuine_signed)

    atk_key, atk_cert = _make_ca("Attacker Self-Signed CA")
    atk_leaf_key, atk_leaf_cert = _make_leaf(atk_key, atk_cert, "statements.demo-bank.example")
    (dirs["pdfs"] / "attacker_self_signed.pdf").write_bytes(
        _sign_pdf(_MINIMAL_PDF, atk_leaf_key, atk_leaf_cert, atk_cert)
    )
    (dirs["pdfs"] / "appended_after_signature.pdf").write_bytes(
        _append_after_signature(genuine_signed)
    )
    (dirs["pdfs"] / "unsigned.pdf").write_bytes(_MINIMAL_PDF)

    # --- Tier-2 arithmetic-consistency samples ------------------------------------------------
    (dirs["statements"] / "genuine_statement.png").write_bytes(
        _png_bytes(_render_statement(_GENUINE_ROWS))
    )
    (dirs["statements"] / "tampered_statement.png").write_bytes(
        _png_bytes(_render_statement(_tampered_rows()))  # one balance figure inflated
    )

    # --- Cross-document bundle samples (ADR-003 #3) -------------------------------------------
    # Consistent: the statement and the ID carry the SAME identity -> bundle corroborates.
    (dirs["match"] / "A_bank_statement.png").write_bytes(
        _png_bytes(_render_identity_doc("DEMO BANK — Account Statement",
                                        {"Account Holder": "ASHA RAO", "PAN": "ABCDE1234F"}))
    )
    (dirs["match"] / "B_identity_card.png").write_bytes(
        _png_bytes(_render_identity_doc("DEMO IDENTITY CARD",
                                        {"Name": "ASHA RAO", "PAN": "ABCDE1234F"}))
    )
    # Mismatch: the same applicant's two documents carry DIFFERENT PANs -> hard identity mismatch.
    (dirs["mismatch"] / "A_bank_statement.png").write_bytes(
        _png_bytes(_render_identity_doc("DEMO BANK — Account Statement",
                                        {"Account Holder": "ASHA RAO", "PAN": "ABCDE1234F"}))
    )
    (dirs["mismatch"] / "B_identity_card.png").write_bytes(
        _png_bytes(_render_identity_doc("DEMO IDENTITY CARD",
                                        {"Name": "MOHAN LAL", "PAN": "PQRST5678K"}))
    )

    print(f"Synthetic test corpus written to {out}")
    for p in sorted(out.rglob("*")):
        if p.is_file() and p.suffix != ".md" and p.name != "generate.py":
            print(f"  {p.relative_to(out)}  ({p.stat().st_size} bytes)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).resolve().parent))
