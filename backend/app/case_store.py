"""Persistent application-case file: an applicant's documents accumulate into one case, and the
cross-document corroboration strengthens as each new document arrives.

Real underwriting is not one document in isolation. An applicant submits a PAN, then a bank statement,
then a Form-16, over the life of a loan application. Each new document is another chance to corroborate
(or contradict) the same identity and the same income story. This store keeps a case's accumulated
identity claims so the cross-document graph (forensics/cross_document.py) is re-run over the WHOLE set
every time a document is added: two documents that agree raise confidence, a third that agrees raises it
further, and one that disagrees on a hard identifier (PAN, Aadhaar, account) flags identity fraud.

Privacy (CLAUDE.md §10): the store holds the EXTRACTED identity claims (:class:`ExtractedEntities`),
per-document verdict metadata, and each document's full (structured, JSON) evidence pack — never the
document bytes or any imagery. The evidence pack is the same structured record already shown to the
underwriter in the console (signals, reasons, measurements — no images, no raw file); persisting it here
is what lets the case-level Underwriter Copilot answer a question about ANY document in the case, not
just the one most recently viewed (the copilot's tools read it via ``interpretability/tools.py``). It is
in-memory now and designed to move to an encrypted-at-rest Postgres table behind the same interface
(stateless-scalable, §4). A case exists only under the applicant's consent, recorded on creation.
"""

from __future__ import annotations

import copy
import secrets
from dataclasses import dataclass, field
from typing import Any

from app.contracts import LayerSignal
from forensics.cross_document import cross_document_signal
from forensics.entities import ExtractedEntities


@dataclass
class CaseDocument:
    """One document's contribution to a case: its extracted identity claims and its own verdict."""

    doc_id: str
    label: str          # e.g. "pan", "bank_statement", "aadhaar", "form16"
    entities: ExtractedEntities
    verdict: str        # the per-document TrustScore verdict (APPROVED / REVIEW / REJECTED)
    added_at: str       # ISO timestamp, supplied by the caller (no wall-clock in this module)
    # The full structured evidence pack (TrustScore.model_dump()) this document produced — the same
    # record the underwriter already saw in the console. None only for a document added before this
    # field existed (a durable-store migration edge case), or if the caller genuinely has none.
    evidence_pack: dict[str, Any] | None = None


@dataclass
class CaseState:
    """An application case: the applicant reference, the accumulated documents, and consent metadata."""

    case_id: str
    applicant_ref: str | None
    consent_id: str | None
    created_at: str
    documents: list[CaseDocument] = field(default_factory=list)


def case_corroboration(case: CaseState) -> LayerSignal:
    """Re-run the cross-document identity corroboration over EVERY document accumulated in the case.

    Returns NOT_EVALUATED until at least two documents share a comparable identity field; VALID once
    they do, with suspicion driven by the most severe disagreement (a hard-identifier mismatch is
    dispositive). This is the signal that strengthens as consistent documents are added.
    """
    entities_by_doc = {f"{d.label}#{d.doc_id[:6]}": d.entities for d in case.documents}
    return cross_document_signal(entities_by_doc)


class CaseStore:
    """In-memory application-case store. Swappable to a durable, encrypted-at-rest backend behind this
    same interface. All timestamps are supplied by the caller so the store stays deterministic."""

    def __init__(self) -> None:
        self._cases: dict[str, CaseState] = {}

    def create(self, *, applicant_ref: str | None, consent_id: str | None, now: str) -> CaseState:
        case_id = f"case_{secrets.token_hex(8)}"
        case = CaseState(
            case_id=case_id, applicant_ref=applicant_ref, consent_id=consent_id, created_at=now
        )
        self._cases[case_id] = case
        return case

    def get(self, case_id: str) -> CaseState | None:
        return self._cases.get(case_id)

    def add_document(
        self,
        case_id: str,
        *,
        label: str,
        entities: ExtractedEntities,
        verdict: str,
        now: str,
        evidence_pack: dict[str, Any] | None = None,
    ) -> CaseState:
        """Append a document's extracted claims to the case. Raises KeyError for an unknown case."""
        case = self._cases[case_id]
        case.documents.append(
            CaseDocument(
                doc_id=secrets.token_hex(6),
                label=(label or "document").strip().lower(),
                entities=entities,
                verdict=verdict,
                added_at=now,
                # Deep-copy: the store owns this record from here — a caller that later mutates the
                # dict it passed in (e.g. reuses a scratch buffer) must never corrupt case history
                # (CLAUDE.md §5 — immutability at boundaries, no shared mutable state across sessions).
                evidence_pack=copy.deepcopy(evidence_pack) if evidence_pack is not None else None,
            )
        )
        return case
