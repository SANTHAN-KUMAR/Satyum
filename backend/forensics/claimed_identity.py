"""Claimed-vs-document identity cross-check — catches a tampered/mismatched applicant identity.

At onboarding the applicant TYPES their PAN (and, optionally, their name). The honest, real
verification is to cross-check the **claimed** identity against what the uploaded document actually
says: a genuine applicant's typed PAN matches the PAN on their statement; a tampered claim does not.
This is the single-document onboarding analogue of the cross-document identity graph (ADR-003 #3), and
it reuses that module's tested comparison (so an OCR single-character slip on the PAN is a REVIEW
near-match, while a genuinely different PAN is a hard mismatch).

PAN is the authoritative, hard-severity signal when both sides have one. Name is a SOFT fallback —
never a hard reject on its own (names are noisy: transliteration, initials, missing middle names) —
but it is not skippable. A document that carries no PAN at all (a land deed, an encumbrance
certificate, most non-financial instruments) previously gated this whole analyzer to NOT_EVALUATED
with no identity check performed whatsoever, even when the applicant's claimed name and the document's
own party name were completely different people — a real, confirmed identity-verification bypass. Name
comparison closes that gap: still soft (REVIEW-only severity, per forensics/cross_document.py's
surname-anchored fuzzy match), but never silently absent when it's the only signal available.

Emits NOT_EVALUATED only when there is truly nothing to compare on EITHER identifier — no claim at all,
or the document carried no extractable PAN *or* name — never a fabricated pass.
"""

from __future__ import annotations

import re

from app.config import settings
from app.contracts import AnalysisContext, LayerSignal, Mode
from forensics.cross_document import AGREE, NEAR, compare_entities
from forensics.entities import ExtractedEntities, normalise_name

_PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")


class ClaimedIdentityAnalyzer:
    name = "claimed_identity"
    layer = 3
    mode = Mode.FILE
    order = 46  # after entity_extraction (order 45) so ctx.shared['entities'] exists

    def applicable(self, ctx: AnalysisContext) -> bool:
        return ctx.intake_mode == Mode.FILE and bool(
            ctx.claimed_identity.get("pan") or ctx.claimed_identity.get("name")
        )

    def analyze(self, ctx: AnalysisContext) -> LayerSignal:
        claimed_pan_raw = (ctx.claimed_identity.get("pan") or "").strip().upper()
        # Same normalisation the document side already goes through (forensics/entities.py) — without
        # it, a claimed "Karnala Vamsi Krishna" would never equal an extracted "KARNALA VAMSI KRISHNA"
        # on case alone, a false disagreement that has nothing to do with actual identity.
        claimed_name = normalise_name(ctx.claimed_identity.get("name") or "") or ""
        claimed_pan = claimed_pan_raw if _PAN_RE.match(claimed_pan_raw) else ""
        # A malformed claimed PAN is a Step-1 client concern, not a document tamper signal here — but
        # don't let a typo'd PAN silently swallow a still-usable claimed name.
        if claimed_pan_raw and not claimed_pan and not claimed_name:
            return LayerSignal.not_evaluated(
                self.name, self.layer, self.mode, "claimed PAN is not well-formed — nothing to cross-check",
            )

        extracted = ctx.shared.get("entities")
        if not isinstance(extracted, ExtractedEntities) or not (extracted.pan or extracted.name):
            return LayerSignal.not_evaluated(
                self.name, self.layer, self.mode,
                "no PAN or name could be read from the document — cannot cross-check the claimed identity",
            )

        result = compare_entities({
            "you entered": ExtractedEntities(pan=claimed_pan or None, name=claimed_name or None),
            "your document": extracted,
        })
        pan_cmp = next((c for c in result.comparisons if c.field == "pan"), None)
        name_cmp = next((c for c in result.comparisons if c.field == "name"), None)
        if pan_cmp is None and name_cmp is None:
            return LayerSignal.not_evaluated(
                self.name, self.layer, self.mode,
                "no comparable PAN or name in both the claim and the document",
            )

        measurements = {
            "claimed_pan_matches_document": pan_cmp.status == AGREE if pan_cmp else None,
            "pan_comparison_status": pan_cmp.status if pan_cmp else None,
            "claimed_name_matches_document": name_cmp.status == AGREE if name_cmp else None,
            "name_comparison_status": name_cmp.status if name_cmp else None,
            # back-compat: the field this analyzer originally reported (PAN's own status, if checked)
            "comparison_status": pan_cmp.status if pan_cmp else (name_cmp.status if name_cmp else None),
        }

        # PAN is authoritative when both sides have one — its own severity/reason drives the signal,
        # exactly as before this change (name is not consulted; a PAN match is not undercut by a noisy
        # name mismatch, and a PAN mismatch is never softened by a name that happens to agree).
        if pan_cmp is not None:
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
                    reason="the entered PAN differs from the document by one character — "
                    "possible OCR slip; manual review",
                    measurements=measurements,
                )
            # DISAGREE — a genuinely different PAN: the claim does not match the document.
            return LayerSignal.valid(
                self.name, self.layer, self.mode, suspicion=pan_cmp.severity,
                weight=settings.weight_claimed_identity,
                reason="the PAN you entered does NOT match the PAN on your document — identity mismatch",
                measurements=measurements,
            )

        # No PAN on one or both sides (e.g. a land deed/encumbrance certificate) — name is the only
        # identity signal available. Soft by construction (compare_entities caps a name disagreement at
        # the REVIEW band; see forensics/cross_document.py::_compare_field) — flags a human review,
        # never an auto-reject, but is no longer silently skipped just because there was no PAN to check.
        assert name_cmp is not None  # guaranteed by the "both None" NOT_EVALUATED check above
        if name_cmp.status == AGREE:
            return LayerSignal.valid(
                self.name, self.layer, self.mode, suspicion=0.0,
                weight=settings.weight_claimed_identity,
                reason="no PAN on this document to cross-check, but the name you entered matches the "
                "document's — soft corroboration only",
                measurements=measurements,
            )
        return LayerSignal.valid(
            self.name, self.layer, self.mode, suspicion=name_cmp.severity,
            weight=settings.weight_claimed_identity,
            reason="no PAN on this document to cross-check, and the name you entered does NOT match "
            "the name on the document — possible identity mismatch (soft signal: names are noisy, "
            "manual review recommended)",
            measurements=measurements,
        )
