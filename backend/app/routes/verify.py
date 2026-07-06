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

import base64
import json
import secrets
import time
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
from app.contracts import AnalysisContext, BundleTrustScore, Mode, PasswordRequired, TrustScore
from app.orchestrator import run_verification
from federation.service import advise_from_context
from forensics.entities import ExtractedEntities
from risk.engine import attach_advisory
from verification.pdf_crypto import is_pdf_encrypted, password_unlocks
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

@router.post("/api/verify", response_model=None)
async def verify_file(
    request: Request,
    file: UploadFile = File(...),  # noqa: B008 — FastAPI's declarative default pattern
    doc_type: str | None = Form(default=None),
    issuer_hint: str | None = Form(default=None),
    claimed_pan: str | None = Form(default=None),    # applicant-typed PAN → cross-checked vs the document
    claimed_name: str | None = Form(default=None),   # applicant-typed name → soft fallback identity check
    features_json: str | None = Form(default=None),  # engineered features for analyst-approved rules
    pdf_password: str | None = Form(default=None),   # unlocks an encrypted (password-protected) PDF
    case_id: str | None = Form(default=None),        # accrue this doc's identity claims into a case
) -> TrustScore | PasswordRequired:
    """Verify an uploaded document and return the :class:`TrustScore` (incl. the evidence pack).

    Pipeline: size/type guard → build a FILE-mode :class:`AnalysisContext` → run the verification
    waterfall → audit → respond. The PDF-only red flag derives the issuer from the *document* itself;
    ``issuer_hint`` is only a soft fallback for media with no readable text layer (ADR-004 Layer 1).
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

    # --- gate 5: password-protected PDF ----------------------------------------------------
    # Govt/bank PDFs (Aadhaar, CAMS, signed e-statements) ship encrypted. This is NOT a fraud signal —
    # it is a recoverable prompt. We take the password in-app and decrypt IN MEMORY (preserving the
    # signature) rather than the user round-tripping through a 3rd-party unlock that breaks it (§10).
    if is_pdf_encrypted(raw):
        if not (pdf_password and pdf_password.strip()):
            return PasswordRequired(file_name=file.filename)
        if not password_unlocks(raw, pdf_password):
            return PasswordRequired(
                file_name=file.filename,
                password_error="Incorrect password — please check and try again.",
            )

    session = request.app.state.sessions
    registry = request.app.state.registry
    ledger = request.app.state.ledger

    # Soft fallback for the PDF-only red flag — the analyzer derives the issuer from the document
    # itself; this client hint only adds coverage for media with no readable text layer (ADR-002 D3).
    source_was_pullable = issuer_is_sourceable(issuer_hint)

    ctx: AnalysisContext = session.create(
        intake_mode=Mode.FILE,
        doc_type=doc_type,
        file_bytes=raw,
        file_name=file.filename,
        file_mime=file.content_type,
        source_was_pullable=source_was_pullable,
    )

    # Applicant-claimed identity + engineered features (from onboarding) feed two deterministic
    # analyzers: ClaimedIdentityAnalyzer cross-checks a typed PAN against the PAN extracted from the
    # document; PromotedRuleAnalyzer fires analyst-approved rules over the features. Both are optional —
    # absent fields simply leave those analyzers NOT_EVALUATED (never an error).
    if pdf_password and pdf_password.strip():
        ctx.pdf_password = pdf_password  # held only for this request; never logged/persisted (§10)
    if claimed_pan and claimed_pan.strip():
        ctx.claimed_identity["pan"] = claimed_pan.strip().upper()
    if claimed_name and claimed_name.strip():
        # Soft fallback identity check (forensics/claimed_identity.py): PAN stays the authoritative,
        # hard-severity signal when present; name is the only signal left when a document (e.g. a land
        # deed/encumbrance certificate) carries no PAN at all — without it, a document belonging to a
        # different person entirely passed through with NO identity signal whatsoever (a real gap).
        ctx.claimed_identity["name"] = claimed_name.strip()
    if features_json:
        try:
            parsed = json.loads(features_json)
            if isinstance(parsed, dict):
                ctx.features = parsed
        except (json.JSONDecodeError, ValueError):
            bound_pre = log.bind(session_id=ctx.session_id)
            bound_pre.warning("verify.features_json.invalid")  # ignore malformed features, never fail

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

    # --- Layer-3 advisory consult (PROPOSAL-001 §5.4) — non-authoritative, fail-open --------------
    # Consult the shared fraud registry with artifacts the deterministic core already published into
    # ctx.shared (pHash / entities). A confirmed cross-bank match can raise an APPROVED case to human
    # REVIEW — it NEVER clears a document and NEVER changes the deterministic score (attach_advisory).
    fraud_registry = getattr(request.app.state, "fraud_registry", None)
    if fraud_registry is not None:
        try:
            advisories = advise_from_context(
                fraud_registry,
                ctx.shared,
                salt_hex=settings.federation_consortium_salt_hex,
                pepper=settings.federation_entity_pepper.encode("utf-8"),
                hamming_threshold=settings.phash_hamming_threshold,
            )
            if advisories:
                trust = attach_advisory(trust, advisories)
        except Exception as exc:  # noqa: BLE001 — advisory must NEVER break a verdict (fail-open, §4)
            bound.warning("advisory.consult.error", error=repr(exc))

    # --- application-case accrual: contribute this document's extracted identity claims to the case so
    # the cross-document graph strengthens over time (app/case_store.py). Only the claims + verdict are
    # stored, never bytes/imagery (§10). Fail-open: case accrual must never break a verdict (§4).
    case_store = getattr(request.app.state, "case_store", None)
    if case_id and case_store is not None and case_store.get(case_id) is not None:
        try:
            entities = ctx.shared.get("entities")
            if isinstance(entities, ExtractedEntities):
                case_store.add_document(
                    case_id,
                    label=(trust.doc_type or doc_type or "document"),
                    entities=entities,
                    verdict=trust.verdict.value,
                    now=_iso_now(),
                    evidence_pack=trust.model_dump(mode="json"),
                )
                bound.info("case.accrual", case_id=case_id)  # no applicant PII (§10)
        except Exception as exc:  # noqa: BLE001 — accrual must never break a verdict
            bound.warning("case.accrual.error", error=repr(exc))

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
# Auto-score once the buffer holds a full short motion sequence (~7 s at the 300 ms client cadence) —
# long enough for a cooperating user to read the instruction, get the document in frame, and perform
# the tilt. The client streams continuously and never has to ask for a score — the server decides when
# it has captured enough of the commanded motion to verify the active challenge. A client MAY also send
# ``{"type": "score"}`` to trigger early once they believe they've completed the motion (the "Verify
# now" control). DEFAULT — needs calibration against real capture timing.
_FRAMES_TO_AUTO_SCORE = 24
# Validity window of the issued challenge nonce, surfaced to the user as a live countdown AND actually
# enforced below as a time-based backstop (previously this was cosmetic only — a documented gap, see
# architecture/BUILD-MANIFEST.md — the frame-count trigger above fired first regardless of this value).
# It now also covers the case of slower-than-expected frame delivery: if elapsed time crosses this
# deadline before the frame count does, we score with whatever motion was captured rather than leaving
# a cooperating user's session hanging indefinitely.
_CHALLENGE_TTL_MS = 8_000
# Bounded in-session retries after a failed/unmet challenge attempt (CLAUDE.md §4 fail-closed still
# holds: retries are exhausted -> the last scored verdict stands, never silently upgraded). This is a
# UX/session-cost bound, NOT a security control — a photo-of-screen or pre-recorded clip fails
# ActiveChallengeAnalyzer's single-homography-consistency check on every independent attempt
# regardless of how many times it's retried, so bounding this cannot weaken the anti-replay property.
_MAX_CHALLENGE_RETRIES = 3

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

# Axis -> the human directional commands the homography axis check accepts. 'x' is a tilt about the
# horizontal axis (top/bottom edge toward the camera); 'y' is about the vertical axis (left/right
# edge toward the camera). NOTE: ActiveChallengeAnalyzer verifies the AXIS and the MAGNITUDE, not the
# sign — decomposeHomographyMat's rotation sign is ambiguous, so the direction is a human-facing
# instruction for clarity, NOT a separately verified factor. We never claim otherwise (CLAUDE.md §3).
_AXIS_KINDS: dict[str, tuple[str, ...]] = {
    "x": ("tilt-up", "tilt-down"),
    "y": ("tilt-left", "tilt-right"),
}
_KIND_INSTRUCTION = {
    "tilt-up": "Tilt the document's top edge toward the camera",
    "tilt-down": "Tilt the document's bottom edge toward the camera",
    "tilt-left": "Tilt the document's left edge toward the camera",
    "tilt-right": "Tilt the document's right edge toward the camera",
}


def _random_magnitude_deg() -> float:
    """A cryptographically-random commanded tilt magnitude in [MIN, MAX] at STEP resolution."""
    steps = round((_CHALLENGE_MAX_DEG - _CHALLENGE_MIN_DEG) / _CHALLENGE_STEP_DEG)
    return round(_CHALLENGE_MIN_DEG + _CHALLENGE_STEP_DEG * secrets.randbelow(steps + 1), 1)


def _issue_challenge() -> dict[str, Any]:
    """Mint the AUTHORITATIVE server-randomized 3D challenge (a time-bounded anti-replay nonce, §10).

    Stored at ``ctx.shared['challenge']`` and verified by :class:`ActiveChallengeAnalyzer` — an axis,
    a randomized magnitude, and a random nonce. The client-facing wire message (kind / instruction /
    countdown) is projected from this by :func:`_challenge_message`.
    """
    return {
        "axis": secrets.choice(_CHALLENGE_AXES),
        "magnitude_deg": _random_magnitude_deg(),
        "nonce": secrets.token_urlsafe(8),
    }


def _challenge_message(challenge: dict[str, Any], retries_remaining: int) -> dict[str, Any]:
    """Project the authoritative challenge into the client wire message (frontend ServerChallengeMessage).

    Carries a human ``kind`` / ``instruction`` plus the exact ``axis`` / ``magnitude_deg`` the
    cooperating client must physically perform. These are not secret from a legitimate client — the
    anti-replay strength is that the command is issued just-in-time and verified against the tracked
    document motion, not that its parameters are hidden. ``challenge_id`` is the nonce; the
    ``expires_at_ms`` deadline drives the on-screen countdown and is now server-enforced (see
    ``_CHALLENGE_TTL_MS``). ``retries_remaining`` tells the client how many more in-session attempts
    are available after this one. Kept field-for-field in lockstep with
    ``frontend/src/api/types.ts :: ServerChallengeMessage`` (CLAUDE.md §11).
    """
    axis = challenge["axis"]
    magnitude = float(challenge["magnitude_deg"])
    kind = secrets.choice(_AXIS_KINDS[axis])
    return {
        "type": "challenge",
        "challenge_id": challenge["nonce"],
        "kind": kind,
        "instruction": f"{_KIND_INSTRUCTION[kind]} about {magnitude:.0f}°, and hold steady",
        "axis": axis,
        "magnitude_deg": round(magnitude, 1),
        "expires_at_ms": int(time.time() * 1000) + _CHALLENGE_TTL_MS,
        "retries_remaining": retries_remaining,
    }


def _live_status_message(frames_buffered: int) -> dict[str, Any]:
    """An HONEST live per-tier status row (frontend ServerTierStatusMessage).

    This is NOT a verdict: it is a single ``NOT_EVALUATED`` capture-progress signal reflecting the
    real buffer state, so the console shows the pipeline is alive without ever fabricating a pass/fail
    on a frame that has not been scored (CLAUDE.md §3.1/§9). The real per-signal verdicts arrive only
    in the final ``result`` message.
    """
    return {
        "type": "tier_status",
        "signals": [
            {
                "name": "live_capture",
                "layer": 3,
                "producing_mode": "CAMERA",
                "status": "NOT_EVALUATED",
                "suspicion": None,
                "weight": 0.0,
                "reason": (
                    f"Capturing the commanded motion — {frames_buffered}/{_FRAMES_TO_AUTO_SCORE} "
                    f"frames buffered. Perform and hold the tilt; the active challenge is verified "
                    f"once enough motion is captured."
                ),
            }
        ],
    }


def _decode_jpeg_frame(payload: bytes):
    """Decode raw JPEG/PNG bytes into a BGR ndarray, or ``None`` if undecodable.

    Frames live only in memory and are never written to disk or logs (§10).
    """
    import cv2
    import numpy as np

    arr = np.frombuffer(payload, dtype=np.uint8)
    if arr.size == 0:
        return None
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)  # -> BGR ndarray or None


def _decode_base64_frame(b64: str):
    """Decode a base64 JPEG (the client's ``frame.jpeg_base64``; data-URL prefix already stripped)."""
    try:
        raw = base64.b64decode(b64, validate=True)
    except (ValueError, TypeError):
        return None
    return _decode_jpeg_frame(raw)


def _challenge_passed(trust: TrustScore) -> bool:
    """Did the active-challenge signal come back a clean, low-suspicion pass?

    Mirrors the analyzer's own PASS threshold (``challenge.py::_suspicion`` returns 0.05 on a clean
    match, >= 0.75 on any failure mode) — a missing/NOT_EVALUATED signal counts as not-passed so a
    fail-closed default applies when the document couldn't be tracked at all.
    """
    for sig in trust.signals:
        if sig.name == "active_challenge":
            return sig.suspicion is not None and sig.suspicion <= 0.1
    return False


@router.websocket("/ws/verify")
async def verify_camera(websocket: WebSocket) -> None:
    """Live camera verification: issue a random 3D challenge, accept streamed frames, score, return.

    Protocol — kept field-for-field in lockstep with ``frontend/src/api/types.ts`` (CLAUDE.md §11):
      * server → client on connect (and after each granted retry): ``{"type": "challenge",
        challenge_id, kind, instruction, axis, magnitude_deg, expires_at_ms, retries_remaining}``.
        ``expires_at_ms`` here is indicative only — the real TTL clock does not start until the
        client arms the attempt (below), so a user reading the instruction is never racing a
        deadline that started before they could act on it.
      * client → server: ``{"type": "hello", doc_type}``, then ``{"type": "start_attempt"}`` once
        the user is ready to begin (this is what actually starts the TTL clock and unblocks frame
        buffering — server replies ``{"type": "armed", "expires_at_ms": ...}`` with the real
        deadline), then ``{"type": "frame", jpeg_base64, ...}`` per ~300 ms window (JSON;
        ``jpeg_base64`` carries no data-URL prefix; raw binary frames are also accepted). A client
        MAY send ``{"type": "score"}`` to score early, or ``{"type": "retry"}`` after a failed
        attempt to request a fresh challenge on the same connection (bounded by
        ``_MAX_CHALLENGE_RETRIES`` — fail-closed once exhausted; a retried attempt again needs its
        own ``start_attempt`` before it's armed).
      * server → client: ``{"type": "tier_status", signals: [...]}`` per accepted frame (honest
        capture progress), then ``{"type": "result", trust_score: {...}}`` once enough of the
        commanded motion is captured, the TTL backstop elapses, or a client-requested early score.
        If the attempt failed AND a retry is still available, the connection stays open awaiting
        ``{"type": "retry"}`` instead of closing — the final ``result`` is the LAST attempt scored.
      * server → client on failure: ``{"type": "error", message}``.

    Frames received before arming, or after a failed attempt awaiting retry, are ignored and never
    buffered. Frames are dropped from the session the instant each attempt is scored (§10).
    """
    app = websocket.app
    session = app.state.sessions
    registry = app.state.registry
    ledger = app.state.ledger

    await websocket.accept()

    ctx: AnalysisContext = session.create(intake_mode=Mode.CAMERA, doc_type="live_capture")
    challenge = _issue_challenge()
    ctx.shared["challenge"] = challenge
    challenge_issued_at = time.monotonic()

    bound = log.bind(session_id=ctx.session_id, intake_mode="CAMERA")
    bound.info("verify.ws.connected", challenge_axis=challenge["axis"], nonce=challenge["nonce"])

    await websocket.send_json(_challenge_message(challenge, retries_remaining=_MAX_CHALLENGE_RETRIES))

    scored = False
    retry_count = 0
    awaiting_retry = False  # True once an attempt has failed and a retry is still on offer
    # The TTL clock does NOT start at challenge issue — a user reading the instruction and getting the
    # document into frame shouldn't be racing an invisible-until-too-late deadline. It starts only once
    # the client explicitly signals readiness (``{"type": "start_attempt"}``, the "Start attempt"
    # control). Frames received before arming are ignored, never buffered toward a verdict.
    armed = False
    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break

            # Resolve an inbound frame from either a JSON control message or a raw binary frame.
            frame = None
            text = message.get("text")
            data = message.get("bytes")
            if text is not None:
                try:
                    payload = json.loads(text)
                except (ValueError, TypeError):
                    continue  # ignore unparseable control text; keep the stream alive
                if not isinstance(payload, dict):
                    continue
                mtype = payload.get("type")
                if mtype == "hello":
                    continue  # the session was created on accept; nothing else to do
                if mtype == "retry":
                    if not awaiting_retry:
                        continue  # nothing to retry (never scored yet, or already passed)
                    if retry_count >= _MAX_CHALLENGE_RETRIES:
                        await websocket.send_json(
                            {"type": "error", "message": "no retries remaining"}
                        )
                        scored = True
                        break
                    retry_count += 1
                    awaiting_retry = False
                    armed = False  # the new attempt again waits for an explicit "start_attempt"
                    challenge = _issue_challenge()  # fresh axis/magnitude/nonce — never reused
                    ctx.shared["challenge"] = challenge
                    bound.info(
                        "verify.ws.retry", retry_count=retry_count, challenge_axis=challenge["axis"]
                    )
                    await websocket.send_json(
                        _challenge_message(
                            challenge, retries_remaining=_MAX_CHALLENGE_RETRIES - retry_count
                        )
                    )
                    continue
                if mtype == "start_attempt":
                    if armed or awaiting_retry:
                        continue  # already armed, or this attempt already failed — nothing to do
                    armed = True
                    challenge_issued_at = time.monotonic()  # the TTL clock starts NOW, not at issue
                    expires_at_ms = int(time.time() * 1000) + _CHALLENGE_TTL_MS
                    await websocket.send_json({"type": "armed", "expires_at_ms": expires_at_ms})
                    continue
                if mtype == "score":
                    if not armed or awaiting_retry:
                        continue  # nothing buffered yet, or this attempt already failed
                    trust = await _score_camera(websocket, session, registry, ledger, ctx, bound)
                    if trust is None:
                        continue
                    scored = True
                    if _challenge_passed(trust):
                        break
                    awaiting_retry = True
                    continue
                if mtype == "frame":
                    frame = _decode_base64_frame(payload.get("jpeg_base64") or "")
                else:
                    continue
            elif data is not None:
                frame = _decode_jpeg_frame(data)
            else:
                continue

            if not armed or awaiting_retry:
                continue  # not yet armed, or this attempt already failed — ignore, never buffer

            if frame is None:
                continue  # undecodable frame — skip silently, never count it toward the challenge

            # Backpressure: bound the buffer; drop the oldest rather than grow without limit (§7).
            if len(ctx.frames) >= _MAX_FRAMES_BUFFERED:
                ctx.frames.pop(0)
            session.add_frame(ctx.session_id, frame)

            elapsed_ms = (time.monotonic() - challenge_issued_at) * 1000
            # Score once enough of the commanded motion is captured, OR the TTL backstop elapses
            # (previously only the frame count mattered and the TTL was purely cosmetic — a
            # cooperating user on a slow connection could be scored on too little motion, or a
            # non-cooperating one force-rejected before the honest deadline actually passed).
            enough_frames = len(ctx.frames) >= _FRAMES_TO_AUTO_SCORE
            ttl_elapsed = elapsed_ms >= _CHALLENGE_TTL_MS and len(ctx.frames) >= _MIN_FRAMES_TO_SCORE
            if enough_frames or ttl_elapsed:
                trust = await _score_camera(websocket, session, registry, ledger, ctx, bound)
                if trust is None:
                    continue
                scored = True
                if _challenge_passed(trust):
                    break
                awaiting_retry = True
                continue

            await websocket.send_json(_live_status_message(len(ctx.frames)))

    except WebSocketDisconnect:
        bound.info("verify.ws.disconnected")
    except Exception as exc:  # noqa: BLE001 — a stream failure must never crash the server (§4)
        bound.warning("verify.ws.error", error=repr(exc))
        try:
            await websocket.send_json({"type": "error", "message": "stream error"})
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
) -> TrustScore | None:
    """Run camera-mode verification on the buffered frames, stream back the result, and return it."""
    if len(ctx.frames) < _MIN_FRAMES_TO_SCORE:
        await websocket.send_json(
            {"type": "error",
             "message": f"need >= {_MIN_FRAMES_TO_SCORE} frames to score (have {len(ctx.frames)})"}
        )
        return None

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
    return trust
