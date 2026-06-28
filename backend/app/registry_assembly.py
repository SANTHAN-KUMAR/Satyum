"""Wire every implemented analyzer into a single :class:`AnalyzerRegistry` (ADR-002 waterfall).

This is the one place that knows the concrete analyzer set; the orchestrator depends only on the
registry interface (Dependency Inversion, CLAUDE.md §4). Registration is **eager and strict**: every
import must resolve. We deliberately do NOT import defensively — a missing analyzer module is an
integration error to surface loudly at startup, never a silently-dropped detector (a dropped fraud
detector is worse than a crash).

Ordering note: the registry sorts analyzers by ``(layer, order, registration-index)`` when it serves
a mode, so the waterfall runs Tier 1 (provenance) → Tier 3-file forensics → Tier 4 challenge, and
within a layer the dependency order holds (e.g. ``document_parse`` order 5 publishes the parsed
statement before ``arithmetic_consistency`` reads it; ``pades_signature`` order 10 sets
``provenance_verified`` before the order-20 PDF-only red flag consults it). We still register in the
same logical order for readability and as a tiebreak.

A ``trust_anchor_dir`` override is threaded through to the crypto analyzers so a test (or a deployment
pinning the CCA-India root) can point them at a specific pinned trust store (§5 config-over-hardcode).
"""

from __future__ import annotations

from app.registry import AnalyzerRegistry
from capture.antispoof import (
    SpectralMoireAnalyzer,
    SpecularGlareAnalyzer,
    TemporalEntropyAnalyzer,
)
from capture.challenge import ActiveChallengeAnalyzer

# Tier 3 — live capture (camera mode)
from capture.rectify import RectifyQualityAnalyzer
from forensics.arithmetic import ArithmeticConsistencyAnalyzer
from forensics.copy_move import CopyMoveAnalyzer
from forensics.entities import EntityExtractionAnalyzer
from forensics.layout import FontLayoutAnalyzer
from forensics.metadata import PdfStructureAnalyzer

# Tier 2 — document forensics / OCR / consistency
from forensics.ocr import DocumentParseAnalyzer
from forensics.phash import PhashResubmissionAnalyzer
from forensics.template import TemplateFingerprintAnalyzer
from verification.provenance import PdfOnlyRedFlagAnalyzer

# Tier 1 — cryptographic provenance (the cyber core)
from verification.signature import C2paProvenanceAnalyzer, PadesSignatureAnalyzer


def build_registry(trust_anchor_dir: str | None = None) -> AnalyzerRegistry:
    """Construct and return the fully-wired analyzer registry.

    Args:
        trust_anchor_dir: optional override for the pinned PKI / C2PA trust store, forwarded to the
            signature analyzers. ``None`` uses ``settings.trust_anchor_dir``.
    """
    registry = AnalyzerRegistry()

    # --- Tier 1: provenance (FILE) — signature first, then the source-avoidance red flag --------
    registry.register(PadesSignatureAnalyzer(anchor_dir=trust_anchor_dir))  # layer 1, order 10
    registry.register(C2paProvenanceAnalyzer(anchor_dir=trust_anchor_dir))  # layer 1, order 11
    registry.register(PdfOnlyRedFlagAnalyzer())                             # layer 1, order 20

    # --- Tier 3: capture quality gate (CAMERA) — foundation for every camera signal ------------
    registry.register(RectifyQualityAnalyzer())                            # layer 1 (camera), order 5

    # --- Tier 2: forensics (FILE / ANY) — parse publishes the statement before arithmetic -------
    registry.register(DocumentParseAnalyzer())                             # layer 3, order 5 (ANY)
    registry.register(ArithmeticConsistencyAnalyzer())                     # layer 3 (ANY)
    registry.register(TemplateFingerprintAnalyzer())                       # layer 3, order 31 (FILE)
    registry.register(FontLayoutAnalyzer())                                # layer 3, order 32 (ANY)
    registry.register(PdfStructureAnalyzer())                              # layer 3, order 30 (FILE)
    registry.register(CopyMoveAnalyzer())                                  # layer 3, order 35 (ANY)
    registry.register(PhashResubmissionAnalyzer())                         # layer 3, order 40 (ANY)
    registry.register(EntityExtractionAnalyzer())                          # layer 3, order 45 (FILE)

    # --- Tier 3: anti-spoof votes (CAMERA) — low/medium-weight, never standalone gates ----------
    registry.register(SpectralMoireAnalyzer())                             # layer 1 (camera)
    registry.register(SpecularGlareAnalyzer())                             # layer 1 (camera)
    registry.register(TemporalEntropyAnalyzer())                           # layer 1 (camera)

    # --- Tier 4: the active 3D challenge (CAMERA) — centerpiece anti-replay anchor ---------------
    registry.register(ActiveChallengeAnalyzer())                           # layer 4, order 10

    return registry
