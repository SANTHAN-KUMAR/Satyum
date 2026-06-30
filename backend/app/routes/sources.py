"""Source-pull API route (PROPOSAL-001 §4 / §9.3): POST /api/sources/{provider}/pull.

The onboarding source-pull endpoint. It is **consent-gated** (DPDP Act 2023 §7.3): every pull carries
an explicit :class:`ConsentArtifact`, and the consent + outcome are written to the tamper-evident
audit ledger (never the document bytes or PII — §10). When a provider returns a cryptographically
*verified* signed document, the verified bytes feed the existing verification core so the response
also carries a full :class:`TrustScore` — "integrity answered at the root" flows straight into the
deterministic engine.

Trust-boundary discipline (§4/§10): the uploaded payload is treated as hostile — size-capped before
parsing; never logged. The provider layer fails closed on bad input (never a fabricated pass).
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.contracts import AnalysisContext, Mode, TrustScore
from app.orchestrator import run_verification
from providers.contracts import (
    ConsentArtifact,
    DocClass,
    DocRequest,
    SourceResult,
)
from providers.service import UnknownProviderError, pull_source

log = structlog.get_logger(__name__)

router = APIRouter()


class SourcePullResponse(BaseModel):
    """The source-pull result, plus a full TrustScore when a verified document fed the core."""

    source_result: SourceResult
    trust_score: TrustScore | None = None


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


def _parse_doc_class(raw: str) -> DocClass:
    try:
        return DocClass(raw)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unknown doc_class {raw!r}; expected one of {[c.value for c in DocClass]}",
        ) from None


@router.post("/api/sources/{provider}/pull", response_model=SourcePullResponse)
async def pull_source_route(
    request: Request,
    provider: str,
    doc_class: str = Form(...),
    consent_id: str = Form(...),
    purpose: str = Form(default="loan_underwriting_document_verification"),
    granted_at: str | None = Form(default=None),
    issuer_hint: str | None = Form(default=None),
    applicant_ref: str | None = Form(default=None),
    share_code: str | None = Form(default=None),  # Aadhaar offline e-KYC ZIP password, when applicable
    name: str | None = Form(default=None),         # applicant name (for PAN name-match)
    dob: str | None = Form(default=None),          # applicant DOB DD/MM/YYYY (for PAN verification)
    file: UploadFile | None = File(default=None),  # noqa: B008 — FastAPI declarative default
) -> SourcePullResponse:
    """Pull/verify a document from a source provider under explicit consent."""
    dc = _parse_doc_class(doc_class)

    # --- read + guard the optional payload (hostile until proven otherwise, §10) ----------------
    payload: bytes | None = None
    if file is not None:
        payload = await file.read()
        if not payload:
            payload = None
        elif len(payload) > settings.max_file_bytes:
            raise HTTPException(status_code=413, detail=f"payload exceeds {settings.max_file_bytes} bytes")

    consent = ConsentArtifact(
        consent_id=consent_id,
        purpose=purpose,
        doc_class=dc,
        granted_at=granted_at or _iso_now(),
        applicant_ref=applicant_ref,
    )
    doc_request = DocRequest(
        doc_class=dc, issuer_hint=issuer_hint, applicant_ref=applicant_ref,
        share_code=share_code, claimant_name=name, dob=dob,
    )

    registry = request.app.state.providers
    ledger = request.app.state.ledger
    analyzer_registry = request.app.state.registry

    bound = log.bind(consent_id=consent_id, provider=provider, doc_class=dc.value)
    bound.info("source.pull.received", has_payload=payload is not None)

    try:
        result: SourceResult = await run_in_threadpool(
            pull_source, registry, provider, consent, doc_request, payload
        )
    except UnknownProviderError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"unknown provider {provider!r}",
        ) from None

    # --- DPDP consent + outcome audit (no document bytes / PII — §7.3 / §10) --------------------
    ledger.record(
        _iso_now(),
        {
            "event": "source_pull",
            "consent_id": consent.consent_id,
            "purpose": consent.purpose,
            "provider": result.provider,
            "doc_class": result.doc_class.value,
            "signature_status": result.signature_status.value,
            "provenance_mode": result.provenance_mode.value,
            "issuer": result.issuer,
            "gated": bool(result.gate),
        },
    )

    # --- when a verified signed document came back, feed the verification core ------------------
    trust: TrustScore | None = None
    if result.verified_at_source and result.signed_bytes is not None:
        ctx = AnalysisContext(
            session_id=f"src-{consent.consent_id}",
            intake_mode=Mode.FILE,
            doc_type=dc.value,
            file_bytes=result.signed_bytes,
            file_name="source_pulled.pdf",
            file_mime="application/pdf",
        )
        try:
            trust = await run_in_threadpool(
                run_verification, ctx, analyzer_registry, ledger, _iso_now()
            )
        finally:
            ctx.file_bytes = None  # release the bytes immediately after scoring (§10)

    bound.info(
        "source.pull.done",
        signature_status=result.signature_status.value,
        verified_at_source=result.verified_at_source,
        gated=bool(result.gate),
        produced_trust_score=trust is not None,
    )

    # Never return the raw payload bytes (SourceResult excludes them from serialisation; be explicit).
    return SourcePullResponse(source_result=result, trust_score=trust)
