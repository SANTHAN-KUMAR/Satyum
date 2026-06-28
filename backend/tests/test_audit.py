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


# --- head-anchor: catching what a bare unanchored chain cannot (truncation / re-forge) ----------

def test_head_anchor_detects_tail_truncation():
    """A bare chain stays internally consistent after its most-recent records are dropped — an
    unanchored verify cannot see the loss. A previously-captured head() anchor detects it."""
    led = _ledger_with_three()
    anchor = led.head()  # (3, last_hash)
    assert anchor[0] == 3
    backing = led._store._records  # type: ignore[attr-defined]
    del backing[2]  # truncate the tail (drop the most recent decision)

    # Unanchored: the surviving 2-record chain re-derives cleanly — the gap is INVISIBLE.
    assert led.verify_chain() == (True, None)
    # Anchored: the loss is caught.
    ok, broken = led.verify_chain(anchor=anchor)
    assert ok is False and broken == 2


def test_head_anchor_detects_wholesale_reforge():
    """An attacker who rewrites a record AND recomputes every forward hash yields a chain that is
    internally consistent (the documented limitation: unanchored verify passes). The head anchor,
    captured before the forge, detects that the anchored history diverged."""
    led = _ledger_with_three()
    anchor = led.head()  # captured BEFORE the forge
    original = led.records()

    forged = AuditLedger()
    forged.record(original[0].timestamp, original[0].payload)
    forged.record(original[1].timestamp, {**original[1].payload, "verdict": "APPROVED"})  # the lie
    forged.record(original[2].timestamp, original[2].payload)

    # The re-forged chain passes an UNANCHORED verify — exactly the gap the anchor closes.
    assert forged.verify_chain() == (True, None)
    # The pre-forge anchor no longer matches the re-forged head -> detected.
    ok, broken = forged.verify_chain(anchor=anchor)
    assert ok is False and broken == anchor[0] - 1


def test_anchor_on_legitimately_extended_chain_passes():
    """Appending NEW records after the anchor is legitimate — the anchored prefix is unchanged, so a
    sound chain plus a valid anchor verifies. Proves the anchor doesn't false-positive on growth."""
    led = _ledger_with_three()
    anchor = led.head()
    led.record("2026-06-28T10:03:00Z", {"session_id": "d", "verdict": "APPROVED", "score": 88})
    ok, broken = led.verify_chain(anchor=anchor)
    assert ok is True and broken is None
