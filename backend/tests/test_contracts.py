"""Contract invariants: a VALID signal must carry suspicion; others must not. These guard against
analyzers fabricating a pass or returning malformed signals."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.contracts import LayerSignal, Mode, SignalStatus


def test_valid_requires_suspicion():
    with pytest.raises(ValidationError):
        LayerSignal(name="x", layer=3, mode=Mode.FILE, status=SignalStatus.VALID, suspicion=None)


def test_not_evaluated_forbids_suspicion():
    with pytest.raises(ValidationError):
        LayerSignal(name="x", layer=3, mode=Mode.FILE,
                    status=SignalStatus.NOT_EVALUATED, suspicion=0.5)


def test_suspicion_must_be_in_unit_interval():
    with pytest.raises(ValidationError):
        LayerSignal.valid("x", 3, Mode.FILE, suspicion=1.5, weight=0.1, reason="r")


def test_constructors_set_producing_mode():
    s = LayerSignal.valid("x", 3, Mode.CAMERA, 0.2, 0.1, "r")
    assert s.producing_mode == Mode.CAMERA
    ne = LayerSignal.not_evaluated("y", 3, Mode.FILE, "gated")
    assert ne.suspicion is None and ne.producing_mode == Mode.FILE
