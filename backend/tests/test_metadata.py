"""Discrimination tests for the PDF structure/metadata forensics analyzer.

These prove the analyzer *separates* a clean bank-style PDF from structurally-anomalous forgeries —
and would FAIL against any constant return (a clean single-save legit-producer PDF must score 0.0
suspicion; a tampered one must score high — no constant satisfies both). Fixtures are GENERATED
programmatically with pikepdf, never hand-tuned until a test passes.

Must-fail fixtures (BUILD-MANIFEST "PDF metadata/structure forensics"):
  * an editing-tool producer string on a purported statement  -> flagged
  * an appended incremental-update (shadow-attack) section     -> flagged
False-positive control (RESEARCH-001 / TESTING-STRATEGY Tier-2):
  * a legitimate print-to-PDF producer                         -> NOT flagged
Honest non-coverage:
  * a metadata-stripped-but-otherwise-clean single-save PDF is only mildly flagged, not "tampered".
"""

from __future__ import annotations

import io
import re

import pikepdf
import pytest

from app.contracts import AnalysisContext, Mode, SignalStatus
from forensics.metadata import (
    PdfStructureAnalyzer,
    analyze_structure,
    count_incremental_updates,
    parse_pdf_date,
    suspicion_from_findings,
)

# --- programmatic fixture builders ----------------------------------------------------------

def _build_pdf(
    *,
    producer: str | None = None,
    creator: str | None = None,
    creation_date: str | None = None,
    mod_date: str | None = None,
) -> bytes:
    """A real single-save PDF with the given /Info metadata. static_id keeps bytes deterministic."""
    pdf = pikepdf.Pdf.new()
    pdf.add_blank_page(page_size=(420, 595))
    if producer is not None:
        pdf.docinfo[pikepdf.Name.Producer] = producer
    if creator is not None:
        pdf.docinfo[pikepdf.Name.Creator] = creator
    if creation_date is not None:
        pdf.docinfo[pikepdf.Name.CreationDate] = creation_date
    if mod_date is not None:
        pdf.docinfo[pikepdf.Name.ModDate] = mod_date
    buf = io.BytesIO()
    pdf.save(buf, static_id=True)
    return buf.getvalue()


def clean_bank_pdf() -> bytes:
    """A genuine-style statement: legitimate generator producer, coherent dates, single save."""
    return _build_pdf(
        producer="iText 7 (bank statement service)",
        creator="Canara Bank Core Banking",
        creation_date="D:20240601090000+05'30'",
        mod_date="D:20240601090000+05'30'",
    )


def print_to_pdf_control() -> bytes:
    """False-positive control: a legitimate OS print-to-PDF driver — must NOT be flagged."""
    return _build_pdf(
        producer="Microsoft: Print To PDF",
        creator="Microsoft: Print To PDF",
        creation_date="D:20240601090000+05'30'",
        mod_date="D:20240601090000+05'30'",
    )


def chromium_print_control() -> bytes:
    """Second FP control: Chromium 'Save as PDF' (Skia/PDF) — a legitimate print path."""
    return _build_pdf(
        producer="Skia/PDF m120",
        creator="Chromium",
        creation_date="D:20240601090000+05'30'",
        mod_date="D:20240601090000+05'30'",
    )


def photoshop_pdf() -> bytes:
    """Adversarial: an editing-tool producer on a purported statement — must be flagged."""
    return _build_pdf(
        producer="Adobe Photoshop 25.0 (Macintosh)",
        creator="Adobe Photoshop",
        creation_date="D:20240601090000+05'30'",
        mod_date="D:20240601090000+05'30'",
    )


def impossible_date_pdf() -> bytes:
    """Adversarial: ModDate strictly BEFORE CreationDate — forged metadata, must be flagged."""
    return _build_pdf(
        producer="iText 7 (bank statement service)",
        creation_date="D:20240601090000+05'30'",
        mod_date="D:20230101090000+05'30'",  # a year EARLIER -> impossible
    )


def incremental_update_pdf(producer: str = "iText 7 (bank statement service)") -> bytes:
    """Adversarial: a clean base PDF with a real incremental-update section APPENDED.

    This mirrors a post-save / post-signing edit (the PAdES shadow-attack pattern): bytes appended
    after the first %%EOF, a fresh xref section, and a trailer whose /Prev chains to the prior xref.
    pikepdf still parses it as a valid PDF, but the raw bytes carry the tell-tale second generation.
    """
    base = _build_pdf(
        producer=producer,
        creation_date="D:20240601090000+05'30'",
        mod_date="D:20240601090000+05'30'",
    )
    m = re.search(rb"startxref\s+(\d+)\s+%%EOF", base)
    assert m, "base PDF must have a startxref/%%EOF to chain from"
    prev_xref_offset = int(m.group(1))

    # Carry forward the base trailer's /Root and /Info references so the incremental update is a
    # faithful continuation of the original (a real incremental update keeps these in its trailer).
    base_trailer = re.search(rb"trailer\s*<<(.+?)>>", base, re.S).group(1)
    root_ref = re.search(rb"/Root\s+(\d+\s+\d+\s+R)", base_trailer).group(1)
    info_match = re.search(rb"/Info\s+(\d+\s+\d+\s+R)", base_trailer)
    info_clause = b" /Info " + info_match.group(1) if info_match else b""

    appended_obj_offset = len(base)
    new_obj = b"5 0 obj\n<< /Note (incremental update) >>\nendobj\n"
    body = base + new_obj
    new_xref_offset = len(body)
    xref = (
        b"xref\n"
        b"0 1\n"
        b"0000000000 65535 f \n"
        b"5 1\n" + f"{appended_obj_offset:010d} 00000 n \n".encode()
    )
    trailer = (
        b"trailer\n"
        b"<< /Size 6 /Root " + root_ref + info_clause
        + b" /Prev " + str(prev_xref_offset).encode() + b" >>\n"
        b"startxref\n" + str(new_xref_offset).encode() + b"\n"
        b"%%EOF\n"
    )
    return body + xref + trailer


def _append_generation(base: bytes, new_obj: bytes, obj_num: int) -> bytes:
    """Append ONE real incremental-update generation carrying ``new_obj``, chaining /Prev to the
    most-recent xref. Re-usable so a signed doc and a shadow attack can be built by composition."""
    last = list(re.finditer(rb"startxref\s+(\d+)\s+%%EOF", base))[-1]
    prev_xref_offset = int(last.group(1))
    base_trailer = re.search(rb"trailer\s*<<(.+?)>>", base, re.S).group(1)
    root_ref = re.search(rb"/Root\s+(\d+\s+\d+\s+R)", base_trailer).group(1)
    info_match = re.search(rb"/Info\s+(\d+\s+\d+\s+R)", base_trailer)
    info_clause = b" /Info " + info_match.group(1) if info_match else b""

    appended_obj_offset = len(base)
    body = base + new_obj
    new_xref_offset = len(body)
    xref = (
        b"xref\n0 1\n0000000000 65535 f \n"
        + f"{obj_num} 1\n".encode()
        + f"{appended_obj_offset:010d} 00000 n \n".encode()
    )
    trailer = (
        b"trailer\n<< /Size " + str(obj_num + 1).encode() + b" /Root " + root_ref + info_clause
        + b" /Prev " + str(prev_xref_offset).encode() + b" >>\n"
        b"startxref\n" + str(new_xref_offset).encode() + b"\n%%EOF\n"
    )
    return body + xref + trailer


def signed_pdf_one_revision() -> bytes:
    """A legitimately e-signed PDF: a clean base + ONE incremental update that IS the signature
    (carries ``/ByteRange``). A PAdES signature is itself one incremental generation — a DigiLocker
    doc / signed bank e-statement (the documents we target) must NOT be flagged for being signed."""
    base = _build_pdf(
        producer="iText 7 (bank statement service)",
        creation_date="D:20240601090000+05'30'",
        mod_date="D:20240601090000+05'30'",
    )
    sig_obj = b"5 0 obj\n<< /Type /Sig /Filter /Adobe.PPKLite /ByteRange [0 0 0 0] >>\nendobj\n"
    return _append_generation(base, sig_obj, 5)


def shadow_attacked_signed_pdf() -> bytes:
    """A shadow attack: sign (1 update, /ByteRange), THEN append a change (a 2nd update). Exactly one
    POST-signing update remains — it must still be flagged (the discount is one signing revision, not
    a blanket amnesty for signed files)."""
    edit_obj = b"6 0 obj\n<< /Note (post-signing edit) >>\nendobj\n"
    return _append_generation(signed_pdf_one_revision(), edit_obj, 6)


def _ctx(raw: bytes | None, mime: str = "application/pdf") -> AnalysisContext:
    return AnalysisContext(
        session_id="t",
        intake_mode=Mode.FILE,
        doc_type="financial_statement",
        file_bytes=raw,
        file_name="statement.pdf",
        file_mime=mime,
    )


# --- pure-function level: prove the building blocks discriminate ----------------------------

def test_incremental_update_count_distinguishes_single_save_from_appended():
    assert count_incremental_updates(clean_bank_pdf()) == 0
    assert count_incremental_updates(incremental_update_pdf()) == 1


def test_parse_pdf_date_handles_real_and_garbage():
    assert parse_pdf_date("D:20240601090000+05'30'").year == 2024
    assert parse_pdf_date(None) is None
    assert parse_pdf_date("not-a-date") is None


def test_clean_findings_have_no_anomalies():
    f = analyze_structure(clean_bank_pdf())
    assert f.editing_tool_hits == []
    assert f.legitimate_producer is True
    assert f.incremental_updates == 0
    assert f.impossible_date_order is False
    assert suspicion_from_findings(f) == 0.0


def test_photoshop_findings_flag_editing_tool():
    f = analyze_structure(photoshop_pdf())
    assert "photoshop" in " ".join(f.editing_tool_hits)
    assert f.legitimate_producer is False
    assert suspicion_from_findings(f) > 0.0


# --- analyzer-level discrimination (the LayerSignal contract) -------------------------------

def test_clean_bank_pdf_is_low_suspicion():
    sig = PdfStructureAnalyzer().analyze(_ctx(clean_bank_pdf()))
    assert sig.status == SignalStatus.VALID
    assert sig.suspicion == 0.0
    assert sig.weight > 0.0


def test_print_to_pdf_is_not_flagged_false_positive_control():
    """RESEARCH-001 FP guard: a legitimate OS print-to-PDF producer must score 0.0, never flagged."""
    sig = PdfStructureAnalyzer().analyze(_ctx(print_to_pdf_control()))
    assert sig.status == SignalStatus.VALID
    assert sig.suspicion == 0.0
    assert sig.measurements["legitimate_producer"] is True
    assert sig.measurements["editing_tool_hits"] == []


def test_chromium_skia_print_is_not_flagged():
    sig = PdfStructureAnalyzer().analyze(_ctx(chromium_print_control()))
    assert sig.status == SignalStatus.VALID
    assert sig.suspicion == 0.0


def test_photoshop_producer_is_flagged():
    """Must-fail fixture: an editing-tool producer on a purported statement is flagged."""
    sig = PdfStructureAnalyzer().analyze(_ctx(photoshop_pdf()))
    assert sig.status == SignalStatus.VALID
    assert sig.suspicion >= 0.5
    assert "photoshop" in " ".join(sig.measurements["editing_tool_hits"]).lower()


def test_incremental_update_is_flagged_shadow_attack():
    """Must-fail fixture: an appended incremental-update section is flagged (post-edit indicator)."""
    sig = PdfStructureAnalyzer().analyze(_ctx(incremental_update_pdf()))
    assert sig.status == SignalStatus.VALID
    assert sig.suspicion >= 0.4
    assert sig.measurements["incremental_updates"] >= 1
    assert sig.measurements["has_prev_xref"] is True


def test_signed_pdf_signing_revision_is_not_flagged_false_positive():
    """A legitimately e-signed PDF's signature is itself ONE incremental update — discounted, so it
    must NOT raise the post-edit/shadow-attack penalty (DigiLocker / signed bank statements are our
    primary targets). Discriminates against the UNSIGNED appended-edit case, which IS flagged."""
    f = analyze_structure(signed_pdf_one_revision())
    assert f.has_signature is True
    assert f.incremental_updates == 1     # the raw structural count still sees the signing revision
    assert f.post_signing_updates == 0    # but it is discounted -> no shadow-attack penalty
    sig = PdfStructureAnalyzer().analyze(_ctx(signed_pdf_one_revision()))
    assert sig.measurements["post_signing_updates"] == 0
    assert sig.suspicion == 0.0  # cleanly-signed, coherent dates, legit producer -> no anomaly
    # The unsigned appended-edit fixture (no /ByteRange) is NOT discounted -> still flagged.
    unsigned = PdfStructureAnalyzer().analyze(_ctx(incremental_update_pdf()))
    assert unsigned.measurements["post_signing_updates"] == 1
    assert unsigned.suspicion is not None and unsigned.suspicion > 0.0


def test_shadow_attack_on_signed_pdf_is_still_flagged():
    """Must-fail: the discount is EXACTLY one signing revision. A shadow attack (sign, THEN append)
    leaves a post-signing update that must still be flagged. Would FAIL if the discount swallowed it."""
    f = analyze_structure(shadow_attacked_signed_pdf())
    assert f.has_signature is True
    assert f.incremental_updates == 2
    assert f.post_signing_updates == 1
    sig = PdfStructureAnalyzer().analyze(_ctx(shadow_attacked_signed_pdf()))
    assert sig.status == SignalStatus.VALID
    assert sig.suspicion >= 0.4
    assert sig.measurements["post_signing_updates"] == 1


def test_impossible_date_order_is_flagged():
    sig = PdfStructureAnalyzer().analyze(_ctx(impossible_date_pdf()))
    assert sig.status == SignalStatus.VALID
    assert sig.suspicion >= 0.5
    assert sig.measurements["impossible_date_order"] is True


def test_analyzer_discriminates_clean_vs_tampered():
    """The core discrimination property — would FAIL against any constant return."""
    az = PdfStructureAnalyzer()
    clean = az.analyze(_ctx(clean_bank_pdf()))
    photoshop = az.analyze(_ctx(photoshop_pdf()))
    incremental = az.analyze(_ctx(incremental_update_pdf()))

    assert clean.suspicion == 0.0
    assert photoshop.suspicion > clean.suspicion
    assert incremental.suspicion > clean.suspicion
    # and the legitimate print-to-PDF control sits with the clean one, NOT with the forgeries:
    print_to_pdf = az.analyze(_ctx(print_to_pdf_control()))
    assert print_to_pdf.suspicion == clean.suspicion
    assert print_to_pdf.suspicion < photoshop.suspicion


def test_combined_anomalies_stack_but_cap_at_one():
    """An editing tool AND an incremental update on the same file is more suspicious than either,
    capped at 1.0 — proves the components are additive and monotone, not a single binary flag."""
    raw = incremental_update_pdf(producer="Adobe Photoshop 25.0")
    sig = PdfStructureAnalyzer().analyze(_ctx(raw))
    only_photoshop = PdfStructureAnalyzer().analyze(_ctx(photoshop_pdf()))
    assert sig.suspicion > only_photoshop.suspicion
    assert sig.suspicion <= 1.0


# --- honest gates & fail-closed -------------------------------------------------------------

def test_non_pdf_is_not_evaluated():
    """A PNG is not a PDF — structure/metadata forensics do not apply -> NOT_EVALUATED, not a pass."""
    png_magic = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    sig = PdfStructureAnalyzer().analyze(_ctx(png_magic, mime="image/png"))
    assert sig.status == SignalStatus.NOT_EVALUATED
    assert sig.suspicion is None  # never a fabricated pass


def test_unparsable_pdf_fails_closed_to_error():
    """A file with a %PDF- header but corrupt body must ERROR (fail-closed), never silently pass."""
    garbage = b"%PDF-1.7\n" + b"\xde\xad\xbe\xef" * 200  # header present, body unparsable
    sig = PdfStructureAnalyzer().analyze(_ctx(garbage))
    assert sig.status == SignalStatus.ERROR
    assert sig.suspicion is None


def test_no_bytes_is_not_evaluated():
    sig = PdfStructureAnalyzer().analyze(_ctx(None))
    assert sig.status == SignalStatus.NOT_EVALUATED


def test_metadata_stripped_is_mild_not_tampered():
    """Honest non-coverage: a clean single-save PDF with NO metadata is only mildly flagged
    (missing-metadata signal), NOT scored as a high-confidence tamper — a forger can always strip
    metadata, so this must not masquerade as strong evidence."""
    raw = _build_pdf()  # no producer, no creator, no dates
    sig = PdfStructureAnalyzer().analyze(_ctx(raw))
    assert sig.status == SignalStatus.VALID
    assert 0.0 < sig.suspicion < 0.5  # mild, not a tamper verdict
    assert sig.measurements["missing_metadata"] is True


def test_publishes_findings_to_shared():
    ctx = _ctx(incremental_update_pdf())
    PdfStructureAnalyzer().analyze(ctx)
    assert "pdf_structure" in ctx.shared
    assert ctx.shared["pdf_structure"].incremental_updates >= 1


# --- the constant-return litmus (TESTING-STRATEGY §2) ---------------------------------------

def test_would_fail_against_a_constant():
    """Encodes the §3.2 litmus: a constant-returning fake cannot satisfy BOTH a clean=0.0 and a
    tampered>=0.4 assertion. This test asserts the *spread* exists, so replacing analyze() with any
    single constant breaks at least one inequality."""
    az = PdfStructureAnalyzer()
    clean = az.analyze(_ctx(clean_bank_pdf())).suspicion
    tampered = az.analyze(_ctx(incremental_update_pdf())).suspicion
    assert clean == 0.0 and tampered >= 0.4
    assert clean != tampered


@pytest.mark.parametrize(
    "builder", [photoshop_pdf, incremental_update_pdf, impossible_date_pdf]
)
def test_every_adversarial_variant_is_flagged(builder):
    sig = PdfStructureAnalyzer().analyze(_ctx(builder()))
    assert sig.status == SignalStatus.VALID
    assert sig.suspicion is not None and sig.suspicion > 0.0
