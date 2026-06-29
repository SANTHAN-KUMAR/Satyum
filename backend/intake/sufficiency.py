"""Deterministic document-type classification + evidence-sufficiency assessment (ADR-004 §Layer-0).

A header/keyword classifier over the PDF text layer assigns a document-type family without the VLM, so
the pipeline knows what it is holding (and what rule pack will apply) even with no model configured. The
sufficiency assessment then states, honestly, the strongest verdict the available evidence can support —
single unsigned document vs. a verifiable source — which the Layer-7 decision brain uses to refuse to
auto-approve on insufficient evidence (the cardinal fail-closed rule, CLAUDE.md §4).

Pure/deterministic and defensive: an unreadable or text-less (scanned) PDF degrades to ``UNKNOWN`` /
``scanned`` and a low achievable confidence — never a guessed classification.
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass

from app.contracts import AnalysisContext, LayerSignal, Mode
from forensics.ocr import is_pdf

logger = logging.getLogger(__name__)

# Document-type families. The financial families match the Layer-4 rule-pack doc types exactly; land/
# legal are recognised here for routing even though their packs are scoped (ADR-004 §Layer-4).
DOC_TYPES = (
    "BANK_STATEMENT", "SALARY_SLIP", "FORM16", "ITR",
    "AADHAAR", "PAN_CARD",
    "LAND_DEED", "LEGAL_CONTRACT", "UNKNOWN",
)

# Document families whose forensic profile differs from financial statements.
# Analyzers calibrated for bank-statement typography / transaction tables skip these.
IDENTITY_DOC_TYPES: frozenset[str] = frozenset({"AADHAAR", "PAN_CARD"})
FINANCIAL_DOC_TYPES: frozenset[str] = frozenset({"BANK_STATEMENT", "SALARY_SLIP", "FORM16", "ITR"})

# Header/keyword fingerprints per family (lower-cased substrings). A document is classified by the family
# with the most distinct keyword hits; ties and zero-hits fall through to UNKNOWN. Calibrated against
# common Indian document mastheads; expandable per corpus (CLAUDE.md §5 — provenance, not magic).
_KEYWORDS: dict[str, tuple[str, ...]] = {
    "BANK_STATEMENT": (
        "statement of account",
        "account statement",
        "closing balance",
        "opening balance",
        "ifsc",
        "value date",
        "withdrawal",
        "deposit",
    ),
    "SALARY_SLIP": (
        "salary slip",
        "pay slip",
        "payslip",
        "net pay",
        "gross earnings",
        "total deductions",
        "earnings",
        "basic pay",
    ),
    "FORM16": (
        "form 16",
        "form no. 16",
        "tds certificate",
        "certificate under section 203",
        "deducted at source",
        "part a",
        "part b",
    ),
    "ITR": (
        "income tax return",
        "itr-v",
        "acknowledgement number",
        "assessment year",
        "gross total income",
        "return of income",
    ),
    "LAND_DEED": (
        "sale deed",
        "conveyance deed",
        "sub-registrar",
        "survey number",
        "khata",
        "khasra",
        "registered",
        "consideration amount",
    ),
    "LEGAL_CONTRACT": (
        "this agreement",
        "this deed",
        "party of the first part",
        "witnesseth",
        "in witness whereof",
        "terms and conditions",
        "hereinafter",
    ),
    "AADHAAR": (
        "unique identification authority of india",
        "uidai",
        "aadhaar",
        "आधार",
        "enrolment no",
        "vid",              # Virtual ID field on the back
        "dob:",             # DOB label common in Aadhaar layout
        "government of india",  # appears on Aadhaar header
    ),
    "PAN_CARD": (
        "permanent account number",
        "income tax department",
        "income-tax department",
        "govt. of india",
    ),
}

# A PDF carrying at least this many characters of extractable text is treated as digital-native
# (machine-readable); below it the file is effectively a scan/image needing OCR/VLM to read.
_DIGITAL_TEXT_MIN_CHARS = 200


@dataclass(frozen=True)
class EvidenceSufficiency:
    """What kind of document this is and the strongest verdict the available evidence can support."""

    doc_type: str
    quality: str  # "digital_native" | "scanned" | "image" | "unknown"
    evidence_level: str  # "single-document" | "case-context" | "corroborated"
    achievable_confidence: str  # "high" | "moderate" | "low"
    sufficient_for_auto_approve: bool


def classify_doc_type(text: str) -> str:
    """Return the best-matching document-type family for ``text``, or ``UNKNOWN``.

    Scores each family by the number of distinct keyword hits and picks the unique maximum; no hits, or
    a tie for the top, yields ``UNKNOWN`` (never a coin-flip guess).
    """
    norm = re.sub(r"\s+", " ", text.lower())
    scores = {family: sum(1 for kw in kws if kw in norm) for family, kws in _KEYWORDS.items()}
    best = max(scores.values(), default=0)
    if best == 0:
        return "UNKNOWN"
    winners = [family for family, n in scores.items() if n == best]
    return winners[0] if len(winners) == 1 else "UNKNOWN"


def _pdf_text(file_bytes: bytes) -> str:
    """Extract the embedded text of the first two pages of a PDF (header is enough to classify)."""
    try:
        import pymupdf
    except ImportError:
        return ""
    try:
        doc = pymupdf.open(stream=file_bytes, filetype="pdf")
    except Exception as exc:  # noqa: BLE001 — an unparsable PDF yields no text, never raises
        logger.info("sufficiency: unparsable pdf: %r", exc)
        return ""
    try:
        return "\n".join(doc.load_page(i).get_text("text") for i in range(min(2, doc.page_count)))
    except Exception as exc:  # noqa: BLE001
        logger.info("sufficiency: pdf text read failed: %r", exc)
        return ""
    finally:
        doc.close()


def assess(ctx: AnalysisContext) -> EvidenceSufficiency:
    """Classify the document and assess what confidence is achievable from the available evidence."""
    file_bytes = ctx.file_bytes or b""
    if is_pdf(file_bytes):
        text = _pdf_text(file_bytes)
        quality = "digital_native" if len(text.strip()) >= _DIGITAL_TEXT_MIN_CHARS else "scanned"
    elif file_bytes:
        text, quality = "", "image"
    else:
        text, quality = "", "unknown"

    # A client-declared doc_type is a hint only; the deterministic classification is authoritative for
    # what we can SEE. Prefer the text classification; fall back to the client hint, then UNKNOWN.
    doc_type = classify_doc_type(text)
    if doc_type == "UNKNOWN" and ctx.doc_type:
        doc_type = ctx.doc_type.upper()

    # This analyzer sees ONE document; bundle-level corroboration is assessed on the bundle path (Layer
    # 6). So the honest evidence level here is single-document.
    evidence_level = "single-document"

    # A verifiable source existing (sourceable issuer) is the only thing that makes a strong, auto-
    # approvable verdict achievable on a single document; otherwise the content is at best assessable
    # (moderate) or unreadable here (low). "sufficient_for_auto_approve" is the honest input to the
    # Layer-7 gate: a lone unsigned, un-pullable document is never, by itself, enough to auto-approve.
    if ctx.source_was_pullable:
        achievable, sufficient = "high", True
    elif doc_type != "UNKNOWN" and quality == "digital_native":
        achievable, sufficient = "moderate", False
    else:
        achievable, sufficient = "low", False

    return EvidenceSufficiency(
        doc_type=doc_type,
        quality=quality,
        evidence_level=evidence_level,
        achievable_confidence=achievable,
        sufficient_for_auto_approve=sufficient,
    )


class IntakeSufficiencyAnalyzer:
    """Layer 0: classify the document + publish the evidence-sufficiency assessment for the brain."""

    name = "intake_sufficiency"
    layer = 1  # intake tier — runs first in the waterfall
    mode = Mode.FILE
    order = 1

    def applicable(self, ctx: AnalysisContext) -> bool:
        return ctx.intake_mode == Mode.FILE and ctx.file_bytes is not None

    def analyze(self, ctx: AnalysisContext) -> LayerSignal:
        try:
            suff = assess(ctx)
        except Exception as exc:  # noqa: BLE001 — assessment must never crash the waterfall
            return LayerSignal.error(
                self.name, self.layer, self.mode, f"sufficiency assessment failed: {exc}"
            )

        # Publish for downstream layers (the rule packs may use doc_type; the brain uses sufficiency).
        ctx.shared["sufficiency"] = suff
        # Write the authoritative classification back to ctx.doc_type so every downstream
        # analyzer's applicable() can route on it (e.g. skip bank-statement forensics on AADHAAR).
        # The client hint (ctx.doc_type on entry) is overwritten only when the text-based
        # classification produced a non-UNKNOWN result; otherwise the client hint is preserved.
        if suff.doc_type != "UNKNOWN":
            ctx.doc_type = suff.doc_type

        # Intake classification is not a tamper judgment → NOT_EVALUATED, carrying the assessment for the
        # decision brain (read from this signal's measurements, like provenance is).
        return LayerSignal.not_evaluated(
            self.name,
            self.layer,
            self.mode,
            f"{suff.doc_type} ({suff.quality}); evidence: {suff.evidence_level}; "
            f"achievable confidence: {suff.achievable_confidence}",
            **asdict(suff),
        )
