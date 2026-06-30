"""Tests for the shared fraud registry, the consult/report service, and the end-to-end demo beat.

Proves: set-membership matching (document + entity), PSI disclosure (only the intersection is
returned), the secure-aggregated "seen at N banks" count, and — the §10 demo beat 3 — a forged
document reported at "Bank A" surfacing as an advisory at "Bank B" that raises an otherwise-APPROVED
case to REVIEW through the firewall (never auto-declines).
"""

from __future__ import annotations

from app.contracts import Mode, TrustScore, Verdict
from federation.registry import FraudRegistry
from federation.service import consult_registry, report_fraud
from federation.tokens import entity_token, salt_phash
from forensics.entities import ExtractedEntities
from risk.engine import attach_advisory

_BASE = "f0e1d2c3b4a5968778695a4b3c2d1e0f0123456789abcdef0123456789abcdef"
_OTHER = "00112233445566778899aabbccddeeff00112233445566778899aabbccddeeff"
_SALT = "9a3c1f00deadbeefcafe1234567890abfedcba98765432100f1e2d3c4b5a6978"
_PEPPER = b"consortium-test-pepper"


def _flip_bits(hex_str: str, n: int) -> str:
    val = int(hex_str, 16)
    for i in range(n):
        val ^= (1 << i)
    return f"{val:064x}"


def _report(reg, phash=_BASE, *, bank="bankA", tokens=None, threat="forged_statement", label="caseA"):
    reg.report(
        label=label, threat_class=threat, bank_id=bank, timestamp="2026-06-18T00:00:00Z",
        salted_phash=salt_phash(phash, _SALT) if phash else None, entity_tokens=tokens or {},
    )


# --- registry membership matching ----------------------------------------------------------------

def test_exact_phash_resubmission_matches():
    reg = FraudRegistry()
    _report(reg)
    res = reg.query(salted_phashes=[salt_phash(_BASE, _SALT)], hamming_threshold=8)
    assert res.matched and res.best.phash_distance == 0


def test_near_duplicate_within_threshold_matches_beyond_does_not():
    reg = FraudRegistry()
    _report(reg)
    near = salt_phash(_flip_bits(_BASE, 6), _SALT)   # 6 bits -> within threshold 8
    far = salt_phash(_flip_bits(_BASE, 40), _SALT)   # 40 bits -> well beyond
    assert reg.query(salted_phashes=[near], hamming_threshold=8).matched is True
    assert reg.query(salted_phashes=[far], hamming_threshold=8).matched is False


def test_entity_token_reuse_matches_without_phash():
    reg = FraudRegistry()
    pan_tok = entity_token("pan", "ABCPK1234L", _PEPPER)
    _report(reg, phash=None, tokens={"pan": pan_tok})
    res = reg.query(entity_tokens={"pan": pan_tok}, hamming_threshold=8)
    assert res.matched and res.best.matched_token_kinds == ("pan",)


def test_psi_returns_only_the_intersection():
    """Two entries reported; a query matching one must return ONLY that one (never the other)."""
    reg = FraudRegistry()
    _report(reg, phash=_BASE, label="caseA")
    _report(reg, phash=_OTHER, label="caseB")
    res = reg.query(salted_phashes=[salt_phash(_BASE, _SALT)], hamming_threshold=8)
    assert len(res.matches) == 1
    assert res.matches[0].label == "caseA"


def test_seen_at_n_banks_is_aggregated():
    reg = FraudRegistry()
    for bank in ("bankA", "bankB", "bankC"):
        _report(reg, phash=_BASE, bank=bank)
    res = reg.query(salted_phashes=[salt_phash(_BASE, _SALT)], hamming_threshold=8)
    assert res.best.banks_seen == 3 and res.best.seen_count == 3
    assert reg.size() == 1  # deduped to a single entry


def test_no_match_returns_empty():
    reg = FraudRegistry()
    _report(reg, phash=_BASE)
    res = reg.query(salted_phashes=[salt_phash(_OTHER, _SALT)], hamming_threshold=8)
    assert res.matched is False


# --- service: report_fraud + consult_registry produce admissible advisories ----------------------

def test_consult_emits_advisory_on_match():
    reg = FraudRegistry()
    report_fraud(
        reg, phash_hex=_BASE, entities=None, threat_class="forged_statement",
        label="caseA", bank_id="bankA", timestamp="2026-06-18T00:00:00Z",
        salt_hex=_SALT, pepper=_PEPPER,
    )
    advisories = consult_registry(
        reg, phash_hex=_flip_bits(_BASE, 3), entities=None,
        salt_hex=_SALT, pepper=_PEPPER, hamming_threshold=8,
    )
    assert len(advisories) == 1
    adv = advisories[0]
    assert adv.source == "fraud_registry"
    assert adv.explanation.strip()                    # mandatory, non-empty (no opaque score)
    assert adv.suspicion >= 0.5                        # a registry hit reliably warrants human review


def test_consult_no_match_is_empty_fail_open():
    reg = FraudRegistry()
    report_fraud(
        reg, phash_hex=_BASE, entities=None, threat_class="forged_statement",
        label="caseA", bank_id="bankA", timestamp="t", salt_hex=_SALT, pepper=_PEPPER,
    )
    advisories = consult_registry(
        reg, phash_hex=_OTHER, entities=None, salt_hex=_SALT, pepper=_PEPPER, hamming_threshold=8,
    )
    assert advisories == []


def test_consult_matches_on_entity_reuse():
    reg = FraudRegistry()
    ent = ExtractedEntities(pan="ABCPK1234L", account_number="123456789")
    report_fraud(
        reg, phash_hex=None, entities=ent, threat_class="pan_ring",
        label="caseA", bank_id="bankA", timestamp="t", salt_hex=_SALT, pepper=_PEPPER,
    )
    # A different document (no pHash) but the SAME PAN reused -> entity-reuse hit.
    advisories = consult_registry(
        reg, phash_hex=None, entities=ExtractedEntities(pan="ABCPK1234L"),
        salt_hex=_SALT, pepper=_PEPPER, hamming_threshold=8,
    )
    assert len(advisories) == 1
    assert "pan" in advisories[0].measurements["matched_token_kinds"]


# --- end-to-end: demo beat 3 — Bank A's forgery surfaces at Bank B and raises REVIEW (never auto-decline)

def test_demo_beat_resubmission_raises_review_through_firewall():
    reg = FraudRegistry()
    # Bank A confirms a forged statement and reports its fingerprint.
    report_fraud(
        reg, phash_hex=_BASE, entities=ExtractedEntities(pan="ABCPK1234L"),
        threat_class="forged_statement", label="bankA:LN-2031", bank_id="bankA",
        timestamp="2026-06-18T00:00:00Z", salt_hex=_SALT, pepper=_PEPPER,
    )
    # Bank B verifies a near-identical document; deterministically it would be APPROVED.
    bankB_trust = TrustScore(
        session_id="bankB:LN-4812", intake_mode=Mode.FILE, trust_score=90.0,
        verdict=Verdict.APPROVED, tier_reached="forensic-fallback",
    )
    advisories = consult_registry(
        reg, phash_hex=_flip_bits(_BASE, 2), entities=ExtractedEntities(pan="ABCPK1234L"),
        salt_hex=_SALT, pepper=_PEPPER, hamming_threshold=8,
    )
    out = attach_advisory(bankB_trust, advisories)

    # The network finding raised it to a human — but never auto-declined and never touched the score.
    assert out.verdict == Verdict.REVIEW
    assert out.trust_score == 90.0
    assert out.deterministic_subscore == 90.0
    assert out.evidence_pack["network_intelligence"][0]["source"] == "fraud_registry"
    assert "not a verdict" in out.evidence_pack["network_intelligence"][0]["note"]
