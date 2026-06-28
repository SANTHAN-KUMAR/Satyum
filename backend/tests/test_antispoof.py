"""Discrimination tests for the three Tier-3 anti-spoof votes.

Each test fails against a constant return: the moire vote must score a periodic screen HIGHER than
a diffuse page; the specular vote must score a concentrated glare hotspot HIGHER than matte paper;
the temporal vote must score a static/looped buffer HIGHER than live aperiodic motion. No constant
satisfies these orderings. Each vote carries only its config weight — never a hard gate — and is
NOT_EVALUATED when frames are insufficient.
"""

from __future__ import annotations

import cv2

from app.config import settings
from app.contracts import AnalysisContext, Mode, SignalStatus
from capture.antispoof import (
    SpecularGlareAnalyzer,
    SpectralMoireAnalyzer,
    TemporalEntropyAnalyzer,
    loop_autocorrelation,
    moire_peak_prominence,
    specular_glare_stats,
    temporal_variance,
)
from tests.capture_fixtures import (
    diffuse_gray,
    diffuse_page,
    live_frames,
    looped_frames,
    screen_glare_page,
    screen_grid_gray,
    static_frames,
)


def _ctx_frame(frame) -> AnalysisContext:
    ctx = AnalysisContext(session_id="t", intake_mode=Mode.CAMERA)
    ctx.frames.append(frame)
    return ctx


def _ctx_frames(frames) -> AnalysisContext:
    ctx = AnalysisContext(session_id="t", intake_mode=Mode.CAMERA)
    ctx.frames.extend(frames)
    return ctx


def _susp(signal) -> float:
    """Assert a VALID signal carries a real suspicion and return it (type-safe comparisons)."""
    assert signal.status == SignalStatus.VALID
    assert signal.suspicion is not None
    return signal.suspicion


# ============================================================================================
#  Spectral moire
# ============================================================================================

def test_moire_prominence_separates_screen_from_paper():
    paper = moire_peak_prominence(diffuse_gray())
    screen = moire_peak_prominence(screen_grid_gray())
    # The periodic screen carrier must produce a far more prominent off-DC peak than diffuse paper.
    assert screen > paper
    assert screen > 10 * max(paper, 1.0)


def test_moire_analyzer_flags_screen_not_paper():
    az = SpectralMoireAnalyzer()
    paper_bgr = cv2.cvtColor(diffuse_gray(), cv2.COLOR_GRAY2BGR)
    screen_bgr = cv2.cvtColor(screen_grid_gray(), cv2.COLOR_GRAY2BGR)
    paper = _susp(az.analyze(_ctx_frame(paper_bgr)))
    screen = _susp(az.analyze(_ctx_frame(screen_bgr)))
    # the discriminating property: the screen is more suspicious than the page
    assert screen > paper
    assert paper < 0.5 and screen > 0.5


def test_moire_is_a_weighted_vote_not_a_gate():
    az = SpectralMoireAnalyzer()
    sig = az.analyze(_ctx_frame(cv2.cvtColor(screen_grid_gray(), cv2.COLOR_GRAY2BGR)))
    assert sig.weight == settings.weight_antispoof_spectral
    assert 0.0 < sig.weight < 1.0  # a vote, never a standalone decision


def test_moire_uses_rectified_crop_when_present():
    az = SpectralMoireAnalyzer()
    ctx = AnalysisContext(session_id="t", intake_mode=Mode.CAMERA)
    ctx.frames.append(cv2.cvtColor(diffuse_gray(), cv2.COLOR_GRAY2BGR))  # diffuse raw frame
    ctx.shared["rectified"] = cv2.cvtColor(screen_grid_gray(), cv2.COLOR_GRAY2BGR)  # screen crop
    sig = az.analyze(ctx)
    # it must analyze the published rectified crop (screen), so it should flag it
    assert _susp(sig) > 0.5


# ============================================================================================
#  Specular glare
# ============================================================================================

def test_specular_stats_separate_glare_from_matte():
    _clip_p, conc_p, hot_p = specular_glare_stats(diffuse_page())
    _clip_g, conc_g, hot_g = specular_glare_stats(screen_glare_page())
    # matte paper has no concentrated clipped hotspot; the glare image does
    assert hot_g > hot_p
    assert conc_g > conc_p


def test_specular_analyzer_flags_glare_not_matte():
    az = SpecularGlareAnalyzer()
    matte = _susp(az.analyze(_ctx_frame(diffuse_page())))
    glare = _susp(az.analyze(_ctx_frame(screen_glare_page())))
    assert glare > matte
    assert matte == 0.0 and glare > 0.0


def test_specular_is_a_weighted_vote():
    az = SpecularGlareAnalyzer()
    sig = az.analyze(_ctx_frame(screen_glare_page()))
    assert sig.weight == settings.weight_antispoof_specular
    assert 0.0 < sig.weight < 1.0


# ============================================================================================
#  Temporal entropy
# ============================================================================================

def test_temporal_variance_separates_static_from_live():
    static_var = temporal_variance(static_frames())
    live_var = temporal_variance(live_frames())
    assert static_var < 1.0  # frozen
    assert live_var > 5.0  # moving
    assert live_var > static_var


def test_loop_autocorrelation_separates_loop_from_live():
    live_ac = loop_autocorrelation(live_frames())
    loop_ac = loop_autocorrelation(looped_frames())
    # a periodic replay loop autocorrelates strongly; aperiodic live motion does not
    assert loop_ac > live_ac
    assert loop_ac > 0.5


def test_temporal_analyzer_static_is_most_suspicious():
    az = TemporalEntropyAnalyzer()
    static = _susp(az.analyze(_ctx_frames(static_frames())))
    live = _susp(az.analyze(_ctx_frames(live_frames())))
    # a static photo of a document is maximally suspicious; live motion is not
    assert static > live
    assert static >= 0.9 and live < 0.5


def test_temporal_analyzer_loop_is_flagged():
    az = TemporalEntropyAnalyzer()
    loop = _susp(az.analyze(_ctx_frames(looped_frames())))
    live = _susp(az.analyze(_ctx_frames(live_frames())))
    assert loop > live  # replay loop is flagged above live


def test_temporal_insufficient_frames_is_not_evaluated():
    az = TemporalEntropyAnalyzer()
    ctx = _ctx_frames(static_frames(count=2))  # below the minimum
    assert az.applicable(ctx) is False
    sig = az.analyze(ctx)
    assert sig.status == SignalStatus.NOT_EVALUATED
    assert sig.suspicion is None


# ============================================================================================
#  Cross-cutting: mode tagging + fail-closed
# ============================================================================================

def test_all_votes_produce_camera_mode():
    frame = cv2.cvtColor(screen_grid_gray(), cv2.COLOR_GRAY2BGR)
    for az, ctx in (
        (SpectralMoireAnalyzer(), _ctx_frame(frame)),
        (SpecularGlareAnalyzer(), _ctx_frame(screen_glare_page())),
        (TemporalEntropyAnalyzer(), _ctx_frames(live_frames())),
    ):
        sig = az.analyze(ctx)
        assert sig.producing_mode == Mode.CAMERA


def test_temporal_shape_inconsistent_frames_not_evaluated():
    az = TemporalEntropyAnalyzer()
    frames = live_frames(n=64, count=6)
    frames.append(cv2.cvtColor(diffuse_gray(n=100), cv2.COLOR_GRAY2BGR))  # different shape
    sig = az.analyze(_ctx_frames(frames))
    # heterogeneous shapes: it must still not crash; either it analyzes the consistent subset or
    # honestly reports not-evaluated — never raises.
    assert sig.status in (SignalStatus.VALID, SignalStatus.NOT_EVALUATED)
