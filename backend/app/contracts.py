"""Frozen shared contracts for the Satyum verification pipeline.

Every analyzer (Tier 1 provenance, Tier 2 forensics, Tier 3 capture) conforms to the
``Analyzer`` protocol and returns exactly one :class:`LayerSignal`. The orchestrator composes
them; analyzers never call each other. The wire types (``LayerSignal``, ``TrustScore``) are
Pydantic models so they validate and serialise to the published API contract; the in-memory
``AnalysisContext`` is a plain dataclass because it carries binary / NumPy data.

See CLAUDE.md §1/§4 and architecture/ADR-002. This module is the keystone — change it deliberately.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field, model_validator


class Mode(StrEnum):
    """The intake/medium a signal physically belongs to.

    The mode-tagging invariant (CLAUDE.md §1): a ``FILE`` analyzer may never run on a ``CAMERA``
    frame and vice-versa; ``ANY`` is medium-agnostic (e.g. pHash on a rectified crop).
    """

    FILE = "FILE"
    CAMERA = "CAMERA"
    ANY = "ANY"


class SignalStatus(StrEnum):
    VALID = "VALID"  # measured; contributes to the score
    NOT_EVALUATED = "NOT_EVALUATED"  # precondition unmet / honestly gated -> excluded from score
    ERROR = "ERROR"  # detector failed -> fail-closed, pushes the verdict toward REVIEW


class Verdict(StrEnum):
    APPROVED = "APPROVED"
    REVIEW = "REVIEW"
    REJECTED = "REJECTED"


class EvidenceRegion(BaseModel):
    """A region a detector wants to highlight on the document, with provenance to the detector."""

    bbox: tuple[float, float, float, float]  # x, y, w, h (pixels in the analysed image space)
    label: str
    source: str  # the detector name that produced this region (auditability)


class LayerSignal(BaseModel):
    """The single typed output of every analyzer.

    ``suspicion`` is in [0, 1] where 0 = clean/genuine and 1 = maximally suspicious. It MUST be
    ``None`` unless ``status == VALID``. The risk engine only ever scores ``VALID`` signals.
    """

    name: str
    layer: int  # 1..5 (1 capture anti-spoof, 2 identity, 3 forensics, 4 challenge, 5 risk)
    mode: Mode
    status: SignalStatus
    suspicion: float | None = Field(default=None, ge=0.0, le=1.0)
    weight: float = Field(default=0.0, ge=0.0)
    reason: str = ""
    evidence_regions: list[EvidenceRegion] = Field(default_factory=list)
    measurements: dict[str, Any] = Field(default_factory=dict)
    producing_mode: Mode = Mode.ANY

    @model_validator(mode="after")
    def _check_suspicion_consistency(self) -> LayerSignal:
        if self.status == SignalStatus.VALID and self.suspicion is None:
            raise ValueError(f"VALID signal '{self.name}' must carry a suspicion value")
        if self.status != SignalStatus.VALID and self.suspicion is not None:
            raise ValueError(
                f"non-VALID signal '{self.name}' must have suspicion=None (got {self.suspicion})"
            )
        return self

    # --- ergonomic constructors so analyzers can't forget the invariants -----------------

    @classmethod
    def valid(
        cls,
        name: str,
        layer: int,
        mode: Mode,
        suspicion: float,
        weight: float,
        reason: str,
        *,
        evidence_regions: list[EvidenceRegion] | None = None,
        measurements: dict[str, Any] | None = None,
    ) -> LayerSignal:
        return cls(
            name=name,
            layer=layer,
            mode=mode,
            status=SignalStatus.VALID,
            suspicion=float(suspicion),
            weight=float(weight),
            reason=reason,
            evidence_regions=evidence_regions or [],
            measurements=measurements or {},
            producing_mode=mode,
        )

    @classmethod
    def not_evaluated(
        cls, name: str, layer: int, mode: Mode, reason: str, **measurements: Any
    ) -> LayerSignal:
        """An honest gate (CLAUDE.md §3.4): excluded from the score, shown as pending in the UI."""
        return cls(
            name=name,
            layer=layer,
            mode=mode,
            status=SignalStatus.NOT_EVALUATED,
            reason=reason,
            measurements=dict(measurements),
            producing_mode=mode,
        )

    @classmethod
    def error(cls, name: str, layer: int, mode: Mode, reason: str) -> LayerSignal:
        """A detector failure. Fail-closed: pushes the verdict toward REVIEW (never silent PASS)."""
        return cls(
            name=name,
            layer=layer,
            mode=mode,
            status=SignalStatus.ERROR,
            reason=reason,
            producing_mode=mode,
        )


class Provenance(BaseModel):
    """Result of Tier-1 source-of-truth verification."""

    verified: bool = False
    method: str = "none"  # PAdES | C2PA | DigiLocker | AA | none
    detail: str = ""
    tampered: bool = False  # signature present but INVALID == active tampering evidence


class TrustScore(BaseModel):
    """The published verdict the bank's core system consumes."""

    session_id: str
    intake_mode: Mode
    doc_type: str | None = None
    provenance: Provenance = Field(default_factory=Provenance)
    trust_score: float
    verdict: Verdict
    tier_reached: str  # "source-verified" | "forensic-fallback" | "in-person-capture"
    signals: list[LayerSignal] = Field(default_factory=list)
    evidence_pack: dict[str, Any] = Field(default_factory=dict)
    fail_closed: bool = False


class BundleDocument(BaseModel):
    """One document's result within a bundle, plus the label used in the cross-document graph."""

    label: str                  # e.g. "doc1:bank_statement.pdf"
    trust: TrustScore


class BundleTrustScore(BaseModel):
    """The published verdict for a MULTI-document application bundle (ADR-003 #3).

    Holds each document's individual :class:`TrustScore` plus the bundle-level
    ``cross_document`` consistency signal and an overall fail-closed bundle verdict. The bundle is
    never *more* trusting than its worst document, and a cross-document identity mismatch drives the
    bundle score down hard (identity fraud across the application).
    """

    session_id: str
    document_count: int
    documents: list[BundleDocument] = Field(default_factory=list)
    cross_document: LayerSignal  # the identity corroboration signal (kept for back-compat)
    # Every bundle-level corroboration signal (identity + cross-source income/employer, ADR-004 §6) so
    # the console can surface both the "same person?" and the "same income story?" cross-checks.
    corroboration: list[LayerSignal] = Field(default_factory=list)
    bundle_score: float
    bundle_verdict: Verdict
    fail_closed: bool = False
    reasons: list[str] = Field(default_factory=list)


@dataclass
class AnalysisContext:
    """In-memory, ephemeral per-session state handed to every analyzer.

    Holds the raw intake plus a ``shared`` scratch space so foundation analyzers (rectify, OCR)
    can publish derived artifacts once and the rest reuse them instead of recomputing. Frames and
    images live here as NumPy arrays / bytes and are NEVER persisted (CLAUDE.md §10).
    """

    session_id: str
    intake_mode: Mode
    doc_type: str | None = None
    # FILE intake
    file_bytes: bytes | None = None
    file_name: str | None = None
    file_mime: str | None = None
    # CAMERA intake — a short rolling buffer of recent frames (BGR np.ndarray)
    frames: list[Any] = field(default_factory=list)
    # capability map: which issuer/source could have been verified for this doc (red-flag logic)
    source_was_pullable: bool = False
    # shared derived artifacts (e.g. shared["rectified"], shared["ocr"]); analyzer-populated
    shared: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=lambda: time.monotonic())


@runtime_checkable
class Analyzer(Protocol):
    """Every detector is one of these. Stateless: ``analyze`` is a pure function of the context.

    Contract:
      * ``mode`` is the ONLY mode the orchestrator may run this analyzer in (registry-enforced).
      * if ``applicable(ctx)`` is False -> the orchestrator skips it (or it returns NOT_EVALUATED).
      * ``analyze`` must NOT raise for ordinary bad input -> return ``LayerSignal.error(...)``;
        the orchestrator still guards against unexpected exceptions (fail-closed).
      * ``suspicion`` MUST move monotonically when the input changes in the way the detector
        claims to detect (enforced by the discrimination + constant-return tests, CLAUDE.md §3.2).
    """

    name: str
    layer: int
    mode: Mode

    def applicable(self, ctx: AnalysisContext) -> bool: ...

    def analyze(self, ctx: AnalysisContext) -> LayerSignal: ...
