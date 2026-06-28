"""Anti-replay entropy of the issued active-challenge command (app/routes/verify.py).

The active 3D challenge is only an anti-replay anchor if the COMMANDED motion is unpredictable: a
fixed public magnitude lets an attacker satisfy every session with one pre-recorded tilt clip, since
a clip within the homography tolerance of the (constant) command always passes. These tests prove
the commanded magnitude is genuinely randomized over a continuous range — would FAIL against the
prior single-constant issuance (which produced exactly one magnitude).
"""

from __future__ import annotations

from app.config import settings
from app.routes.verify import (
    _CHALLENGE_AXES,
    _CHALLENGE_MAX_DEG,
    _CHALLENGE_MIN_DEG,
    _issue_challenge,
    _random_magnitude_deg,
)


def test_commanded_magnitude_is_randomized_within_range():
    values = {_random_magnitude_deg() for _ in range(300)}
    # Not a single public constant — many distinct commanded magnitudes.
    assert len(values) > 10, "commanded magnitude must be randomized, not a fixed public constant"
    assert all(_CHALLENGE_MIN_DEG <= v <= _CHALLENGE_MAX_DEG for v in values)


def test_randomized_range_exceeds_twice_the_tolerance():
    """For randomization to actually cost an attacker, the magnitude span must exceed 2x the
    homography tolerance — otherwise a single clip at the midpoint covers the whole range."""
    span = _CHALLENGE_MAX_DEG - _CHALLENGE_MIN_DEG
    assert span > 2.0 * settings.challenge_homography_tol_deg


def test_issued_challenge_has_axis_magnitude_and_fresh_nonce():
    a, b = _issue_challenge(), _issue_challenge()
    for ch in (a, b):
        assert ch["axis"] in _CHALLENGE_AXES
        assert _CHALLENGE_MIN_DEG <= ch["magnitude_deg"] <= _CHALLENGE_MAX_DEG
        assert isinstance(ch["nonce"], str) and len(ch["nonce"]) >= 8
    # The nonce is a per-issue anti-replay token, so two issues do not collide.
    assert a["nonce"] != b["nonce"]
