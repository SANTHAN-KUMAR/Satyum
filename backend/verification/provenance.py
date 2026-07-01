"""Tier-1 support: the issuer source-capability registry and the "PDF-only" red-flag (ADR-002 D3).

If a verifiable source existed for a document (the issuer is AA-enabled / signs its statements /
is DigiLocker-issuable) but the applicant submitted only an *unsigned* PDF, that avoidance is itself
a risk signal — mirroring how lenders treat a missing sourceable record.

The real signature verification (PAdES/C2PA) lives in ``verification/signature.py``. This module holds
the deterministic capability map + the red-flag rule. The issuer that drives the flag is derived **from
the document itself** (PDF metadata + page-1 text), NOT from a client-supplied hint — an attacker who
simply omits the hint must not be able to disable the flag (ADR-004 Layer-1 hardening). The client hint
survives only as a soft fallback for media with no readable text layer (e.g. an image statement).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from app.config import settings
from app.contracts import AnalysisContext, LayerSignal, Mode

logger = logging.getLogger(__name__)

# v2 provenance result contract (ADR-004 Layer 1): the avoidance state surfaced to the decision brain.
PROV_RESULT_SOURCE_AVOIDED = "SOURCE_AVOIDED"

# How many characters of page-1 text to scan for an issuer name (the masthead/header is at the top).
_TEXT_SCAN_LIMIT = 4000


@dataclass(frozen=True)
class IssuerCapability:
    issuer: str
    aa_enabled: bool  # reachable via RBI Account Aggregator
    signs_statements: bool  # issues CCA-signed e-statements
    digilocker_issuable: bool


# Seed registry of common Indian issuers and whether a verifiable source exists. This is a real
# knowledge map (expandable), not a mock — it drives the red-flag decision. Keys are normalised,
# lower-cased issuer identifiers.
SOURCE_CAPABILITY: dict[str, IssuerCapability] = {
    "sbi": IssuerCapability("State Bank of India", True, True, True),
    "hdfc": IssuerCapability("HDFC Bank", True, True, True),
    "icici": IssuerCapability("ICICI Bank", True, True, True),
    "axis": IssuerCapability("Axis Bank", True, True, True),
    "canara": IssuerCapability("Canara Bank", True, True, True),
    "pnb": IssuerCapability("Punjab National Bank", True, True, True),
    "kotak": IssuerCapability("Kotak Mahindra Bank", True, True, True),
}

# Multi-word issuer patterns (lowercased) -> capability key. Checked as substrings first because they
# are specific; the short keys above are then checked only as WHOLE words to avoid false positives
# (e.g. "axis" inside another token). Calibrated against the registry, expandable per corpus.
_ISSUER_PATTERNS: dict[str, str] = {
    "state bank of india": "sbi",
    "hdfc bank": "hdfc",
    "icici bank": "icici",
    "axis bank": "axis",
    "canara bank": "canara",
    "punjab national bank": "pnb",
    "kotak mahindra": "kotak",
}


def issuer_is_sourceable(issuer_key: str | None) -> bool:
    if not issuer_key:
        return False
    cap = SOURCE_CAPABILITY.get(issuer_key.strip().lower())
    return bool(cap and (cap.aa_enabled or cap.signs_statements or cap.digilocker_issuable))


def detect_issuer(text: str) -> str | None:
    """Return the capability key of the MOST PROMINENT issuer in ``text`` (the masthead), or ``None``.

    Prominence is by position: the issuing bank's name sits in the header at the *top* of the document,
    whereas an incidental competitor name ("UPI / HDFC BANK / …") appears far down in a transaction row.
    We therefore return the issuer whose name appears EARLIEST, not whichever registry key we happen to
    check first — otherwise a genuine Canara statement carrying an HDFC UPI line is mislabelled HDFC
    (KNOWN_ISSUES #5.3). Specific multi-word names win ties over short whole-word keys. Pure string
    logic — deterministic and directly unit-tested.
    """
    t = re.sub(r"\s+", " ", text.lower())
    best_key: str | None = None
    best_pos = len(t) + 1
    best_specific = False  # a multi-word masthead name is more trustworthy than a bare short key
    # Specific multi-word names first (e.g. "canara bank").
    for pattern, key in _ISSUER_PATTERNS.items():
        pos = t.find(pattern)
        if pos == -1:
            continue
        if pos < best_pos or (pos == best_pos and not best_specific):
            best_key, best_pos, best_specific = key, pos, True
    # Short keys matched only as whole words (e.g. "axis") — never break a tie away from a specific name.
    for key in SOURCE_CAPABILITY:
        m = re.search(rf"\b{re.escape(key)}\b", t)
        if m and m.start() < best_pos:
            best_key, best_pos, best_specific = key, m.start(), False
    return best_key


def _is_pdf(data: bytes) -> bool:
    head = data[:1024].lstrip(b"\x00\r\n\t ")
    return head.startswith(b"%PDF-")


def extract_issuer_from_document(
    file_bytes: bytes | None, password: str | None = None
) -> tuple[str | None, str]:
    """Derive the issuing institution from the PDF itself (metadata + page-1 text).

    Returns ``(issuer_key | None, evidence)``. Defensive: a missing/garbled/non-PDF input yields
    ``(None, reason)`` and never raises — the red flag then has no document basis (and may fall back
    to an upstream capability hint). This replaces trusting a client-supplied issuer field, which a
    forger could simply omit to dodge the flag. ``password`` decrypts an encrypted PDF in memory.
    """
    if not file_bytes:
        return None, "no file bytes"
    if not _is_pdf(file_bytes):
        return None, "not a pdf (no text layer to derive issuer from)"
    try:
        import pymupdf  # PyMuPDF; lazy import so a missing dep degrades, never crashes the pipeline
    except ImportError:
        return None, "pdf text extraction unavailable (pymupdf missing)"
    try:
        doc = pymupdf.open(stream=file_bytes, filetype="pdf")
        if doc.needs_pass and password:  # encrypted govt/bank PDF: decrypt in memory (CLAUDE.md §10)
            doc.authenticate(password)
    except Exception as exc:  # noqa: BLE001 — a malformed PDF yields no issuer, never raises
        logger.info("issuer extraction: unparsable pdf: %r", exc)
        return None, "unparsable pdf"
    try:
        meta_values = [str(v) for v in (doc.metadata or {}).values() if v]
        page_text = doc.load_page(0).get_text("text")[:_TEXT_SCAN_LIMIT] if doc.page_count else ""
    except Exception as exc:  # noqa: BLE001 — extraction failure -> no issuer, never a crash
        logger.info("issuer extraction: text/metadata read failed: %r", exc)
        meta_values, page_text = [], ""
    finally:
        doc.close()

    key = detect_issuer(" ".join(meta_values) + "\n" + page_text)
    if key is None:
        return None, "no recognized issuer in metadata or page-1 text"
    return key, "document"


class PdfOnlyRedFlagAnalyzer:
    """Raises a risk flag when a sourceable issuer's document arrived as an unsigned upload.

    The issuer is derived from the document (``extract_issuer_from_document``); the client capability
    hint (``ctx.source_was_pullable``) is only a fallback for media with no readable text layer. Runs
    after the signature analyzer (which sets ``ctx.shared['provenance_verified']``); registered after
    it so the orchestrator's insertion order guarantees ordering.
    """

    name = "pdf_only_red_flag"
    layer = 1
    mode = Mode.FILE
    order = 20  # after signature (order 10)

    def applicable(self, ctx: AnalysisContext) -> bool:
        return ctx.intake_mode == Mode.FILE

    def analyze(self, ctx: AnalysisContext) -> LayerSignal:
        # Derive the issuer FROM THE DOCUMENT first; never let a (possibly absent) client hint be the
        # trigger. The hint may only ADD coverage when the document yields nothing.
        issuer_key, evidence = extract_issuer_from_document(ctx.file_bytes, ctx.pdf_password)
        if issuer_key is not None:
            sourceable = issuer_is_sourceable(issuer_key)
        else:
            sourceable = ctx.source_was_pullable
            evidence = "issuer-capability hint" if sourceable else evidence

        if not sourceable:
            return LayerSignal.not_evaluated(
                self.name,
                self.layer,
                self.mode,
                "no source-verifiable issuer recognised in the document — no basis for the red flag",
            )
        if ctx.shared.get("provenance_verified"):
            # They DID provide a cryptographically verifiable document — no avoidance, no flag.
            return LayerSignal.not_evaluated(
                self.name,
                self.layer,
                self.mode,
                "verifiable source provided (no avoidance)",
            )

        issuer_label = (
            SOURCE_CAPABILITY[issuer_key].issuer if issuer_key in SOURCE_CAPABILITY else "the issuer"
        )
        return LayerSignal.valid(
            self.name,
            self.layer,
            self.mode,
            suspicion=settings.red_flag_pdf_only_suspicion,
            weight=settings.red_flag_pdf_only_weight,
            reason=(
                f"{issuer_label} is source-verifiable but only an unsigned PDF was submitted — "
                "a verifiable pull/signature was avoided"
            ),
            measurements={
                "red_flag": "pdf_only_when_pullable",
                "issuer": issuer_key,
                "issuer_evidence": evidence,
                "provenance_result": PROV_RESULT_SOURCE_AVOIDED,
            },
        )
