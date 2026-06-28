"""Verification API routes: file upload (POST), session lookup (GET), live camera (WS).

Trust-boundary discipline (CLAUDE.md §4/§10): every uploaded file is treated as hostile — size and
type are guarded *before* any parsing, against ``settings.max_file_bytes``. The handlers never log
document bytes or PII; only a session correlation id and decision metadata reach the structured log.
Analyzer work is CPU-bound (PDF parse / OCR / crypto), so it runs in a threadpool to keep the async
event loop responsive (§7).

The shared :class:`AuditLedger`, :class:`AnalyzerRegistry`, and :class:`SessionManager` are created
once at app startup (``app.main``) and read off ``request.app.state`` here.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import (
    APIRouter,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from starlette.concurrency import run_in_threadpool

from app.bundle import verify_bundle
from app.config import settings
from app.contracts import AnalysisContext, BundleTrustScore, Mode, TrustScore
from app.orchestrator import run_verification
from verification.provenance import issuer_is_sourceable

log = structlog.get_logger(__name__)

router = APIRouter()

# Accepted upload content-types (defensive allow-list, §10). PDFs are the primary path; images cover
# scanned/photographed statements and the C2PA image path.
_ALLOWED_MIME = {
    "application/pdf",
    "application/octet-stream",  # some clients send PDFs as octet-stream; magic-byte check still applies
    "image/jpeg",
    "image/png",
    "image/webp",
}

_PDF_MAGIC = b"%PDF-"
_IMAGE_MAGICS = (
    b"\xff\xd8\xff",            # JPEG
    b"\x89PNG\r\n\x1a\n",       # PNG
    b"RIFF",                    # WebP (RIFF container)
)


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


def _looks_like_document(data: bytes) -> bool:
    """Cheap magic-byte sniff so we reject obviously-non-document uploads before parsing."""
    if data[:5] == _PDF_MAGIC or _PDF_MAGIC in data[:1024]:
        return True
    return any(data[: len(m)] == m for m in _IMAGE_MAGICS)


# ---------------------------------------------------------------------------------------------
# POST /api/verify — file intake
# ---------------------------------------------------------------------------------------------

@router.post("/api/verify", response_model=TrustScore)
async def verify_file(
    request: Request,
    file: UploadFile = File(...),  # noqa: B008 — FastAPI's declarative default pattern
    doc_type: str | None = Form(default=None),
    issuer_hint: str | None = Form(default=None),
) -> TrustScore:
    """Verify an uploaded document and return the :class:`TrustScore` (incl. the evidence pack).

    Pipeline: size/type guard → build a FILE-mode :class:`AnalysisContext` (with the issuer-capability
    red-flag input derived from ``issuer_hint``) → run the verification waterfall → audit → respond.
    """
    raw = await file.read()

    # --- guard 1: non-empty ----------------------------------------------------------------
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="empty file upload"
        )

    # --- guard 2: size cap (§10) -----------------------------------------------------------
    if len(raw) > settings.max_file_bytes:
        raise HTTPException(
            status_code=413,  # Content Too Large (constant name varies across Starlette versions)
            detail=f"file exceeds {settings.max_file_bytes} bytes",
        )

    # --- guard 3: declared type allow-list -------------------------------------------------
    if file.content_type is not None and file.content_type not in _ALLOWED_MIME:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"unsupported content-type {file.content_type!r}",
        )

    # --- guard 4: magic-byte sniff (declared type can lie) ---------------------------------
    if not _looks_like_document(raw):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="payload is not a recognised PDF or image document",
        )

    session = request.app.state.sessions
    registry = request.app.state.registry
    ledger = request.app.state.ledger

    # Real source-capability red-flag input: was a verifiable source pullable for this issuer? (D3)
    source_was_pullable = issuer_is_sourceable(issuer_hint)

    ctx: AnalysisContext = session.create(
        intake_mode=Mode.FILE,
        doc_type=doc_type,
        file_bytes=raw,
        file_name=file.filename,
        file_mime=file.content_type,
        source_was_pullable=source_was_pullable,
    )

    bound = log.bind(session_id=ctx.session_id, intake_mode="FILE", doc_type=doc_type)
    bound.info(
        "verify.file.received",
        size_bytes=len(raw),
        content_type=file.content_type,
        source_was_pullable=source_was_pullable,
    )  # NB: never log raw bytes / filename PII content — size + type only (§10)

    try:
        # CPU-bound (parse + OCR + crypto) — keep the event loop free (§7).
        trust: TrustScore = await run_in_threadpool(
            run_verification, ctx, registry, ledger, _iso_now()
        )
    finally:
        # File bytes are not needed after scoring — release them immediately (§10).
        session.mark_scored(ctx.session_id)
        ctx.file_bytes = None

    bound.info(
        "verify.file.scored",
        verdict=trust.verdict.value,
        trust_score=trust.trust_score,
        tier=trust.tier_reached,
        fail_closed=trust.fail_closed,
    )
    return trust


# ---------------------------------------------------------------------------------------------
# POST /api/verify-bundle — multi-document bundle intake + cross-document consistency (ADR-003 #3)
# ---------------------------------------------------------------------------------------------

# A loan application bundle is small (statement + ID + deed + a few more). Bound it defensively so a
# caller cannot fan out unbounded parsing work in one request (§7/§10). DEFAULT — adjust to product.
_MIN_BUNDLE_DOCS = 2
_MAX_BUNDLE_DOCS = 12


def _guard_upload(raw: bytes, content_type: str | None) -> None:
    """Apply the same hostile-input guards as the single-file path; raise HTTPException on failure."""
    if not raw:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="empty file in bundle")
    if len(raw) > settings.max_file_bytes:
        raise HTTPException(status_code=413, detail=f"a file exceeds {settings.max_file_bytes} bytes")
    if content_type is not None and content_type not in _ALLOWED_MIME:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"unsupported content-type {content_type!r} in bundle",
        )
    if not _looks_like_document(raw):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="a payload in the bundle is not a recognised PDF or image",
        )


@router.post("/api/verify-bundle", response_model=BundleTrustScore)
async def verify_bundle_route(
    request: Request,
    files: list[UploadFile] = File(...),  # noqa: B008 — FastAPI's declarative default pattern
    issuer_hint: str | None = Form(default=None),
) -> BundleTrustScore:
    """Verify an application BUNDLE: each document individually, then the cross-document graph.

    The bundle is fail-closed (CLAUDE.md §4): never more trusting than its worst document, and a
    cross-document identity mismatch (e.g. the name/PAN on the ID disagrees with the bank statement)
    drives the bundle verdict down hard — that is identity fraud across the application.
    """
    if not (_MIN_BUNDLE_DOCS <= len(files) <= _MAX_BUNDLE_DOCS):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"a bundle needs {_MIN_BUNDLE_DOCS}-{_MAX_BUNDLE_DOCS} documents, got {len(files)}",
        )

    session = request.app.state.sessions
    registry = request.app.state.registry
    ledger = request.app.state.ledger
    source_was_pullable = issuer_is_sourceable(issuer_hint)

    labelled: list[tuple[str, AnalysisContext]] = []
    for i, f in enumerate(files):
        raw = await f.read()
        _guard_upload(raw, f.content_type)
        ctx = session.create(
            intake_mode=Mode.FILE,
            doc_type=None,
            file_bytes=raw,
            file_name=f.filename,
            file_mime=f.content_type,
            source_was_pullable=source_was_pullable,
        )
        labelled.append((f"doc{i + 1}:{f.filename or 'unnamed'}", ctx))

    bundle_id = f"bundle-{secrets.token_urlsafe(8)}"
    bound = log.bind(session_id=bundle_id, intake_mode="FILE-BUNDLE", document_count=len(files))
    bound.info("verify.bundle.received", document_count=len(files))

    try:
        bundle: BundleTrustScore = await run_in_threadpool(
            verify_bundle, labelled, registry, ledger, _iso_now(), bundle_session_id=bundle_id
        )
    finally:
        # Release every document's bytes immediately after scoring (privacy by design, §10).
        for _label, ctx in labelled:
            session.mark_scored(ctx.session_id)
            ctx.file_bytes = None

    bound.info(
        "verify.bundle.scored",
        bundle_verdict=bundle.bundle_verdict.value,
        bundle_score=bundle.bundle_score,
        fail_closed=bundle.fail_closed,
        cross_document_status=bundle.cross_document.status.value,
    )
    return bundle


# ---------------------------------------------------------------------------------------------
# GET /api/session/{id} — lightweight session status (no document content ever returned)
# ---------------------------------------------------------------------------------------------

@router.get("/api/session/{session_id}")
async def get_session(request: Request, session_id: str) -> dict[str, Any]:
    """Return non-sensitive session status. Never returns document bytes or frames (§10)."""
    session = request.app.state.sessions
    ctx = session.get(session_id)
    if ctx is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="unknown or expired session"
        )
    return {
        "session_id": ctx.session_id,
        "intake_mode": ctx.intake_mode.value,
        "doc_type": ctx.doc_type,
        "frames_buffered": len(ctx.frames),
        "challenge_issued": "challenge" in ctx.shared,
    }


# ---------------------------------------------------------------------------------------------
# WS /ws/verify — live camera (Tier-3) capture
# ---------------------------------------------------------------------------------------------

# Camera-path tunables (§7 backpressure): bound the rolling frame buffer so a flood can never grow
# memory unboundedly — drop the oldest, never queue without limit.
_MAX_FRAMES_BUFFERED = 30
_MIN_FRAMES_TO_SCORE = 4  # matches ActiveChallengeAnalyzer._MIN_FRAMES

# The active-challenge command space the server may randomly issue (anti-replay nonce). Verified by
# the homography in ActiveChallengeAnalyzer against the tracked corner motion. The COMMANDED
# magnitude is randomized over a continuous range (not a single public constant): a single
# pre-recorded tilt clip only satisfies commands within +/-challenge_homography_tol_deg of its own
# tilt, so a wider random magnitude forces an attacker to hold a *library* of clips rather than one.
# Range is bounded to angles a webcam can resolve while keeping the document in frame.
# TODO(satyum): the strongest anti-replay is a multi-STEP randomized sequence (e.g. "tilt x, THEN
# pan y") verified as an ordered chain of homographies — a single-tilt challenge has inherently
# bounded entropy. Tracked for a follow-up; the single-tilt homography-consistency check still
# defeats photo-of-screen replay today (see ActiveChallengeAnalyzer honest_bound).
_CHALLENGE_AXES = ("x", "y")
_CHALLENGE_MIN_DEG = 12.0
_CHALLENGE_MAX_DEG = 30.0
_CHALLENGE_STEP_DEG = 0.5


def _random_magnitude_deg() -> float:
    """A cryptographically-random commanded tilt magnitude in [MIN, MAX] at STEP resolution."""
    steps = round((_CHALLENGE_MAX_DEG - _CHALLENGE_MIN_DEG) / _CHALLENGE_STEP_DEG)
    return round(_CHALLENGE_MIN_DEG + _CHALLENGE_STEP_DEG * secrets.randbelow(steps + 1), 1)


def _issue_challenge() -> dict[str, Any]:
    """Mint a server-randomized, just-in-time 3D challenge (a time-bounded anti-replay nonce, §10)."""
    return {
        "axis": secrets.choice(_CHALLENGE_AXES),
        "magnitude_deg": _random_magnitude_deg(),
        "nonce": secrets.token_urlsafe(8),
    }


def _decode_frame(payload: bytes):
    """Decode a binary frame (JPEG/PNG bytes) into a BGR ndarray, or ``None`` if undecodable.

    Frames live only in memory and are never written to disk or logs (§10).
    """
    import cv2
    import numpy as np

    arr = np.frombuffer(payload, dtype=np.uint8)
    if arr.size == 0:
        return None
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)  # -> BGR ndarray or None
    return img


@router.websocket("/ws/verify")
async def verify_camera(websocket: WebSocket) -> None:
    """Live camera verification: accept frames, issue a random 3D challenge, stream tier status.

    Protocol:
      * server → client on connect: ``{"type": "challenge", "challenge": {...}, "session_id": ...}``
      * client → server: binary messages, each a JPEG/PNG-encoded frame
      * client → server text ``"score"`` (or buffer full): run camera-mode verification
      * server → client: ``{"type": "status", ...}`` per accepted frame, then
        ``{"type": "result", "trust_score": {...}}`` with the final :class:`TrustScore`.

    Frames are dropped from the session the instant scoring completes (§10).
    """
    app = websocket.app
    session = app.state.sessions
    registry = app.state.registry
    ledger = app.state.ledger

    await websocket.accept()

    ctx: AnalysisContext = session.create(intake_mode=Mode.CAMERA, doc_type="live_capture")
    challenge = _issue_challenge()
    ctx.shared["challenge"] = challenge

    bound = log.bind(session_id=ctx.session_id, intake_mode="CAMERA")
    bound.info("verify.ws.connected", challenge_axis=challenge["axis"], nonce=challenge["nonce"])

    await websocket.send_json(
        {"type": "challenge", "session_id": ctx.session_id, "challenge": challenge}
    )

    scored = False
    try:
        while True:
            message = await websocket.receive()

            if message.get("type") == "websocket.disconnect":
                break

            text = message.get("text")
            data = message.get("bytes")

            if text is not None:
                if text.strip().lower() == "score":
                    await _score_camera(websocket, session, registry, ledger, ctx, bound)
                    scored = True
                    break
                # ignore other control text quietly (keeps the stream alive)
                continue

            if data is None:
                continue

            frame = _decode_frame(data)
            if frame is None:
                await websocket.send_json(
                    {"type": "status", "tier": "capture", "accepted": False,
                     "reason": "undecodable frame"}
                )
                continue

            # Backpressure: bound the buffer; drop the oldest rather than grow without limit (§7).
            if len(ctx.frames) >= _MAX_FRAMES_BUFFERED:
                ctx.frames.pop(0)
            session.add_frame(ctx.session_id, frame)

            await websocket.send_json(
                {"type": "status", "tier": "capture", "accepted": True,
                 "frames_buffered": len(ctx.frames),
                 "ready_to_score": len(ctx.frames) >= _MIN_FRAMES_TO_SCORE}
            )

    except WebSocketDisconnect:
        bound.info("verify.ws.disconnected")
    except Exception as exc:  # noqa: BLE001 — a stream failure must never crash the server (§4)
        bound.warning("verify.ws.error", error=repr(exc))
        try:
            await websocket.send_json({"type": "error", "detail": "stream error"})
        except Exception:  # noqa: BLE001 — socket may already be gone
            pass
    finally:
        # Privacy hard-stop (§10): frames never outlive the session; drop them and end it.
        session.drop_frames(ctx.session_id)
        session.end(ctx.session_id)
        if not scored:
            bound.info("verify.ws.closed_without_score")


async def _score_camera(
    websocket: WebSocket,
    session,
    registry,
    ledger,
    ctx: AnalysisContext,
    bound,
) -> None:
    """Run camera-mode verification on the buffered frames and stream back the result."""
    if len(ctx.frames) < _MIN_FRAMES_TO_SCORE:
        await websocket.send_json(
            {"type": "error",
             "detail": f"need >= {_MIN_FRAMES_TO_SCORE} frames to score (have {len(ctx.frames)})"}
        )
        return

    try:
        trust: TrustScore = await run_in_threadpool(
            run_verification, ctx, registry, ledger, _iso_now()
        )
    finally:
        session.mark_scored(ctx.session_id)
        session.drop_frames(ctx.session_id)  # frames dropped the instant scoring completes (§10)

    bound.info(
        "verify.ws.scored",
        verdict=trust.verdict.value,
        trust_score=trust.trust_score,
        tier=trust.tier_reached,
        fail_closed=trust.fail_closed,
    )
    await websocket.send_json(
        {"type": "result", "trust_score": trust.model_dump(mode="json")}
    )
