"""Tamper-evident audit ledger: prove that altering a past record breaks the hash chain."""

from __future__ import annotations

import dataclasses

from risk.audit import AuditLedger


def _ledger_with_three() -> AuditLedger:
    led = AuditLedger()
    led.record("2026-06-28T10:00:00Z", {"session_id": "a", "verdict": "APPROVED", "score": 90})
    led.record("2026-06-28T10:01:00Z", {"session_id": "b", "verdict": "REJECTED", "score": 5})
    led.record("2026-06-28T10:02:00Z", {"session_id": "c", "verdict": "REVIEW", "score": 70})
    return led


def test_intact_chain_verifies():
    ok, broken = _ledger_with_three().verify_chain()
    assert ok is True and broken is None


def test_mutating_a_payload_breaks_the_chain():
    led = _ledger_with_three()
    # Simulate an attacker with write access to the backing store forging the middle record:
    # pretend a REJECTED decision was APPROVED. (store.all() returns a defensive copy by design,
    # so we reach the real backing list — that is exactly the threat this control defends against.)
    backing = led._store._records  # type: ignore[attr-defined]
    backing[1] = dataclasses.replace(backing[1], payload={**backing[1].payload, "verdict": "APPROVED"})
    ok, broken = led.verify_chain()
    assert ok is False and broken == 1


def test_reordering_breaks_the_chain():
    led = _ledger_with_three()
    backing = led._store._records  # type: ignore[attr-defined]
    backing[1], backing[2] = backing[2], backing[1]
    ok, _ = led.verify_chain()
    assert ok is False
