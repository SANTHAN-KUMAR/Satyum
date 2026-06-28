"""Tier-2 forensic signal: PDF document-structure / metadata anomaly detection.

A forger who edits a bank statement in an image/document editor and re-exports it leaves
*structural* fingerprints that a genuine print-to-PDF / bank-issued statement does not carry:

  * **Producer / Creator strings** — an editing tool (Photoshop, GIMP, Canva, Word, LibreOffice,
    Inkscape, a generic Skia/Cairo canvas renderer) named on a purported bank statement is weak-to-
    moderate evidence the PDF was authored/edited rather than printed by the bank's core system.
    This is *weighted evidence*, NOT a binary blocklist: RESEARCH-001 warns that legitimate
    print-to-PDF drivers (Microsoft Print to PDF, macOS Quartz, CUPS/Ghostscript, Chromium "Skia")
    produce many genuine statements, so a known print-to-PDF producer must NOT be flagged on its own.
  * **Incremental updates / multiple xref generations** — a PDF that has been saved, then had bytes
    appended after ``%%EOF`` with a new cross-reference section chained via ``/Prev`` to the previous
    one, has been *edited after its original save*. On a signed document this is the classic
    PAdES **shadow-attack / post-signing edit** indicator; on any statement it shows the bytes were
    revised. We count the appended generations from the raw bytes (pikepdf collapses the xref chain
    on a full re-parse, so the raw-byte markers — ``%%EOF`` / ``startxref`` / ``/Prev`` — are the
    faithful evidence).
  * **Creation-date vs modification-date skew & missing/forged dates** — a ModDate *earlier* than the
    CreationDate is physically impossible (forged metadata); a large skew, or metadata stripped
    entirely, is corroborating evidence.

These are combined into a single ``suspicion`` in [0, 1] (weighted, capped). None of the three is a
hard gate — each contributes graded evidence, in line with BUILD-MANIFEST's "weighted evidence, not a
binary blocklist; FP-test against legitimate print-to-PDF" guard.

Honest bound: structure/metadata forensics is corroborating, not dispositive — a careful forger can
strip metadata or author with a benign producer. A clean structure is therefore low suspicion, never
zero-proof of authenticity; the primary in-document signal remains the arithmetic engine, and origin
is answered by Tier-1 provenance. Unparsable PDF -> ERROR (fail-closed). Non-PDF -> NOT_EVALUATED.

Deterministic, no partner, no network. pikepdf (qpdf) parses defensively; we never render or execute.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import pikepdf

from app.config import settings
from app.contracts import AnalysisContext, LayerSignal, Mode

# --- evidence-weighting constants (CLAUDE.md §5: named, with provenance) --------------------
# These are the *internal* sub-weights that compose the single suspicion in [0, 1]; the analyzer's
# contribution to the verdict is the separate, config-driven ``settings.weight_metadata_structure``.
# DEFAULT — needs calibration on a real statement corpus (no labelled corpus available yet).

# Producer/Creator fingerprint of a deny-listed editing tool on a purported statement.
SUSPICION_EDITING_TOOL: float = 0.55
# Each appended incremental-update generation beyond the original save (shadow-attack indicator).
SUSPICION_PER_INCREMENTAL_UPDATE: float = 0.40
# ModDate strictly earlier than CreationDate — physically impossible -> forged metadata.
SUSPICION_IMPOSSIBLE_DATE_ORDER: float = 0.60
# Large legitimate-direction create->mod skew (document edited long after creation).
SUSPICION_LARGE_DATE_SKEW: float = 0.20
# Both Producer and Creator absent on a document that should carry them.
SUSPICION_MISSING_METADATA: float = 0.15

# A create->mod gap beyond this many days is treated as a "large skew" signal. DEFAULT.
LARGE_DATE_SKEW_DAYS: float = 30.0

# Deny list: substrings (lower-cased) of Producer/Creator that fingerprint an *editing/authoring*
# tool. Matched as case-insensitive substrings of the metadata string. Weighted evidence, not a
# hard block — see the allow list below which suppresses legitimate print-to-PDF drivers.
EDITING_TOOL_FINGERPRINTS: tuple[str, ...] = (
    "photoshop",
    "adobe photoshop",
    "gimp",
    "canva",
    "inkscape",
    "coreldraw",
    "affinity",
    "pixelmator",
    "figma",
    "illustrator",
    "microsoft word",
    "microsoft® word",
    "libreoffice",
    "openoffice",
    "wps office",
    "pages",  # Apple Pages authoring app
    "google docs",
)

# Allow list: legitimate print-to-PDF / OS / bank-core / library producers that must NOT be flagged
# even though some overlap with generic renderers. RESEARCH-001: print-to-PDF false positives are the
# documented failure mode of a naive producer blocklist. A producer matching an allow-list entry
# suppresses the editing-tool signal entirely (the allow list wins over the deny list on conflict).
LEGITIMATE_PRODUCER_FINGERPRINTS: tuple[str, ...] = (
    "microsoft: print to pdf",
    "microsoft print to pdf",
    "quartz pdfcontext",  # macOS print-to-PDF
    "mac os x",
    "cairo",
    "ghostscript",
    "gpl ghostscript",
    "cups",
    "pdfkit",
    "itext",  # widely used by bank statement generators
    "itextsharp",
    "jasperreports",  # common bank/enterprise report engine
    "oracle bi publisher",
    "crystal reports",
    "fpdf",
    "reportlab",  # common server-side statement generator
    "tcpdf",
    "dompdf",
    "wkhtmltopdf",
    "prince",
    "pdf-xchange",
    "acrobat distiller",
    "skia/pdf",  # Chromium "Print to PDF" backend — a legitimate print path
    "chromium",
    "pikepdf",
    "qpdf",
)

# Producers/Creators that are generic *Skia/canvas* renderers WITHOUT the explicit print-to-PDF
# context. "Skia/PDF" appears in the allow list (legit Chromium print path); but a bare canvas
# producer with no print context is mild evidence. We keep this conservative to avoid FPs.

BBox = tuple[float, float, float, float]


@dataclass
class StructureFindings:
    """Structured result of the metadata/structure analysis — typed, auditable, side-effect-free."""

    producer: Optional[str] = None
    creator: Optional[str] = None
    editing_tool_hits: list[str] = field(default_factory=list)
    legitimate_producer: bool = False
    incremental_updates: int = 0  # appended generations beyond the original save
    has_prev_xref: bool = False
    creation_date: Optional[datetime] = None
    mod_date: Optional[datetime] = None
    impossible_date_order: bool = False
    large_date_skew_days: Optional[float] = None
    missing_metadata: bool = False
    reasons: list[str] = field(default_factory=list)


_PDF_DATE_RE = re.compile(r"D?:?\s*(\d{4})(\d{2})(\d{2})(\d{2})?(\d{2})?(\d{2})?")


def parse_pdf_date(value: Any) -> Optional[datetime]:
    """Parse a PDF date string (``D:YYYYMMDDHHmmSS+OH'mm'``) to a UTC datetime.

    We normalise to UTC ignoring the offset for *ordering* purposes (we compare create vs mod from
    the same document, so a consistent reference is what matters). Returns ``None`` for absent or
    unparseable values — never raises.
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    m = _PDF_DATE_RE.match(s)
    if not m:
        return None
    year, month, day, hour, minute, second = (int(g) if g else 0 for g in m.groups())
    try:
        return datetime(
            year,
            month or 1,
            day or 1,
            hour,
            minute,
            second,
            tzinfo=timezone.utc,
        )
    except ValueError:
        return None


def _match_fingerprints(text: Optional[str], fingerprints: tuple[str, ...]) -> list[str]:
    if not text:
        return []
    low = text.lower()
    return [fp for fp in fingerprints if fp in low]


def count_incremental_updates(raw: bytes) -> int:
    """Count appended cross-reference generations beyond the original save (the shadow-attack count).

    A genuine single-save PDF has exactly one body terminated by one ``%%EOF`` and one ``startxref``.
    Each incremental update appends a new body section, a new xref section, a new ``startxref`` and a
    new ``%%EOF``, with the new trailer's ``/Prev`` pointing back at the previous xref offset. We
    count the *additional* end-of-file markers, corroborated by ``/Prev`` chaining.

    Reading the raw bytes (rather than the parsed xref) is deliberate: pikepdf/qpdf collapse the xref
    chain when it re-serialises, so the parsed object would *hide* the incremental history — exactly
    the evidence we need to preserve. We therefore measure it on the untouched intake bytes.
    """
    # Count physical %%EOF markers (tolerant of trailing whitespace / missing final newline).
    eof_markers = len(re.findall(rb"%%EOF", raw))
    startxref_markers = len(re.findall(rb"\bstartxref\b", raw))
    # Generations beyond the first. Use the larger of the two structural counts but never below 0.
    generations = max(eof_markers, startxref_markers)
    return max(0, generations - 1)


def analyze_structure(raw: bytes) -> StructureFindings:
    """Pure analysis: parse PDF structure/metadata and assemble typed findings. May raise on a
    fundamentally unparsable PDF (caller converts that to a fail-closed ERROR)."""
    findings = StructureFindings()

    # 1) Incremental-update / xref-generation count — from the RAW intake bytes (see docstring).
    findings.incremental_updates = count_incremental_updates(raw)
    findings.has_prev_xref = b"/Prev" in raw
    if findings.incremental_updates > 0:
        findings.reasons.append(
            f"{findings.incremental_updates} incremental update(s) appended after the original save "
            "(post-edit / shadow-attack indicator)"
        )

    # 2) Open with pikepdf (qpdf) — defensive parse, no render, no JS, no network.
    with pikepdf.Pdf.open(io.BytesIO(raw)) as pdf:
        docinfo = pdf.docinfo
        producer = docinfo.get(pikepdf.Name.Producer)
        creator = docinfo.get(pikepdf.Name.Creator)
        findings.producer = str(producer) if producer is not None else None
        findings.creator = str(creator) if creator is not None else None

        create_raw = docinfo.get(pikepdf.Name.CreationDate)
        mod_raw = docinfo.get(pikepdf.Name.ModDate)
        findings.creation_date = parse_pdf_date(create_raw)
        findings.mod_date = parse_pdf_date(mod_raw)

    # 3) Producer/Creator fingerprinting — deny list, suppressed by the print-to-PDF allow list.
    combined = " | ".join(p for p in (findings.producer, findings.creator) if p)
    legit_hits = _match_fingerprints(combined, LEGITIMATE_PRODUCER_FINGERPRINTS)
    findings.legitimate_producer = bool(legit_hits)
    editing_hits = _match_fingerprints(combined, EDITING_TOOL_FINGERPRINTS)
    if findings.legitimate_producer:
        # Allow list wins: a recognised print-to-PDF / bank-core producer is NOT an editing tool,
        # even if a substring incidentally overlaps. This is the documented FP guard.
        findings.editing_tool_hits = []
        findings.reasons.append(
            f"producer recognised as legitimate print-to-PDF / generator ({', '.join(legit_hits)})"
        )
    else:
        findings.editing_tool_hits = editing_hits
        if editing_hits:
            findings.reasons.append(
                f"editing/authoring tool fingerprint in metadata: {', '.join(editing_hits)}"
            )

    # 4) Missing metadata — both Producer and Creator absent (stripped / never written).
    if not findings.producer and not findings.creator:
        findings.missing_metadata = True
        findings.reasons.append("no Producer/Creator metadata present (stripped or absent)")

    # 5) Date skew / impossible ordering.
    if findings.creation_date and findings.mod_date:
        delta_days = (findings.mod_date - findings.creation_date).total_seconds() / 86400.0
        if delta_days < 0:
            findings.impossible_date_order = True
            findings.reasons.append(
                "ModDate is earlier than CreationDate — physically impossible (forged metadata)"
            )
        elif delta_days > LARGE_DATE_SKEW_DAYS:
            findings.large_date_skew_days = delta_days
            findings.reasons.append(
                f"large create->modify skew of {delta_days:.1f} days (edited well after creation)"
            )

    return findings


def suspicion_from_findings(findings: StructureFindings) -> float:
    """Combine the structural sub-signals into a single suspicion in [0, 1] (monotone, additive,
    capped). Each component is graded evidence, none is a hard gate."""
    suspicion = 0.0

    if findings.editing_tool_hits:
        suspicion += SUSPICION_EDITING_TOOL

    if findings.incremental_updates > 0:
        # First appended generation is the strong signal; further ones add diminishing weight.
        suspicion += SUSPICION_PER_INCREMENTAL_UPDATE
        suspicion += 0.10 * (findings.incremental_updates - 1)

    if findings.impossible_date_order:
        suspicion += SUSPICION_IMPOSSIBLE_DATE_ORDER
    elif findings.large_date_skew_days is not None:
        suspicion += SUSPICION_LARGE_DATE_SKEW

    if findings.missing_metadata:
        suspicion += SUSPICION_MISSING_METADATA

    return float(min(1.0, suspicion))


class PdfStructureAnalyzer:
    """Tier-2 (layer 3) FILE-mode analyzer: PDF document-structure / metadata forensics.

    Reads the raw intake bytes from ``ctx.file_bytes``. Non-PDF intake -> NOT_EVALUATED (no signal in
    this medium). Unparsable PDF -> ERROR (fail-closed). Otherwise emits a VALID graded suspicion.
    """

    name = "pdf_structure_metadata"
    layer = 3
    mode = Mode.FILE
    order = 30

    def applicable(self, ctx: AnalysisContext) -> bool:
        return ctx.intake_mode == Mode.FILE and bool(ctx.file_bytes)

    def _looks_like_pdf(self, ctx: AnalysisContext) -> bool:
        raw = ctx.file_bytes or b""
        # Trust the magic header over the (client-supplied, spoofable) MIME/extension.
        if raw[:5] == b"%PDF-":
            return True
        # Some valid PDFs have leading junk before %PDF- (tolerated by qpdf); accept if the header
        # appears within the first 1 KiB, mirroring qpdf's own leniency.
        return b"%PDF-" in raw[:1024]

    def analyze(self, ctx: AnalysisContext) -> LayerSignal:
        raw = ctx.file_bytes
        if not raw:
            return LayerSignal.not_evaluated(
                self.name, self.layer, self.mode, "no file bytes to analyse"
            )
        if not self._looks_like_pdf(ctx):
            return LayerSignal.not_evaluated(
                self.name,
                self.layer,
                self.mode,
                "intake is not a PDF — structure/metadata forensics do not apply to this medium",
                mime=ctx.file_mime,
            )

        try:
            findings = analyze_structure(raw)
        except pikepdf.PdfError as exc:  # genuinely unparsable PDF -> fail-closed
            return LayerSignal.error(
                self.name, self.layer, self.mode, f"unparsable PDF: {exc}"
            )
        except (ValueError, RuntimeError) as exc:  # defensive: any structural decode failure
            return LayerSignal.error(
                self.name, self.layer, self.mode, f"PDF structure decode failed: {exc}"
            )

        suspicion = suspicion_from_findings(findings)

        measurements: dict[str, Any] = {
            "producer": findings.producer,
            "creator": findings.creator,
            "editing_tool_hits": findings.editing_tool_hits,
            "legitimate_producer": findings.legitimate_producer,
            "incremental_updates": findings.incremental_updates,
            "has_prev_xref": findings.has_prev_xref,
            "impossible_date_order": findings.impossible_date_order,
            "large_date_skew_days": findings.large_date_skew_days,
            "missing_metadata": findings.missing_metadata,
            "creation_date": findings.creation_date.isoformat() if findings.creation_date else None,
            "mod_date": findings.mod_date.isoformat() if findings.mod_date else None,
            "honest_bound": (
                "structure/metadata forensics is corroborating evidence, not dispositive: a careful "
                "forger can strip metadata or author with a benign producer; clean structure is low "
                "suspicion, not proof of authenticity"
            ),
        }

        # Publish findings for downstream reuse (e.g. the signature analyzer correlates an
        # incremental update with a post-signing edit / shadow attack).
        ctx.shared["pdf_structure"] = findings

        if suspicion == 0.0:
            reason = "no structural/metadata anomalies (single save, neutral producer, coherent dates)"
        else:
            reason = "; ".join(findings.reasons) or "structural/metadata anomalies detected"

        return LayerSignal.valid(
            self.name,
            self.layer,
            self.mode,
            suspicion,
            settings.weight_metadata_structure,
            reason,
            measurements=measurements,
        )
