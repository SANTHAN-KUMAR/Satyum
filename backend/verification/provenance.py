"""Tier-1 support: the issuer source-capability registry and the "PDF-only" red-flag (ADR-002 D3).

If a verifiable source existed for a document (the issuer is AA-enabled / signs its statements /
is DigiLocker-issuable) but the applicant submitted only an *unsigned* PDF, that avoidance is itself
a risk signal — mirroring how lenders treat a missing sourceable record.

The real signature verification (PAdES/C2PA) is implemented separately (verification/signature.py,
built in the analyzer workflow); this module holds the deterministic capability map + red-flag rule,
which need no heavy deps and are unit-tested directly.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import settings
from app.contracts import AnalysisContext, LayerSignal, Mode


@dataclass(frozen=True)
class IssuerCapability:
    issuer: str
    aa_enabled: bool          # reachable via RBI Account Aggregator
    signs_statements: bool    # issues CCA-signed e-statements
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


def issuer_is_sourceable(issuer_key: str | None) -> bool:
    if not issuer_key:
        return False
    cap = SOURCE_CAPABILITY.get(issuer_key.strip().lower())
    return bool(cap and (cap.aa_enabled or cap.signs_statements or cap.digilocker_issuable))


class PdfOnlyRedFlagAnalyzer:
    """Raises a risk flag when a sourceable issuer's document arrived as an unsigned upload.

    Runs after the signature analyzer (which sets ``ctx.shared['provenance_verified']``); registered
    after it so the orchestrator's insertion order guarantees ordering.
    """

    name = "pdf_only_red_flag"
    layer = 1
    mode = Mode.FILE
    order = 20  # after signature (order 10)

    def applicable(self, ctx: AnalysisContext) -> bool:
        return ctx.intake_mode == Mode.FILE

    def analyze(self, ctx: AnalysisContext) -> LayerSignal:
        if not ctx.source_was_pullable:
            return LayerSignal.not_evaluated(
                self.name, self.layer, self.mode,
                "issuer not known to be source-verifiable — no basis for the red flag",
            )
        if ctx.shared.get("provenance_verified"):
            # they DID provide a cryptographically verifiable document — no avoidance, no flag
            return LayerSignal.not_evaluated(
                self.name, self.layer, self.mode, "verifiable source provided (no avoidance)",
            )
        # sourceable issuer, but only an unsigned PDF was submitted -> avoidance signal
        return LayerSignal.valid(
            self.name, self.layer, self.mode,
            suspicion=settings.red_flag_pdf_only_suspicion,
            weight=settings.red_flag_pdf_only_weight,
            reason="sourceable issuer but unsigned PDF submitted — a verifiable pull was avoided",
            measurements={"red_flag": "pdf_only_when_pullable"},
        )
