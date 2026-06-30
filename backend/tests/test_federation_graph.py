"""Tests for the cross-bank entity graph + ring detection (PROPOSAL-001 §6.1 / §6.3.2).

Proves the §6.1 worked example (five banks each holding one weak signal → a coherent ring only once
pooled) AND the crucial discrimination that keeps it honest: a shared *employer* alone (real
colleagues) is NOT a ring, while a shared *payout account* / device is. No constant could satisfy both.
"""

from __future__ import annotations

from federation.graph import ApplicationNode, EntityGraph
from federation.service import add_application, ring_advisories_for

_PEPPER = b"ring-test-pepper"


def _graph_with(apps: list[tuple[str, str, dict[str, str]]]) -> EntityGraph:
    g = EntityGraph()
    for case_id, bank, identifiers in apps:
        add_application(g, case_id=case_id, bank_id=bank, identifiers=identifiers, pepper=_PEPPER)
    return g


# --- the §6.1 worked example: five banks, pooled, reveal one ring --------------------------------

def test_worked_example_ring_is_detected_only_when_pooled():
    # Five applications at five banks, all sharing a payout account + device + employer ("Company X").
    shared = {"payout_account": "50100123456789", "device": "DV-FP-AA11", "employer": "COMPANY X PVT"}
    g = _graph_with([
        ("canara:LN-1", "canara", shared),
        ("sbi:LN-2", "sbi", shared),
        ("hdfc:LN-3", "hdfc", shared),
        ("icici:LN-4", "icici", shared),
        ("union:LN-5", "union", shared),
    ])
    rings = g.detect_rings(min_ring_size=3, ring_weight_threshold=1.0)
    assert len(rings) == 1
    ring = rings[0]
    assert len(ring.members) == 5
    assert len(ring.banks) == 5
    assert set(ring.shared_identifiers) == {"payout_account", "device", "employer"}
    assert "applications across 5 bank(s)" in ring.explanation


def test_shared_employer_alone_is_not_a_ring():
    """Real colleagues share an employer — that alone must NOT read as a ring (weight 0.4 < 1.0)."""
    g = _graph_with([
        ("a:1", "a", {"employer": "BIG CORP"}),
        ("b:2", "b", {"employer": "BIG CORP"}),
        ("c:3", "c", {"employer": "BIG CORP"}),
        ("d:4", "d", {"employer": "BIG CORP"}),
    ])
    assert g.detect_rings() == []


def test_shared_payout_account_alone_is_a_ring():
    """One payout account receiving every disbursement IS dispositive (weight 1.0)."""
    g = _graph_with([
        ("a:1", "a", {"payout_account": "999000111222"}),
        ("b:2", "b", {"payout_account": "999000111222"}),
        ("c:3", "c", {"payout_account": "999000111222"}),
    ])
    rings = g.detect_rings()
    assert len(rings) == 1 and rings[0].shared_identifiers == {"payout_account": 3}


def test_below_min_ring_size_is_not_flagged():
    g = _graph_with([
        ("a:1", "a", {"payout_account": "999000111222"}),
        ("b:2", "b", {"payout_account": "999000111222"}),
    ])
    assert g.detect_rings(min_ring_size=3) == []


def test_unrelated_applications_form_no_ring():
    g = _graph_with([
        ("a:1", "a", {"payout_account": "111", "device": "DV-1"}),
        ("b:2", "b", {"payout_account": "222", "device": "DV-2"}),
        ("c:3", "c", {"payout_account": "333", "device": "DV-3"}),
    ])
    assert g.detect_rings() == []


def test_two_weak_shared_signals_sum_into_a_ring():
    # Employer (0.4) + device (0.9) = 1.3 >= 1.0 -> a ring, exactly the §6.1 pooling argument.
    shared = {"employer": "COMPANY X", "device": "DV-FP-ZZ"}
    g = _graph_with([("a:1", "a", shared), ("b:2", "b", shared), ("c:3", "c", shared)])
    rings = g.detect_rings()
    assert len(rings) == 1
    assert set(rings[0].shared_identifiers) == {"employer", "device"}


def test_nodes_hold_tokens_not_raw_identifiers():
    g = EntityGraph()
    add_application(g, case_id="a:1", bank_id="a",
                    identifiers={"payout_account": "50100123456789"}, pepper=_PEPPER)
    node = g._nodes["a:1"]  # noqa: SLF001 — white-box privacy assertion
    assert "50100123456789" not in node.linkage_tokens.get("payout_account", "")
    assert len(node.linkage_tokens["payout_account"]) == 64  # HMAC-SHA256 hex


# --- service: per-case ring advisory -------------------------------------------------------------

def test_ring_advisory_for_a_member_case():
    shared = {"payout_account": "999000111222", "device": "DV-X"}
    g = _graph_with([("a:1", "a", shared), ("b:2", "b", shared), ("c:3", "c", shared)])
    advisories = ring_advisories_for(g, "a:1")
    assert len(advisories) == 1
    adv = advisories[0]
    assert adv.source == "ring_evidence"
    assert adv.suspicion >= 0.5 and adv.explanation.strip()
    assert "a:1" in adv.measurements["members"]


def test_no_ring_advisory_for_isolated_case():
    g = _graph_with([("lonely:1", "a", {"payout_account": "uniqueACC"})])
    assert ring_advisories_for(g, "lonely:1") == []
