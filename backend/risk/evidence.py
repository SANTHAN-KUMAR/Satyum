"""The Underwriter Evidence Pack (ADR-001 D7 / ADR-002 D7).

Turns the raw verdict into the auditable case file an underwriter acts on: intake mode, document
type, provenance result, the verification tier reached, every signal with its status + producing
mode (NOT_EVALUATED shown honestly as pending), the deterministic tamper-evidence regions (only
those traced to a real detector), a recommended action with reasons, and the privacy note.

Pure function of the ``TrustScore`` — no I/O.
"""

from __future__ import annotations

from typing import Any

from app.contracts import SignalStatus, TrustScore, Verdict

_ACTION = {
    Verdict.APPROVED: "Proceed — integrity checks passed; no human review required for document integrity.",
    Verdict.REVIEW: "Route to a human underwriter — at least one signal is inconclusive or flagged.",
    Verdict.REJECTED: "Reject / escalate to fraud ops — strong tampering or failed verification.",
}

PRIVACY_NOTE = (
    "Ephemeral processing: camera frames and document content are held in memory for the session "
    "only and are never persisted. This record stores decision metadata and signal digests, not the "
    "document or any imagery."
)


def build_evidence_pack(trust: TrustScore) -> dict[str, Any]:
    flagged = [s for s in trust.signals if s.status == SignalStatus.VALID and (s.suspicion or 0) > 0]
    pending = [s for s in trust.signals if s.status == SignalStatus.NOT_EVALUATED]
    errored = [s for s in trust.signals if s.status == SignalStatus.ERROR]

    tamper_regions = [
        {**region.model_dump(), "suspicion": s.suspicion}
        for s in trust.signals
        if s.status == SignalStatus.VALID
        for region in s.evidence_regions
    ]

    reasons: list[str] = []
    if trust.provenance.tampered:
        reasons.append(
            f"Cryptographic signature present but INVALID ({trust.provenance.method}) — tampering."
        )
    elif trust.provenance.verified:
        reasons.append(f"Source verified cryptographically via {trust.provenance.method}.")
    for s in flagged:
        reasons.append(f"{s.name}: {s.reason}")
    for s in errored:
        reasons.append(f"{s.name}: errored — fail-closed ({s.reason}).")
    if not reasons:
        reasons.append("No adverse signals; document integrity checks reconcile.")

    return {
        "session_id": trust.session_id,
        "document_type": trust.doc_type,
        "intake_mode": trust.intake_mode.value,
        "tier_reached": trust.tier_reached,
        "provenance": trust.provenance.model_dump(),
        "trust_score": trust.trust_score,
        "verdict": trust.verdict.value,
        "fail_closed": trust.fail_closed,
        "recommended_action": _ACTION[trust.verdict],
        "reasons": reasons,
        "signals": [
            {
                "name": s.name,
                "layer": s.layer,
                "producing_mode": s.producing_mode.value,
                "status": s.status.value,
                "suspicion": s.suspicion,
                "weight": s.weight,
                "reason": s.reason,
            }
            for s in trust.signals
        ],
        "pending_not_evaluated": [{"name": s.name, "reason": s.reason} for s in pending],
        "tamper_evidence_regions": tamper_regions,
        "privacy_note": PRIVACY_NOTE,
    }
