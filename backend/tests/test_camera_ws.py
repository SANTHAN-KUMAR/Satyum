"""End-to-end WebSocket (/ws/verify) protocol + active-challenge discrimination tests.

These prove the LIVE-CAPTURE wire path works end to end — the exact integration that silently broke
when the frontend and backend WS protocols drifted out of lockstep (CLAUDE.md §11; §8 "integration-
test the waterfall end-to-end"). There was previously NO test crossing this boundary, which is why
the drift shipped. We drive the route exactly as the browser does: connect, read the server's
challenge, stream base64-JPEG ``frame`` messages, and read back ``tier_status`` + the final
``result``. Frames are synthetic (``capture_fixtures``) — never real imagery (§10).

Discrimination (the §3.2 core): a frame sequence that REALISES the commanded tilt yields a VALID
``active_challenge`` at low suspicion; a frozen replay (no commanded motion) yields a high-suspicion
"challenge unmet" verdict. No constant return satisfies both, so the pair fails against a constant.
"""

from __future__ import annotations

import base64

import cv2
import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.registry import AnalyzerRegistry
from app.routes.verify import _FRAMES_TO_AUTO_SCORE
from app.routes.verify import router as verify_router
from app.session import SessionManager
from capture.challenge import ActiveChallengeAnalyzer
from risk.audit import AuditLedger
from tests.capture_fixtures import challenge_sequence, static_challenge_sequence

# The ChallengeKind set the frontend guard (frontend/src/api/types.ts) accepts.
_CHALLENGE_KINDS = {
    "tilt-up", "tilt-down", "tilt-left", "tilt-right",
    "rotate-cw", "rotate-ccw", "move-closer", "move-away",
}


def _make_app() -> FastAPI:
    """The real WS route mounted on a camera registry holding the centerpiece challenge analyzer."""
    app = FastAPI()
    app.state.ledger = AuditLedger()
    registry = AnalyzerRegistry()
    registry.register(ActiveChallengeAnalyzer())  # the Tier-3 anti-replay signal under test
    app.state.registry = registry
    app.state.sessions = SessionManager()
    app.include_router(verify_router)
    return app


def _frame_message(frame: np.ndarray) -> dict:
    """Encode a BGR frame exactly as the browser does: base64 JPEG, no data-URL prefix."""
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
    assert ok, "failed to JPEG-encode the synthetic frame"
    return {
        "type": "frame",
        "challenge_id": None,
        "ts_ms": 0,
        "jpeg_base64": base64.b64encode(buf.tobytes()).decode("ascii"),
    }


def _stream_and_collect(ws, frames) -> dict:
    """Stream frames as the client would and return the server's final ``result`` message.

    The server replies with exactly one message per inbound frame — a ``tier_status`` (honest live
    progress), or the ``result`` on the frame that crosses the auto-score threshold — so we read one
    reply per send.
    """
    result = None
    for frame in frames:
        ws.send_json(_frame_message(frame))
        msg = ws.receive_json()
        if msg["type"] == "result":
            result = msg
            break
        assert msg["type"] == "tier_status", f"unexpected pre-score message: {msg['type']}"
        # The live progress row is honest: NOT_EVALUATED, never a fabricated pass/fail (§3.1/§9).
        assert msg["signals"][0]["status"] == "NOT_EVALUATED"
        assert msg["signals"][0]["suspicion"] is None
    assert result is not None, "server never returned a result after streaming the motion sequence"
    return result


def _active_challenge_signal(result_msg: dict) -> dict:
    signals = result_msg["trust_score"]["signals"]
    matches = [s for s in signals if s["name"] == "active_challenge"]
    assert matches, "active_challenge signal missing from the camera verdict"
    return matches[0]


def _arm(ws) -> dict:
    """Signal readiness for the CURRENT challenge — this is what starts the real TTL clock and
    unblocks frame buffering (frames sent before arming are honestly ignored, never scored, so a
    cooperating user is never racing a deadline that started before they could act on it)."""
    ws.send_json({"type": "start_attempt"})
    msg = ws.receive_json()
    assert msg["type"] == "armed"
    return msg


def _run(frames_for) -> tuple[dict, dict]:
    """Connect, read the challenge, arm the attempt, build the caller's frames, score, return.

    ``frames_for(axis, magnitude_deg)`` produces the streamed sequence; returns
    ``(active_challenge_signal, result_message)``.
    """
    client = TestClient(_make_app())
    with client.websocket_connect("/ws/verify") as ws:
        challenge = ws.receive_json()
        _arm(ws)
        frames = frames_for(challenge["axis"], float(challenge["magnitude_deg"]))
        result = _stream_and_collect(ws, frames)
    return _active_challenge_signal(result), result


# --- the protocol contract --------------------------------------------------------------------

def test_ws_challenge_message_matches_frontend_contract():
    """The connect challenge carries exactly the fields the frontend guard requires — proving the
    two sides are back in lockstep (the regression that broke the camera, §11)."""
    client = TestClient(_make_app())
    with client.websocket_connect("/ws/verify") as ws:
        msg = ws.receive_json()
    assert msg["type"] == "challenge"
    assert isinstance(msg["challenge_id"], str) and msg["challenge_id"]
    assert msg["kind"] in _CHALLENGE_KINDS
    assert isinstance(msg["instruction"], str) and msg["instruction"]
    assert isinstance(msg["expires_at_ms"], int)
    # The exact command a cooperating client must physically perform.
    assert msg["axis"] in ("x", "y")
    assert isinstance(msg["magnitude_deg"], (int, float))


# --- discrimination through the wire ----------------------------------------------------------

def test_ws_compliant_tilt_passes_active_challenge():
    """Streaming a sequence that REALISES the commanded tilt → VALID, low-suspicion live document."""
    sig, result = _run(
        lambda axis, mag: challenge_sequence(axis, mag, n=300, steps=_FRAMES_TO_AUTO_SCORE)
    )
    assert sig["status"] == "VALID", sig["reason"]
    assert sig["suspicion"] <= 0.1, sig["reason"]
    assert sig["measurements"]["axis_match"] is True
    assert sig["measurements"]["magnitude_match"] is True
    # The wired result is a real, complete TrustScore the console can render.
    ts = result["trust_score"]
    assert ts["intake_mode"] == "CAMERA"
    assert ts["tier_reached"] == "in-person-capture"
    assert isinstance(ts["trust_score"], (int, float))


def test_ws_static_replay_fails_active_challenge():
    """A frozen photo (no commanded motion) → high-suspicion 'challenge unmet', never an auto-pass."""
    sig, _ = _run(
        lambda _axis, _mag: static_challenge_sequence(n=300, steps=_FRAMES_TO_AUTO_SCORE)
    )
    assert sig["status"] == "VALID", sig["reason"]
    assert sig["suspicion"] >= 0.7, sig["reason"]
    assert sig["measurements"]["magnitude_match"] is False


def test_ws_compliant_beats_static_would_fail_against_a_constant():
    """The §3.2 litmus on the live path: the realised-tilt verdict must be strictly less suspicious
    than the frozen-replay verdict. A constant-return challenge analyzer fails this."""
    compliant, _ = _run(
        lambda axis, mag: challenge_sequence(axis, mag, n=300, steps=_FRAMES_TO_AUTO_SCORE)
    )
    static, _ = _run(
        lambda _axis, _mag: static_challenge_sequence(n=300, steps=_FRAMES_TO_AUTO_SCORE)
    )
    assert compliant["suspicion"] < static["suspicion"]


# --- in-session retry (a failed/unmet attempt gets a bounded chance to try again) --------------

def test_ws_frames_before_arming_are_ignored_not_scored():
    """Frames sent before `start_attempt` don't count toward anything — no ticking clock starts
    until the client explicitly says it's ready (the fix for "the timer started before I could act
    on the instruction")."""
    client = TestClient(_make_app())
    with client.websocket_connect("/ws/verify") as ws:
        challenge = ws.receive_json()
        # Send a few frames without arming first — these must be silently ignored (no tier_status,
        # no result), proving the buffer + TTL clock haven't started yet.
        for frame in static_challenge_sequence(n=300, steps=3):
            ws.send_json(_frame_message(frame))
        _arm(ws)
        # Now the SAME challenge is scored fresh from arming, not from the ignored pre-arm frames.
        frames = challenge_sequence(challenge["axis"], float(challenge["magnitude_deg"]), n=300,
                                     steps=_FRAMES_TO_AUTO_SCORE)
        result = _stream_and_collect(ws, frames)
        sig = _active_challenge_signal(result)
        assert sig["status"] == "VALID" and sig["suspicion"] <= 0.1, sig["reason"]


def test_ws_retry_issues_a_fresh_challenge_on_the_same_connection():
    """A failed attempt does NOT close the socket — the client can request a new challenge in place,
    and the server mints a genuinely fresh nonce (never reissues the same one, §10 anti-replay)."""
    client = TestClient(_make_app())
    with client.websocket_connect("/ws/verify") as ws:
        first = ws.receive_json()
        assert first["retries_remaining"] == 3
        _arm(ws)

        frames = static_challenge_sequence(n=300, steps=_FRAMES_TO_AUTO_SCORE)
        result = _stream_and_collect(ws, frames)
        assert _active_challenge_signal(result)["suspicion"] >= 0.7  # unmet -> failed

        ws.send_json({"type": "retry"})
        second = ws.receive_json()
        assert second["type"] == "challenge"
        assert second["challenge_id"] != first["challenge_id"]  # a fresh nonce, never reused
        assert second["retries_remaining"] == 2


def test_ws_retry_lets_a_corrected_attempt_pass_and_end_the_session():
    """After a retry, a compliant attempt against the NEW challenge's own axis/magnitude passes and
    the session concludes normally (no extra retry needed once genuinely satisfied)."""
    client = TestClient(_make_app())
    with client.websocket_connect("/ws/verify") as ws:
        ws.receive_json()  # first (failing) challenge — deliberately ignored
        _arm(ws)
        _stream_and_collect(ws, static_challenge_sequence(n=300, steps=_FRAMES_TO_AUTO_SCORE))

        ws.send_json({"type": "retry"})
        second = ws.receive_json()
        _arm(ws)

        compliant_frames = challenge_sequence(
            second["axis"], float(second["magnitude_deg"]), n=300, steps=_FRAMES_TO_AUTO_SCORE
        )
        result = _stream_and_collect(ws, compliant_frames)
        sig = _active_challenge_signal(result)
        assert sig["status"] == "VALID" and sig["suspicion"] <= 0.1, sig["reason"]


def test_ws_retries_are_bounded_and_the_final_failure_stands():
    """Exhausting every retry ends the session (fail-closed) rather than granting retries forever —
    bounded for session-cost, not security: a replay fails homography-consistency every attempt."""
    client = TestClient(_make_app())
    with client.websocket_connect("/ws/verify") as ws:
        ws.receive_json()
        for _ in range(3):  # consume all _MAX_CHALLENGE_RETRIES
            _arm(ws)
            _stream_and_collect(ws, static_challenge_sequence(n=300, steps=_FRAMES_TO_AUTO_SCORE))
            ws.send_json({"type": "retry"})
            msg = ws.receive_json()
            assert msg["type"] == "challenge"

        # One final failing attempt after the last granted retry — no retries left, session must end.
        _arm(ws)
        final_result = _stream_and_collect(
            ws, static_challenge_sequence(n=300, steps=_FRAMES_TO_AUTO_SCORE)
        )
        assert _active_challenge_signal(final_result)["suspicion"] >= 0.7

        ws.send_json({"type": "retry"})
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "no retries remaining" in msg["message"].lower()
