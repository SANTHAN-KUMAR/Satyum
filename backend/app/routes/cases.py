"""Application-case API: POST /api/cases, GET /api/cases/{id}.

An application case accumulates an applicant's documents so the cross-document identity graph
strengthens over time (app/case_store.py). A case is created under explicit consent. Documents are
added by the verify route (POST /api/verify with a ``case_id``): each verification contributes its
extracted identity claims to the case and re-runs the corroboration. This route creates cases and reads
back the accumulated case with its current cross-document corroboration signal.

Privacy (CLAUDE.md §10): the response carries the extracted identity claims and per-document verdicts
only, never document bytes or imagery.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import APIRouter, Form, HTTPException, Request, status
from pydantic import BaseModel

log = structlog.get_logger(__name__)

router = APIRouter()


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


class CaseDocumentView(BaseModel):
    doc_id: str
    label: str
    verdict: str
    added_at: str
    identity: dict[str, str]  # the comparable identity fields extracted from this document


class FieldComparisonView(BaseModel):
    """One field's cross-document comparison — mirrors forensics/cross_document.py::FieldComparison.
    status is one of "agree" | "near" | "disagree" (near = single-char OCR-slip, clamped to REVIEW,
    not a hard mismatch). Kept as its own model (not a raw dict) so the wire contract stays typed."""

    field: str
    status: str
    agree: bool
    values: dict[str, str]  # doc label -> the value that document carries


class CaseView(BaseModel):
    case_id: str
    applicant_ref: str | None
    created_at: str
    document_count: int
    documents: list[CaseDocumentView]
    # The accumulated cross-document corroboration over EVERY document in the case. status is
    # NOT_EVALUATED until two documents share a comparable field; then VALID (agreement or mismatch).
    corroboration_status: str
    corroboration_reason: str
    corroboration_suspicion: float | None
    identity_consistent: bool
    hard_mismatch_fields: list[str]
    # Full per-field breakdown (including the "near" OCR-slip tier) — previously computed server-side
    # but never forwarded past hard_mismatch_fields, so the frontend had to fake a coarser 2-tier view.
    # Now exposed for real (CLAUDE.md §9: don't ship a signal the frontend can't render honestly).
    comparisons: list[FieldComparisonView]


def _view(request: Request, case) -> CaseView:
    from app.case_store import case_corroboration

    sig = case_corroboration(case)
    m: dict[str, Any] = sig.measurements or {}
    return CaseView(
        case_id=case.case_id,
        applicant_ref=case.applicant_ref,
        created_at=case.created_at,
        document_count=len(case.documents),
        documents=[
            CaseDocumentView(
                doc_id=d.doc_id, label=d.label, verdict=d.verdict, added_at=d.added_at,
                identity=d.entities.comparable_fields(),
            )
            for d in case.documents
        ],
        corroboration_status=sig.status.value if hasattr(sig.status, "value") else str(sig.status),
        corroboration_reason=sig.reason or "",
        corroboration_suspicion=sig.suspicion,
        identity_consistent=not m.get("hard_reject", False)
        and not m.get("disagreeing_fields")
        and bool(m.get("comparisons")),
        hard_mismatch_fields=list(m.get("hard_mismatch_fields", [])),
        comparisons=[FieldComparisonView(**c) for c in m.get("comparisons", [])],
    )


@router.post("/api/cases", response_model=CaseView, status_code=status.HTTP_201_CREATED)
async def create_case(
    request: Request,
    applicant_ref: str | None = Form(default=None),
    consent_id: str | None = Form(default=None),
) -> CaseView:
    """Open a new application case (consented). Documents accrue via POST /api/verify with this case_id."""
    store = request.app.state.case_store
    case = store.create(applicant_ref=applicant_ref, consent_id=consent_id, now=_iso_now())
    log.info("case.created", case_id=case.case_id)  # never log applicant PII (§10)
    return _view(request, case)


@router.get("/api/cases/{case_id}", response_model=CaseView)
async def get_case(request: Request, case_id: str) -> CaseView:
    """Read the accumulated case and its current cross-document corroboration."""
    store = request.app.state.case_store
    case = store.get(case_id)
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"unknown case {case_id!r}")
    return _view(request, case)


class CaseDocumentEvidenceView(BaseModel):
    doc_id: str
    label: str
    verdict: str
    added_at: str
    evidence_pack: dict[str, Any] | None  # None only for a document added before this field existed


class CaseEvidenceView(BaseModel):
    case_id: str
    documents: list[CaseDocumentEvidenceView]


@router.get("/api/cases/{case_id}/evidence", response_model=CaseEvidenceView)
async def get_case_evidence(request: Request, case_id: str) -> CaseEvidenceView:
    """Every accumulated document's FULL evidence pack — additive to GET /api/cases/{id}, which stays
    identity+verdict only (the lightweight case-overview list). This is what lets the case-level
    Underwriter Copilot answer a question about ANY document in the case — not just the one most
    recently viewed — by giving its tools (interpretability/tools.py) something to read per document,
    fetched fresh server-side so it survives navigation/reload rather than living only in page state.
    """
    store = request.app.state.case_store
    case = store.get(case_id)
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"unknown case {case_id!r}")
    return CaseEvidenceView(
        case_id=case.case_id,
        documents=[
            CaseDocumentEvidenceView(
                doc_id=d.doc_id, label=d.label, verdict=d.verdict, added_at=d.added_at,
                evidence_pack=d.evidence_pack,
            )
            for d in case.documents
        ],
    )
