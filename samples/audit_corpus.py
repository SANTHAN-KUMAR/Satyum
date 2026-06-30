#!/usr/bin/env python3
"""Deep audit of generated corpus files.

Extracts text from genuine vs tampered PDFs and compares them to verify
that real text-layer modifications exist (not just renames/copies).
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))

import pymupdf

def extract_all_text(pdf_path: Path) -> str:
    """Extract full text from all pages of a PDF."""
    try:
        doc = pymupdf.open(str(pdf_path))
        text = ""
        for page in doc:
            text += page.get_text()
        doc.close()
        return text
    except Exception as e:
        return f"[ERROR: {e}]"

def file_size(p: Path) -> int:
    return p.stat().st_size if p.exists() else 0

def diff_texts(genuine_text: str, tampered_text: str) -> list[str]:
    """Find lines that differ between genuine and tampered text."""
    g_lines = genuine_text.splitlines()
    t_lines = tampered_text.splitlines()
    diffs = []
    max_len = max(len(g_lines), len(t_lines))
    for i in range(max_len):
        g = g_lines[i] if i < len(g_lines) else "<MISSING>"
        t = t_lines[i] if i < len(t_lines) else "<MISSING>"
        if g != t:
            diffs.append(f"  Line {i+1}: '{g.strip()}' → '{t.strip()}'")
    return diffs

print("=" * 80)
print("CORPUS FORENSIC AUDIT")
print("=" * 80)

# ── 1. REAL CORPUS: Canara Direct ──
print("\n── REAL CORPUS: canara_direct ──")
real_dir = REPO / "samples" / "real_corpus" / "canara_direct"
genuine_path = real_dir / "genuine.pdf"

if genuine_path.exists():
    genuine_text = extract_all_text(genuine_path)
    print(f"  genuine.pdf: {file_size(genuine_path)} bytes, {len(genuine_text)} chars text extracted")

    for tamper_file in sorted(real_dir.glob("tamper_*.pdf")):
        tamper_text = extract_all_text(tamper_file)
        size = file_size(tamper_file)
        is_identical = (genuine_text == tamper_text)
        byte_identical = (file_size(genuine_path) == size)

        diffs = diff_texts(genuine_text, tamper_text)
        status = "❌ IDENTICAL TEXT (SHALLOW COPY!)" if is_identical else f"✅ {len(diffs)} text differences found"

        print(f"\n  {tamper_file.name}: {size} bytes | byte-identical={byte_identical} | {status}")
        if diffs:
            for d in diffs[:5]:  # Show first 5 diffs
                print(f"    {d}")
            if len(diffs) > 5:
                print(f"    ... and {len(diffs) - 5} more differences")
else:
    print("  genuine.pdf not found!")

# ── 2. REAL CORPUS: Aadhaar Identity ──
print("\n── REAL CORPUS: identity ──")
id_dir = REPO / "samples" / "real_corpus" / "identity"
genuine_aadhaar = id_dir / "aadhaar_genuine.pdf"

if genuine_aadhaar.exists():
    genuine_text = extract_all_text(genuine_aadhaar)
    print(f"  aadhaar_genuine.pdf: {file_size(genuine_aadhaar)} bytes, {len(genuine_text)} chars text")

    for tamper_file in sorted(id_dir.glob("aadhaar_*mismatch*.pdf")) + sorted(id_dir.glob("aadhaar_*typo*.pdf")):
        tamper_text = extract_all_text(tamper_file)
        is_identical = (genuine_text == tamper_text)
        diffs = diff_texts(genuine_text, tamper_text)
        status = "❌ IDENTICAL TEXT (SHALLOW COPY!)" if is_identical else f"✅ {len(diffs)} text differences found"

        print(f"\n  {tamper_file.name}: {file_size(tamper_file)} bytes | {status}")
        if diffs:
            for d in diffs[:5]:
                print(f"    {d}")

    # Check locked
    locked = id_dir / "aadhaar_locked.pdf"
    if locked.exists():
        locked_text = extract_all_text(locked)
        print(f"\n  aadhaar_locked.pdf: {file_size(locked)} bytes | text='{locked_text[:80].strip()}'")
else:
    print("  aadhaar_genuine.pdf not found!")

# ── 3. REAL CORPUS: Edge cases ──
print("\n── REAL CORPUS: edge cases ──")
edge_dir = REPO / "samples" / "real_corpus" / "edge"
if edge_dir.exists():
    for f in sorted(edge_dir.glob("*.pdf")):
        size = file_size(f)
        text = extract_all_text(f)
        is_error = text.startswith("[ERROR")
        print(f"  {f.name}: {size} bytes | {'error on open (expected)' if is_error else f'{len(text)} chars text'}")

# ── 4. MASS CORPUS: Sample audit of first 5 tampered statements ──
print("\n── MASS CORPUS: spot-check first 5 statements ──")
mass_stmt = REPO / "samples" / "mass_corpus" / "statements"
mass_genuine = mass_stmt / "stmt_000_genuine.pdf"

if mass_genuine.exists():
    genuine_text = extract_all_text(mass_genuine)
    print(f"  stmt_000_genuine.pdf: {file_size(mass_genuine)} bytes, {len(genuine_text)} chars")

    for i in range(1, 6):
        tamper = mass_stmt / f"stmt_{i:03d}_tampered.pdf"
        if tamper.exists():
            tamper_text = extract_all_text(tamper)
            is_identical = (genuine_text == tamper_text)
            diffs = diff_texts(genuine_text, tamper_text)
            status = "❌ IDENTICAL (SHALLOW!)" if is_identical else f"✅ {len(diffs)} diffs"
            print(f"  {tamper.name}: {file_size(tamper)} bytes | {status}")
            if diffs:
                for d in diffs[:3]:
                    print(f"    {d}")
else:
    print("  Mass corpus not found!")

# ── 5. MASS CORPUS: Sample audit of first 5 tampered Aadhaars ──
print("\n── MASS CORPUS: spot-check first 5 Aadhaars ──")
mass_id = REPO / "samples" / "mass_corpus" / "identity"
mass_genuine_id = mass_id / "aadhaar_000_genuine.pdf"

if mass_genuine_id.exists():
    genuine_text = extract_all_text(mass_genuine_id)
    print(f"  aadhaar_000_genuine.pdf: {file_size(mass_genuine_id)} bytes, {len(genuine_text)} chars")

    for i in range(1, 6):
        tamper = mass_id / f"aadhaar_{i:03d}_tampered.pdf"
        if tamper.exists():
            tamper_text = extract_all_text(tamper)
            is_identical = (genuine_text == tamper_text)
            diffs = diff_texts(genuine_text, tamper_text)
            status = "❌ IDENTICAL (SHALLOW!)" if is_identical else f"✅ {len(diffs)} diffs"
            print(f"  {tamper.name}: {file_size(tamper)} bytes | {status}")
            if diffs:
                for d in diffs[:3]:
                    print(f"    {d}")
else:
    print("  Mass corpus identity not found!")

# ── 6. CAMS: check if the search target "10000.00" even exists in source ──
print("\n── SEARCH TARGET VALIDATION ──")
cams_genuine = REPO / "samples" / "real_corpus" / "canara_cams" / "genuine.pdf"
if cams_genuine.exists():
    text = extract_all_text(cams_genuine)
    has_target = "10000.00" in text
    print(f"  canara_cams/genuine.pdf contains '10000.00': {has_target}")
    if not has_target:
        print("  ⚠️  WARNING: The search target '10000.00' was NOT FOUND in the source PDF!")
        print("     This means tamper_amount_inflate.pdf is likely an UNMODIFIED copy!")

canara_genuine = REPO / "samples" / "real_corpus" / "canara_direct" / "genuine.pdf"
if canara_genuine.exists():
    text = extract_all_text(canara_genuine)
    for amt in ["5,80,000.00", "22,562.16", "295.00", "5,84,115.00"]:
        found = amt in text
        sym = "✅" if found else "❌"
        print(f"  canara_direct/genuine.pdf contains '{amt}': {sym}")

aadhaar_genuine = REPO / "samples" / "real_corpus" / "identity" / "aadhaar_genuine.pdf"
if aadhaar_genuine.exists():
    text = extract_all_text(aadhaar_genuine)
    for target in ["Karnala Santhan Kumar", "KARNALA SANTHAN KUMAR", "2797 8827 4735"]:
        found = target in text
        sym = "✅" if found else "❌"
        print(f"  identity/aadhaar_genuine.pdf contains '{target}': {sym}")

print("\n" + "=" * 80)
print("AUDIT COMPLETE")
print("=" * 80)
