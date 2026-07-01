"""Discrimination tests for PDF font-object consistency (forensics/pdf_fonts.py, KNOWN_ISSUES #3).

The subset-tag inconsistency signal is proven two ways (CLAUDE.md §3.2): the pure analysis discriminates
a re-embed/edit (multiple subsets of one face) from legitimate multi-font layout, and — critically for
"do not false-reject genuine documents" — a real genuine born-digital PDF scores ZERO. Every test would
FAIL against a constant return.
"""

from __future__ import annotations

from app.contracts import AnalysisContext, Mode, SignalStatus
from forensics.pdf_fonts import (
    PdfFontConsistencyAnalyzer,
    analyze_font_consistency,
    extract_font_usage,
    suspicion_from_findings,
)

# --- pure analysis: the discriminative claim ------------------------------------------------------


def test_consistent_single_subset_is_clean():
    findings = analyze_font_consistency(["ABCDEF+ArialMT"] * 10)
    assert findings.inconsistent_bases == []
    assert suspicion_from_findings(findings) == 0.0


def test_multiple_subsets_of_same_base_are_flagged():
    """A re-embed of the SAME face under a second subset tag is the edit fingerprint."""
    fonts = ["ABCDEF+ArialMT"] * 8 + ["GHIJKL+ArialMT"] * 2
    findings = analyze_font_consistency(fonts)
    assert findings.inconsistent_bases == ["ArialMT"]
    assert suspicion_from_findings(findings) >= 0.45


def test_subset_plus_nonsubset_same_base_is_flagged():
    fonts = ["ABCDEF+TimesNewRoman"] * 5 + ["TimesNewRoman"] * 3
    findings = analyze_font_consistency(fonts)
    assert "TimesNewRoman" in findings.inconsistent_bases
    assert suspicion_from_findings(findings) > 0.0


def test_distinct_faces_each_with_one_tag_is_clean():
    """Legitimate multi-font layout (a bold header + a body face) is NOT tampering — each face one tag."""
    fonts = ["ABCDEF+ArialMT"] * 10 + ["ABCDEF+Arial-BoldMT"] * 4
    findings = analyze_font_consistency(fonts)
    assert findings.inconsistent_bases == []
    assert suspicion_from_findings(findings) == 0.0


def test_more_inconsistent_bases_raise_suspicion():
    one = analyze_font_consistency(["ABCDEF+Arial", "GHIJKL+Arial"])
    two = analyze_font_consistency(["ABCDEF+Arial", "GHIJKL+Arial", "MNOPQR+Times", "STUVWX+Times"])
    assert suspicion_from_findings(two) > suspicion_from_findings(one)


# --- real PDF extraction + the analyzer -----------------------------------------------------------


def _pdf(lines: list[str]) -> bytes:
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    y = 40
    for line in lines:
        page.insert_text((40, y), line, fontsize=11)
        y += 16
    out = doc.tobytes()
    doc.close()
    return out


def test_extract_font_usage_reads_real_pdf_fonts():
    fonts, embedded = extract_font_usage(_pdf(["Balance", "15,000.00", "Closing"]))
    assert fonts, "a born-digital PDF must yield span font names"
    assert all(isinstance(f, str) for f in fonts)
    assert "Helvetica" in embedded and embedded["Helvetica"] is False  # standard-14 => not embedded


def test_genuine_born_digital_pdf_scores_zero_no_false_positive():
    """The must-not-regress case: a genuine single-font statement must NEVER be flagged."""
    raw = _pdf([f"Row {i} Salary 1{i},000.00 Balance 2{i},000.00" for i in range(10)])
    sig = PdfFontConsistencyAnalyzer().analyze(
        AnalysisContext(session_id="s", intake_mode=Mode.FILE, file_bytes=raw)
    )
    assert sig.status == SignalStatus.VALID
    assert sig.suspicion == 0.0
    assert sig.measurements["inconsistent_bases"] == []


def test_scan_or_non_pdf_is_not_evaluated():
    """No text layer (a scan) / non-PDF -> NOT_EVALUATED; the pixel path covers that medium."""
    sig = PdfFontConsistencyAnalyzer().analyze(
        AnalysisContext(session_id="s", intake_mode=Mode.FILE, file_bytes=b"\x89PNG\r\n not a pdf")
    )
    assert sig.status == SignalStatus.NOT_EVALUATED
    assert sig.suspicion is None
