#!/usr/bin/env python3
"""Mass Corpus Generator for Satyum.

Generates 500 statement variants and 500 Aadhaar variants by programmatically
combining different forgery techniques (inflations, typos, date changes)
and applying them to the source PDFs. Only PDFs are generated to save disk space
and speed up test execution.

Usage:
    cd <repo_root>
    backend/.venv/bin/python samples/generate_mass_corpus.py
"""

from __future__ import annotations

import concurrent.futures
import random
import shutil
import string
import sys
from pathlib import Path
import pymupdf

REPO = Path(__file__).resolve().parent.parent
BACKEND = REPO / "backend"
sys.path.insert(0, str(BACKEND))

CORPUS_DIR = REPO / "samples" / "mass_corpus"
SRC_CANARA = REPO / "652591331-Canara-Bank-Statement.pdf"
SRC_AADHAAR = REPO / "aadhars" / "my aadhar.pdf"

random.seed(42)  # Deterministic generation

def _ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)

def _pdf_replace_text(src_path: Path, replacements: list[tuple[str, str]], out_path: Path):
    doc = pymupdf.open(str(src_path))
    for page in doc:
        for old_text, new_text in replacements:
            hits = page.search_for(old_text)
            for rect in hits:
                page.add_redact_annot(rect, text=new_text, fontsize=0, align=pymupdf.TEXT_ALIGN_LEFT)
        page.apply_redactions()
    doc.save(str(out_path))
    doc.close()

# ── Statement Extraction ──

# Seed values extracted from the Canara PDF to build combinations
AMOUNTS_IN_PDF = [
    "5,000.00", "295.00", "4,705.00", "590.00", "4,115.00",
    "5,80,000.00", "5,84,115.00", "3,00,000.00", "2,84,115.00",
    "1,00,000.00", "1,84,115.00", "1,80,000.00", "1,98,000.00",
    "2,02,115.00", "2,00,000.00", "2,115.00", "1,50,000.00",
    "1,52,115.00", "1,20,000.00", "1,22,115.00", "37,000.00",
    "34,885.00", "39,974.00", "42,089.00", "300.00", "41,789.00",
    "38,000.00", "3,789.00", "2,75,000.00", "2,78,789.00"
]

def mutate_amount(amt: str, strategy: str) -> str:
    """Takes a formatted amount '5,000.00' and mutates it."""
    clean = float(amt.replace(",", ""))
    if strategy == "inflate_10":
        clean *= 1.10
    elif strategy == "inflate_50":
        clean *= 1.50
    elif strategy == "zero":
        clean = 0.0
    elif strategy == "penny_siphon":
        clean += 0.99
    
    # Format back to Indian numbering system (approximate for regex match)
    s = f"{clean:,.2f}"
    return s

def _worker_statement(args):
    i, replacements, out_path = args
    _pdf_replace_text(SRC_CANARA, replacements, out_path)
    return i

def generate_mass_statements(count: int = 500):
    print(f"Generating {count} statement combinations...")
    out = CORPUS_DIR / "statements"
    _ensure_dir(out)
    
    # 1 genuine
    shutil.copy2(SRC_CANARA, out / "stmt_000_genuine.pdf")
    
    strategies = ["inflate_10", "inflate_50", "zero", "penny_siphon"]
    
    tasks = []
    for i in range(1, count + 1):
        num_replacements = random.randint(1, 5)
        replacements = []
        for _ in range(num_replacements):
            target = random.choice(AMOUNTS_IN_PDF)
            strat = random.choice(strategies)
            new_val = mutate_amount(target, strat)
            replacements.append((target, new_val))
            
        out_name = f"stmt_{i:03d}_tampered.pdf"
        tasks.append((i, replacements, out / out_name))
        
    with concurrent.futures.ProcessPoolExecutor(max_workers=6) as executor:
        for done_i in executor.map(_worker_statement, tasks):
            if done_i % 50 == 0:
                print(f"  {done_i}/{count} statements generated")

# ── Aadhaar Combinations ──

def mutate_name(name: str) -> str:
    """Introduce typos into the name."""
    chars = list(name)
    idx = random.randint(0, len(chars)-2)
    # Swap adjacent
    chars[idx], chars[idx+1] = chars[idx+1], chars[idx]
    return "".join(chars)

def mutate_aadhaar(num: str) -> str:
    """Mutate Aadhaar number (e.g. '2797 8827 4735')"""
    clean = list(num.replace(" ", ""))
    idx = random.randint(0, 11)
    # Change one digit
    clean[idx] = random.choice([c for c in string.digits if c != clean[idx]])
    # Re-insert spaces
    s = "".join(clean)
    return f"{s[:4]} {s[4:8]} {s[8:]}"

def _worker_aadhaar(args):
    i, replacements, out_path = args
    _pdf_replace_text(SRC_AADHAAR, replacements, out_path)
    return i

def generate_mass_aadhars(count: int = 500):
    print(f"Generating {count} Aadhaar combinations...")
    out = CORPUS_DIR / "identity"
    _ensure_dir(out)
    
    # 1 genuine
    shutil.copy2(SRC_AADHAAR, out / "aadhaar_000_genuine.pdf")
    
    base_name = "Karnala Santhan Kumar"
    base_name_upper = "KARNALA SANTHAN KUMAR"
    base_num = "2797 8827 4735"
    
    tasks = []
    for i in range(1, count + 1):
        replacements = []
        
        # 50% chance of name mismatch, 50% chance of number typo
        if random.random() < 0.5:
            new_name = mutate_name(base_name)
            new_name_upper = mutate_name(base_name_upper)
            replacements.append((base_name, new_name))
            replacements.append((base_name_upper, new_name_upper))
        else:
            new_num = mutate_aadhaar(base_num)
            replacements.append((base_num, new_num))
            
        out_name = f"aadhaar_{i:03d}_tampered.pdf"
        tasks.append((i, replacements, out / out_name))
        
    with concurrent.futures.ProcessPoolExecutor(max_workers=6) as executor:
        for done_i in executor.map(_worker_aadhaar, tasks):
            if done_i % 50 == 0:
                print(f"  {done_i}/{count} Aadhaars generated")

def write_manifest(stmt_count: int, aadhaar_count: int):
    manifest = CORPUS_DIR / "MANIFEST.md"
    manifest.write_text(f"""# Mass Corpus Manifest

Generated {stmt_count} Canara Bank Statements and {aadhaar_count} Aadhaar variants.

- `statements/stmt_000_genuine.pdf`: REVIEW (Unsigned)
- `statements/stmt_*_tampered.pdf`: REJECTED (Arithmetic consistency fails)
- `identity/aadhaar_000_genuine.pdf`: REVIEW
- `identity/aadhaar_*_tampered.pdf`: REJECTED / REVIEW (Identity mismatch)
""")
    print("✓ Manifest written.")

def main():
    print("Starting mass generation. PDFs only.\n")
    if CORPUS_DIR.exists():
        shutil.rmtree(CORPUS_DIR)
        
    generate_mass_statements(500)
    print()
    generate_mass_aadhars(500)
    print()
    write_manifest(500, 500)
    print("\n✅ Done.")

if __name__ == "__main__":
    main()
