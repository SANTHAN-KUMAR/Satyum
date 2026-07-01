"""Tier-2 forensic signal: PDF FONT-OBJECT consistency for born-digital documents (KNOWN_ISSUES #3).

This is the deterministic, layout-agnostic answer to "the pixel Z-score false-flags genuine documents":
instead of measuring rasterised glyph geometry (which is inherently layout-dependent and a category
error on vector text), we interrogate the PDF's own FONT OBJECTS and compare the document *to itself*.

The reliable, low-false-positive tell for a born-digital edit is **subset-tag inconsistency**. When a
generator embeds a font it emits a single subset — a 6-uppercase-letter tag, e.g. ``ABCDEF+ArialMT`` —
used consistently across the whole document. An editor that re-embeds a font to render an *edited* text
run creates a SECOND subset of the same base face (``GHIJKL+ArialMT``), or mixes the embedded subset
with a non-subset copy. A single-pass genuine render never does this; two subsets of one base face is a
structural fingerprint of a re-save/edit — and it needs no corpus, no per-bank template, no threshold
tuning, because the reference is the document itself.

Honest bound (CLAUDE.md §3.1/§3.5; the same bound stated to the user): this catches the common editor
(re-embed / substitute), NOT a skilled forger who re-embeds into the *same* subset or replaces the whole
font uniformly (e.g. Sejda). It is therefore graded, low-weight, orthogonal evidence — one converging
vote alongside metadata/xref forensics (``forensics/metadata.py``) and the arithmetic engine — never a
dispositive gate. Producer/metadata and incremental-update/shadow-attack forensics live in metadata.py;
this module adds only the font-object dimension. Deterministic, no render, no network.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.config import settings
from app.contracts import AnalysisContext, LayerSignal, Mode

# 6-uppercase-letter subset prefix that precedes an embedded-subset font name (``ABCDEF+ArialMT``).
_SUBSET_PREFIX_RE = re.compile(r"^([A-Z]{6})\+(.+)$")

# Suspicion for a base font face that appears under more than one subset tag (a re-embed / edit tell).
# Graded, low — corroborating evidence, not a gate. DEFAULT — needs calibration on a real corpus.
SUSPICION_SUBSET_INCONSISTENCY: float = 0.45
# Extra per additional inconsistent base face, with diminishing weight; capped in the aggregate.
SUSPICION_PER_EXTRA_INCONSISTENT_BASE: float = 0.10
# Only assess a document with at least this many distinct fonts / this many text spans — too few and
# the signal is not meaningful (a one-font statement can never be subset-inconsistent).
MIN_SPANS_TO_ASSESS: int = 8


def _base_and_prefix(font_name: str) -> tuple[str, str | None]:
    """Split ``ABCDEF+ArialMT`` into ``("ArialMT", "ABCDEF")``; a non-subset name → ``(name, None)``."""
    m = _SUBSET_PREFIX_RE.match(font_name or "")
    return (m.group(2), m.group(1)) if m else (font_name or "", None)


@dataclass
class FontFindings:
    """Typed, side-effect-free result of the font-object consistency analysis."""

    total_spans: int = 0
    distinct_fonts: list[str] = field(default_factory=list)
    # base face -> the distinct subset tags it appears under (``None`` = a non-subset occurrence)
    subset_tags_by_base: dict[str, list[str | None]] = field(default_factory=dict)
    inconsistent_bases: list[str] = field(default_factory=list)  # base faces under >1 distinct tag
    embedded_fonts: list[str] = field(default_factory=list)
    non_embedded_fonts: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


def analyze_font_consistency(
    span_font_names: list[str], embedded_by_name: dict[str, bool] | None = None
) -> FontFindings:
    """Pure analysis: given every text span's font name (+ optional embedded map), find subset-tag
    inconsistency. Deterministic, no I/O — directly unit-testable with synthetic font lists."""
    findings = FontFindings(total_spans=len(span_font_names))
    findings.distinct_fonts = sorted(set(span_font_names))

    tags: dict[str, set[str | None]] = {}
    for name in span_font_names:
        base, prefix = _base_and_prefix(name)
        tags.setdefault(base, set()).add(prefix)
    findings.subset_tags_by_base = {b: sorted(t, key=lambda x: (x is None, x)) for b, t in tags.items()}
    # A base face rendered under MORE THAN ONE distinct tag (two subsets, or subset + non-subset) is the
    # re-embed/edit fingerprint. One tag per base (the single-render norm) is clean.
    findings.inconsistent_bases = sorted(b for b, t in tags.items() if len(t) > 1)

    emb = embedded_by_name or {}
    findings.embedded_fonts = sorted(n for n, e in emb.items() if e)
    findings.non_embedded_fonts = sorted(n for n, e in emb.items() if not e)

    for base in findings.inconsistent_bases:
        shown = ", ".join(
            (f"{tag}+{base}" if tag else base) for tag in findings.subset_tags_by_base[base]
        )
        findings.reasons.append(
            f"font face '{base}' appears under multiple subset tags ({shown}) — a re-embed / edited "
            "text run (a single genuine render emits one subset per face)"
        )
    return findings


def suspicion_from_findings(findings: FontFindings) -> float:
    """Combine the font-object sub-signals into a single suspicion in [0, 1] (graded, capped)."""
    if not findings.inconsistent_bases:
        return 0.0
    suspicion = SUSPICION_SUBSET_INCONSISTENCY
    suspicion += SUSPICION_PER_EXTRA_INCONSISTENT_BASE * (len(findings.inconsistent_bases) - 1)
    return float(min(1.0, suspicion))


def _looks_like_pdf(raw: bytes) -> bool:
    return raw[:5] == b"%PDF-" or b"%PDF-" in raw[:1024]


def extract_font_usage(raw: bytes, password: str | None = None) -> tuple[list[str], dict[str, bool]]:
    """Read every text span's font name + an embedded map from a born-digital PDF (all pages).

    Returns ``([], {})`` when the file is not a PDF or has no text layer (a scan) — the caller then
    leaves the signal NOT_EVALUATED. Never raises: a malformed PDF degrades to no signal, fail-closed.
    """
    if not _looks_like_pdf(raw):
        return [], {}
    try:
        import pymupdf
    except ImportError:
        return [], {}
    span_fonts: list[str] = []
    embedded: dict[str, bool] = {}
    try:
        doc = pymupdf.open(stream=raw, filetype="pdf")
    except Exception:  # noqa: BLE001 — a malformed PDF yields no signal, never raises
        return [], {}
    try:
        if doc.needs_pass and not (password and doc.authenticate(password)):
            return [], {}
        for page in doc:
            try:
                data = page.get_text("dict")
            except Exception:  # noqa: BLE001 — skip an unreadable page, keep the rest
                continue
            for block in data.get("blocks", []):
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        name = span.get("font")
                        if name and (span.get("text") or "").strip():
                            span_fonts.append(str(name))
            # get_fonts(full=True): (xref, ext, type, basefont, name, encoding, referencer);
            # ext == 'n/a' (or empty) means the font is NOT embedded.
            for entry in page.get_fonts(full=True):
                ext = entry[1] if len(entry) > 1 else "n/a"
                basefont = str(entry[3]) if len(entry) > 3 else ""
                if basefont:
                    embedded[basefont] = bool(ext) and str(ext).lower() not in ("n/a", "")
    finally:
        doc.close()
    return span_fonts, embedded


_HONEST_BOUND = (
    "font-object consistency catches the common editor (re-embed / font substitution); a skilled forger "
    "who re-embeds into the same subset or replaces the whole face uniformly defeats it — graded, "
    "corroborating evidence alongside metadata/xref forensics and the arithmetic engine, never a gate"
)


class PdfFontConsistencyAnalyzer:
    """Tier-2 (layer 3) FILE-mode analyzer: born-digital PDF font-object consistency (KNOWN_ISSUES #3).

    The layout-agnostic replacement for the pixel Z-score on born-digital documents: it compares the
    document's font objects to themselves. Non-PDF / no text layer (a scan) → NOT_EVALUATED (the pixel
    path in ``forensics/layout.py`` handles that medium). Otherwise a graded, low-weight VALID signal.
    """

    name = "pdf_font_consistency"
    layer = 3
    mode = Mode.FILE
    order = 33  # after font_layout (32); both are low-weight typography signals, one per medium

    def applicable(self, ctx: AnalysisContext) -> bool:
        return ctx.intake_mode == Mode.FILE and bool(ctx.file_bytes)

    def analyze(self, ctx: AnalysisContext) -> LayerSignal:
        raw = ctx.file_bytes
        if not raw:
            return LayerSignal.not_evaluated(self.name, self.layer, self.mode, "no file bytes to analyse")

        span_fonts, embedded = extract_font_usage(raw, password=ctx.pdf_password)
        if len(span_fonts) < MIN_SPANS_TO_ASSESS:
            # Not a born-digital PDF (a scan has no text layer), or too little text to assess — the
            # pixel-forensic path covers scans; here we honestly abstain rather than assert on nothing.
            return LayerSignal.not_evaluated(
                self.name,
                self.layer,
                self.mode,
                "no PDF text layer / too few text spans for font-object analysis "
                "(scanned or image document — pixel typography path applies instead)",
                span_count=len(span_fonts),
            )

        findings = analyze_font_consistency(span_fonts, embedded)
        suspicion = suspicion_from_findings(findings)
        measurements: dict[str, Any] = {
            "total_spans": findings.total_spans,
            "distinct_fonts": findings.distinct_fonts,
            "inconsistent_bases": findings.inconsistent_bases,
            "embedded_fonts": findings.embedded_fonts,
            "non_embedded_fonts": findings.non_embedded_fonts,
            "honest_bound": _HONEST_BOUND,
        }
        reason = (
            "font objects are consistent (one subset per face — a single genuine render)"
            if suspicion == 0.0
            else "; ".join(findings.reasons)
        )
        return LayerSignal.valid(
            self.name,
            self.layer,
            self.mode,
            suspicion,
            settings.weight_font_layout,  # same low weight as the pixel path; one runs per medium
            reason,
            measurements=measurements,
        )
