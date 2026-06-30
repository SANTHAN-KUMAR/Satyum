"""Claimed-vs-document identity cross-check — catches a tampered/mismatched applicant PAN.

At onboarding the applicant TYPES their PAN. We can only check its *format* offline (real existence
needs the gated Protean API). The honest, real verification is to cross-check the **claimed** PAN
against the PAN **extracted from the uploaded document**: a genuine applicant's typed PAN matches the
PAN on their statement; a tampered claim does not. This is the single-document onboarding analogue of
the cross-document identity graph (ADR-003 #3), and it reuses that module's tested comparison (so an
OCR single-character slip is a REVIEW near-match, while a genuinely different PAN is a hard mismatch).

Only the structured identifier (PAN) is cross-checked here — names are noisy (transliteration), so they
are left to the bundle-level cross-document graph. Emits NOT_EVALUATED when there is nothing to compare
(no claim, or the document carried no extractable PAN) — never a fabricated pass.
"""

from __future__ import annotations

import re

from app.config import settings
from app.contracts import AnalysisContext, LayerSignal, Mode
from forensics.cross_document import AGREE, NEAR, compare_entities
from forensics.entities import ExtractedEntities

_PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")


class ClaimedIdentityAnalyzer:
    name = "claimed_identity"
    layer = 3
    mode = Mode.FILE
    order = 46  # after entity_extraction (order 45) so ctx.shared['entities'] exists

    def applicable(self, ctx: AnalysisContext) -> bool:
        return ctx.intake_mode == Mode.FILE and bool(ctx.claimed_identity.get("pan"))

    def analyze(self, ctx: AnalysisContext) -> LayerSignal:
        claimed_pan = (ctx.claimed_identity.get("pan") or "").strip().upper()
        if not _PAN_RE.match(claimed_pan):
            # A malformed claimed PAN is a Step-1 client concern, not a document tamper signal here.
            return LayerSignal.not_evaluated(
                self.name, self.layer, self.mode, "claimed PAN is not well-formed — nothing to cross-check",
            )

        extracted = ctx.shared.get("entities")
        if not isinstance(extracted, ExtractedEntities) or not extracted.pan:
            return LayerSignal.not_evaluated(
                self.name, self.layer, self.mode,
                "no PAN could be read from the document — cannot cross-check the claimed PAN",
            )

        result = compare_entities({
            "you entered": ExtractedEntities(pan=claimed_pan),
            "your document": extracted,
        })
        pan_cmp = next((c for c in result.comparisons if c.field == "pan"), None)
        if pan_cmp is None:
            return LayerSignal.not_evaluated(
                self.name, self.layer, self.mode, "no comparable PAN in both the claim and the document",
            )

        measurements = {
            "claimed_pan_matches_document": pan_cmp.status == AGREE,
            "comparison_status": pan_cmp.status,
        }
        if pan_cmp.status == AGREE:
            return LayerSignal.valid(
                self.name, self.layer, self.mode, suspicion=0.0,
                weight=settings.weight_claimed_identity,
                reason="the PAN you entered matches the PAN on your document",
                measurements=measurements,
            )
        if pan_cmp.status == NEAR:
            return LayerSignal.valid(
                self.name, self.layer, self.mode, suspicion=pan_cmp.severity,
                weight=settings.weight_claimed_identity,
                reason="the entered PAN differs from the document by one character — possible OCR slip; manual review",
                measurements=measurements,
            )
        # DISAGREE — a genuinely different PAN: the claim does not match the document.
        return LayerSignal.valid(
            self.name, self.layer, self.mode, suspicion=pan_cmp.severity,
            weight=settings.weight_claimed_identity,
            reason="the PAN you entered does NOT match the PAN on your document — identity mismatch",
            measurements=measurements,
        )
