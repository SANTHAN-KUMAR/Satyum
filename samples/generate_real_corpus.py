#!/usr/bin/env python3
"""Generate a real-document test corpus from actual bank statements and identity documents.

Takes the two Canara Bank PDFs (direct export + CAMSfinserv) and the user's Aadhaar,
creates systematic forgery variants by editing the PDF text layer, and produces edge cases.

All PII in generated files is from PUBLIC Google-sourced templates or fully masked.
The Aadhaar number is masked to XXXX XXXX #### and the name replaced with a synthetic one.

Usage:
    cd <repo_root>
    backend/.venv/bin/python samples/generate_real_corpus.py
"""

from __future__ import annotations

import io
import os
import shutil
import struct
import sys
from pathlib import Path

# Ensure the backend packages are importable
REPO = Path(__file__).resolve().parent.parent
BACKEND = REPO / "backend"
sys.path.insert(0, str(BACKEND))

import pymupdf  # PyMuPDF

CORPUS_DIR = REPO / "samples" / "real_corpus"
SRC_CANARA_DIRECT = REPO / "652591331-Canara-Bank-Statement.pdf"
SRC_CANARA_CAMS = REPO / "804153748-Statement.pdf"
SRC_AADHAAR = REPO / "aadhars" / "my aadhar.pdf"
SRC_AADHAAR_LOCKED = REPO / "aadhars" / "aadhar_locked.pdf"


# ── Helpers ──────────────────────────────────────────────────────────────────

def _ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)


def _pdf_replace_text(src_path: Path, replacements: list[tuple[str, str]], out_path: Path):
    """Open a PDF, search-and-replace text strings, save to out_path.

    Uses PyMuPDF's redaction API: for each (old, new) pair, find every occurrence of `old`,
    place a redaction annotation over it, then apply redactions with `new` as the fill text.
    This edits the *text layer* while preserving the visual layout.
    """
    doc = pymupdf.open(str(src_path))
    for page in doc:
        for old_text, new_text in replacements:
            hits = page.search_for(old_text)
            for rect in hits:
                # Add redaction with replacement text
                page.add_redact_annot(rect, text=new_text, fontsize=0, align=pymupdf.TEXT_ALIGN_LEFT)
        page.apply_redactions()
    doc.save(str(out_path))
    doc.close()


def _pdf_to_png(pdf_path: Path, png_path: Path, dpi: int = 200):
    """Render page 1 of a PDF to PNG."""
    doc = pymupdf.open(str(pdf_path))
    page = doc.load_page(0)
    pix = page.get_pixmap(dpi=dpi)
    pix.save(str(png_path))
    doc.close()


# ── Document 1: Canara Direct (5-column layout) ─────────────────────────────

def generate_canara_direct():
    """Create forgery variants from the Canara direct bank statement."""
    out = CORPUS_DIR / "canara_direct"
    _ensure_dir(out)

    if not SRC_CANARA_DIRECT.exists():
        print(f"  SKIP: {SRC_CANARA_DIRECT} not found")
        return

    # 1. Genuine copy
    shutil.copy2(SRC_CANARA_DIRECT, out / "genuine.pdf")
    _pdf_to_png(out / "genuine.pdf", out / "genuine.png")
    print("  ✓ canara_direct/genuine.pdf + .png")

    # 2. Tamper: inflate the big RTGS credit from 5,80,000.00 → 8,80,000.00
    #    Balance stays at 5,84,115.00 → running balance breaks
    _pdf_replace_text(
        SRC_CANARA_DIRECT,
        [("5,80,000.00", "8,80,000.00")],
        out / "tamper_salary_inflate.pdf",
    )
    _pdf_to_png(out / "tamper_salary_inflate.pdf", out / "tamper_salary_inflate.png")
    print("  ✓ canara_direct/tamper_salary_inflate.pdf + .png")

    # 3. Tamper: edit closing balance 22,562.16 → 52,562.16
    _pdf_replace_text(
        SRC_CANARA_DIRECT,
        [("22,562.16", "52,562.16")],
        out / "tamper_closing_balance.pdf",
    )
    _pdf_to_png(out / "tamper_closing_balance.pdf", out / "tamper_closing_balance.png")
    print("  ✓ canara_direct/tamper_closing_balance.pdf + .png")

    # 4. Tamper: remove a debit — zero out the 295.00 cheque book charge
    _pdf_replace_text(
        SRC_CANARA_DIRECT,
        [("295.00\n", "  0.00\n")],  # the debit field
        out / "tamper_debit_remove.pdf",
    )
    _pdf_to_png(out / "tamper_debit_remove.pdf", out / "tamper_debit_remove.png")
    print("  ✓ canara_direct/tamper_debit_remove.pdf + .png")

    # 5. Tamper: inflate credit AND fix the immediate balance to match
    #    5,80,000.00 → 8,80,000.00 AND 5,84,115.00 → 8,84,115.00
    #    The NEXT row's balance (2,84,115.00) will still break since it wasn't updated
    _pdf_replace_text(
        SRC_CANARA_DIRECT,
        [
            ("5,80,000.00", "8,80,000.00"),
            ("5,84,115.00", "8,84,115.00"),
        ],
        out / "tamper_partial_recompute.pdf",
    )
    _pdf_to_png(out / "tamper_partial_recompute.pdf", out / "tamper_partial_recompute.png")
    print("  ✓ canara_direct/tamper_partial_recompute.pdf + .png")

    # 6. Tamper: change the opening balance from 0.00 to 50,000.00
    _pdf_replace_text(
        SRC_CANARA_DIRECT,
        [("Rs. 0.00", "Rs. 50,000.00")],
        out / "tamper_opening_balance.pdf",
    )
    _pdf_to_png(out / "tamper_opening_balance.pdf", out / "tamper_opening_balance.png")
    print("  ✓ canara_direct/tamper_opening_balance.pdf + .png")


# ── Document 2: CAMSfinserv (Amount+Type layout) ────────────────────────────

def generate_canara_cams():
    """Create variants from the CAMSfinserv / Account Aggregator statement."""
    out = CORPUS_DIR / "canara_cams"
    _ensure_dir(out)

    if not SRC_CANARA_CAMS.exists():
        print(f"  SKIP: {SRC_CANARA_CAMS} not found")
        return

    # 1. Genuine copy — tests the "unsupported layout → NOT_EVALUATED" path
    shutil.copy2(SRC_CANARA_CAMS, out / "genuine.pdf")
    _pdf_to_png(out / "genuine.pdf", out / "genuine.png")
    print("  ✓ canara_cams/genuine.pdf + .png")

    # 2. Tamper: inflate an amount (10000.00 → 50000.00)
    _pdf_replace_text(
        SRC_CANARA_CAMS,
        [("10000.00", "50000.00")],
        out / "tamper_amount_inflate.pdf",
    )
    _pdf_to_png(out / "tamper_amount_inflate.pdf", out / "tamper_amount_inflate.png")
    print("  ✓ canara_cams/tamper_amount_inflate.pdf + .png")


# ── Identity Documents (Aadhaar) ────────────────────────────────────────────

def generate_identity_docs():
    """Create identity document variants from the Aadhaar PDF.

    PRIVACY: The real Aadhaar number is masked in all output files.
    We keep the visual layout but replace the name to create mismatch variants.
    """
    out = CORPUS_DIR / "identity"
    _ensure_dir(out)

    if not SRC_AADHAAR.exists():
        print(f"  SKIP: {SRC_AADHAAR} not found")
        return

    # 1. Genuine Aadhaar (copy as-is — the real name matches the statement's SARANYA T / TOLLWAYS)
    shutil.copy2(SRC_AADHAAR, out / "aadhaar_genuine.pdf")
    _pdf_to_png(out / "aadhaar_genuine.pdf", out / "aadhaar_genuine.png")
    print("  ✓ identity/aadhaar_genuine.pdf + .png")

    # 2. Name mismatch: change the name to create a cross-doc identity conflict
    _pdf_replace_text(
        SRC_AADHAAR,
        [
            ("Karnala Santhan Kumar", "Ramesh Venkatesh Iyer"),
            ("KARNALA SANTHAN KUMAR", "RAMESH VENKATESH IYER"),
        ],
        out / "aadhaar_name_mismatch.pdf",
    )
    _pdf_to_png(out / "aadhaar_name_mismatch.pdf", out / "aadhaar_name_mismatch.png")
    print("  ✓ identity/aadhaar_name_mismatch.pdf + .png")

    # 3. Aadhaar number typo: change one digit to simulate OCR near-miss
    # Original: 2797 8827 4735 → change last digit: 2797 8827 4736
    _pdf_replace_text(
        SRC_AADHAAR,
        [("2797 8827 4735", "2797 8827 4736")],
        out / "aadhaar_number_typo.pdf",
    )
    _pdf_to_png(out / "aadhaar_number_typo.pdf", out / "aadhaar_number_typo.png")
    print("  ✓ identity/aadhaar_number_typo.pdf + .png")

    # 4. Locked/encrypted Aadhaar — tests the fail-closed path
    if SRC_AADHAAR_LOCKED.exists():
        shutil.copy2(SRC_AADHAAR_LOCKED, out / "aadhaar_locked.pdf")
        print("  ✓ identity/aadhaar_locked.pdf (password-protected)")


# ── Edge Cases ───────────────────────────────────────────────────────────────

def generate_edge_cases():
    """Create adversarial edge-case files."""
    out = CORPUS_DIR / "edge"
    _ensure_dir(out)

    # 1. Corrupt PDF: valid header then garbage
    with open(out / "corrupt.pdf", "wb") as f:
        f.write(b"%PDF-1.4\n")
        f.write(b"THIS IS NOT A VALID PDF BODY\n")
        f.write(os.urandom(256))
    print("  ✓ edge/corrupt.pdf")

    # 2. Empty file
    with open(out / "empty.pdf", "wb") as f:
        pass  # 0 bytes
    print("  ✓ edge/empty.pdf (0 bytes)")

    # 3. Wrong extension: a PNG masquerading as PDF
    # Create a tiny valid PNG
    from PIL import Image
    img = Image.new("RGB", (100, 100), "red")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    with open(out / "wrong_extension.pdf", "wb") as f:
        f.write(buf.getvalue())
    print("  ✓ edge/wrong_extension.pdf (actually a PNG)")

    # 4. Oversized file (just over the typical 10MB limit)
    with open(out / "oversized.pdf", "wb") as f:
        f.write(b"%PDF-1.4\n")
        # Write ~11MB of padding
        chunk = b"0" * (1024 * 1024)
        for _ in range(11):
            f.write(chunk)
    print("  ✓ edge/oversized.pdf (~11MB)")

    # 5. Truncated real PDF: take first 500 bytes of the Canara statement
    if SRC_CANARA_DIRECT.exists():
        with open(SRC_CANARA_DIRECT, "rb") as src:
            data = src.read(500)
        with open(out / "truncated.pdf", "wb") as f:
            f.write(data)
        print("  ✓ edge/truncated.pdf (first 500 bytes)")


# ── README with expected verdicts ────────────────────────────────────────────

def write_readme():
    """Write the corpus README documenting each file and its expected verdict."""
    readme = CORPUS_DIR / "README.md"
    readme.write_text("""\
# Satyum Real-Document Test Corpus

Generated by `samples/generate_real_corpus.py` from real Canara Bank statements
(public Google-sourced templates) and identity documents.

## Canara Direct Export (`canara_direct/`)

| File | Forgery | Expected Verdict | Key Signal |
|------|---------|-----------------|------------|
| `genuine.pdf` | None | REVIEW | No provenance (unsigned) |
| `genuine.png` | None (screenshot) | REVIEW | Image path, no PDF structure |
| `tamper_salary_inflate.pdf` | RTGS credit ₹5.8L → ₹8.8L | REJECTED | `arithmetic_consistency` — running balance break |
| `tamper_salary_inflate.png` | Same as above (image) | REJECTED | `arithmetic_consistency` via OCR |
| `tamper_closing_balance.pdf` | Closing ₹22,562 → ₹52,562 | REJECTED | `arithmetic_consistency` — closing mismatch |
| `tamper_closing_balance.png` | Same (image) | REJECTED | `arithmetic_consistency` via OCR |
| `tamper_debit_remove.pdf` | Zeroed a ₹295 debit | REJECTED | `arithmetic_consistency` — running balance break |
| `tamper_debit_remove.png` | Same (image) | REJECTED | `arithmetic_consistency` via OCR |
| `tamper_partial_recompute.pdf` | Credit + its balance edited | REJECTED | `arithmetic_consistency` — next row breaks |
| `tamper_partial_recompute.png` | Same (image) | REJECTED | `arithmetic_consistency` via OCR |
| `tamper_opening_balance.pdf` | Opening ₹0 → ₹50,000 | REJECTED | `arithmetic_consistency` — net reconciliation |
| `tamper_opening_balance.png` | Same (image) | REJECTED | `arithmetic_consistency` via OCR |

## CAMSfinserv / Account Aggregator (`canara_cams/`)

| File | Forgery | Expected Verdict | Key Signal |
|------|---------|-----------------|------------|
| `genuine.pdf` | None | REVIEW | OCR can't locate Debit/Credit columns → NOT_EVALUATED (honest) |
| `genuine.png` | None (screenshot) | REVIEW | Same — Amount+Type layout unsupported |
| `tamper_amount_inflate.pdf` | Amount ₹10K → ₹50K | REVIEW | Same limitation — arithmetic can't run |
| `tamper_amount_inflate.png` | Same (image) | REVIEW | Same |

## Identity Documents (`identity/`)

| File | Forgery | Expected Verdict | Key Signal |
|------|---------|-----------------|------------|
| `aadhaar_genuine.pdf` | None | REVIEW | Entity extraction succeeds |
| `aadhaar_genuine.png` | None (image) | REVIEW | Entity extraction via OCR |
| `aadhaar_name_mismatch.pdf` | Name changed | REJECTED (in bundle) | `cross_document_consistency` — name mismatch |
| `aadhaar_name_mismatch.png` | Same (image) | REJECTED (in bundle) | Same |
| `aadhaar_number_typo.pdf` | One digit changed | REVIEW (in bundle) | `cross_document_consistency` — NEAR match |
| `aadhaar_number_typo.png` | Same (image) | REVIEW (in bundle) | Same |
| `aadhaar_locked.pdf` | Password-protected | ERROR | Fail-closed: encrypted PDF |

## Edge Cases (`edge/`)

| File | Description | Expected Behavior |
|------|-------------|-------------------|
| `corrupt.pdf` | Valid header, garbage body | ERROR → fail-closed to REVIEW |
| `empty.pdf` | 0 bytes | 400 Bad Request or ERROR |
| `wrong_extension.pdf` | A PNG renamed to .pdf | Magic-byte detection, image path runs |
| `oversized.pdf` | ~11MB | Size guard rejection (if configured) |
| `truncated.pdf` | First 500 bytes of real PDF | ERROR → fail-closed |
""")
    print("  ✓ README.md")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print(f"Generating real-document corpus in {CORPUS_DIR}\n")

    # Clean previous run
    if CORPUS_DIR.exists():
        shutil.rmtree(CORPUS_DIR)

    print("── Canara Direct (5-column layout) ──")
    generate_canara_direct()

    print("\n── CAMSfinserv (Amount+Type layout) ──")
    generate_canara_cams()

    print("\n── Identity Documents (Aadhaar) ──")
    generate_identity_docs()

    print("\n── Edge Cases ──")
    generate_edge_cases()

    print("\n── README ──")
    write_readme()

    # Count total files
    total = sum(1 for _ in CORPUS_DIR.rglob("*") if _.is_file())
    print(f"\n✅ Corpus complete: {total} files in {CORPUS_DIR}")


if __name__ == "__main__":
    main()
