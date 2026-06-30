"""Discrimination + must-fail tests for the Account Aggregator FIP-signature verifier.

These prove the verifier actually separates a genuine FIP signature from a forged / wrong-signer /
tampered one — signing with a key we PIN must verify; signing with a key we do NOT pin, or tampering
the payload after signing, must FAIL (CLAUDE.md §3.2). No constant return can satisfy all cases.

The crypto stack is required; skip cleanly if absent (never a false green).
"""

from __future__ import annotations

import pytest

pytest.importorskip("cryptography")

from providers.account_aggregator import (  # noqa: E402
    AccountAggregatorProvider,
    verify_detached_jws,
)
from providers.contracts import ConsentArtifact, DocClass, DocRequest, SignatureStatus  # noqa: E402
from tests.crypto_fixtures import (  # noqa: E402
    aa_envelope,
    gen_ec_key,
    gen_rsa_key,
    sign_detached_jws,
    write_fip_key_dir,
)

_FI = {"account": "XXXX1234", "balance": "152340.55", "freshness": "2026-06-30T09:00:00Z",
       "transactions": [{"amt": "5000", "type": "CREDIT"}]}


def _consent() -> ConsentArtifact:
    return ConsentArtifact(
        consent_id="c-aa", purpose="loan_underwriting_document_verification",
        doc_class=DocClass.FINANCIAL_STATEMENT, granted_at="2026-06-30T00:00:00Z",
    )


def _req() -> DocRequest:
    return DocRequest(doc_class=DocClass.FINANCIAL_STATEMENT)


# --- unit: the detached-JWS verifier itself (RS256 / PS256 / ES256) -------------------------------

@pytest.mark.parametrize("alg,keygen", [
    ("RS256", gen_rsa_key), ("PS256", gen_rsa_key), ("ES256", gen_ec_key),
])
def test_detached_jws_roundtrip_verifies(alg, keygen):
    key = keygen()
    payload = b'{"hello":"world","n":1}'
    jws = sign_detached_jws(payload, key, alg)
    ok, info = verify_detached_jws(jws, payload, key.public_key())
    assert ok is True and info["alg"] == alg


@pytest.mark.parametrize("alg,keygen", [
    ("RS256", gen_rsa_key), ("PS256", gen_rsa_key), ("ES256", gen_ec_key),
])
def test_detached_jws_tampered_payload_fails(alg, keygen):
    key = keygen()
    payload = b'{"amount":"5000"}'
    jws = sign_detached_jws(payload, key, alg)
    ok, _ = verify_detached_jws(jws, b'{"amount":"9000"}', key.public_key())  # edited after signing
    assert ok is False, "a payload edited after signing must not verify"


@pytest.mark.parametrize("alg,keygen", [
    ("RS256", gen_rsa_key), ("ES256", gen_ec_key),
])
def test_detached_jws_wrong_key_fails(alg, keygen):
    signer, other = keygen(), keygen()
    payload = b'{"x":1}'
    jws = sign_detached_jws(payload, signer, alg)
    ok, _ = verify_detached_jws(jws, payload, other.public_key())  # not the signing key
    assert ok is False, "a signature from a different key must not verify"


def test_attached_jws_is_rejected():
    key = gen_rsa_key()
    # A non-detached (middle segment non-empty) JWS is ambiguous about what was signed -> rejected.
    bad = "eyJhbGciOiJSUzI1NiJ9.eyJwYXlsb2FkIjoxfQ.AAAA"
    ok, info = verify_detached_jws(bad, b"{}", key.public_key())
    assert ok is False and "DETACHED" in info["error"]


# --- provider: pinned vs attacker FIP key (the must-fail battery) ---------------------------------

def test_provider_verifies_against_pinned_fip_key(tmp_path):
    fip_key = gen_rsa_key()
    key_dir = write_fip_key_dir(tmp_path, fip_key.public_key())
    provider = AccountAggregatorProvider(fip_key_dir=key_dir)

    envelope = aa_envelope(_FI, fip_key, alg="RS256", fip_id="SETU-FIP")
    res = provider.fetch(_consent(), _req(), payload=envelope)

    assert res.signature_status == SignatureStatus.VERIFIED
    assert res.verified_at_source is True
    assert res.issuer == "SETU-FIP"
    assert res.freshness_ts == "2026-06-30T09:00:00Z"  # the AA-unique freshness signal, surfaced
    # The signature is real; only production live-pull (freshness) is gated -> gate present, honest.
    assert res.gate and "live-pull" in res.gate
    assert res.measurements["jws_alg"] == "RS256"


def test_provider_rejects_signature_from_unpinned_attacker_key(tmp_path):
    """MUST-FAIL: a FIP-signed-looking payload signed by a key we do NOT pin is INVALID, not verified."""
    pinned, attacker = gen_rsa_key(), gen_rsa_key()
    key_dir = write_fip_key_dir(tmp_path, pinned.public_key())  # pin ONLY the genuine FIP key
    provider = AccountAggregatorProvider(fip_key_dir=key_dir)

    forged = aa_envelope(_FI, attacker, alg="RS256", fip_id="SETU-FIP")  # signed by the attacker
    res = provider.fetch(_consent(), _req(), payload=forged)

    assert res.signature_status == SignatureStatus.INVALID
    assert res.verified_at_source is False


def test_provider_no_pinned_keys_fails_closed(tmp_path):
    """With an empty FIP-key store the provider cannot assert a signer -> NOT_VERIFIED (never a pass)."""
    empty = tmp_path / "empty_fip"
    empty.mkdir()
    provider = AccountAggregatorProvider(fip_key_dir=str(empty))
    res = provider.fetch(_consent(), _req(), payload=aa_envelope(_FI, gen_rsa_key()))
    assert res.signature_status == SignatureStatus.NOT_VERIFIED
    assert res.verified_at_source is False


def test_provider_live_pull_without_payload_is_gated(tmp_path):
    provider = AccountAggregatorProvider(fip_key_dir=write_fip_key_dir(tmp_path, gen_rsa_key().public_key()))
    res = provider.fetch(_consent(), _req(), payload=None)  # live pull requested
    assert res.signature_status == SignatureStatus.NOT_VERIFIED
    assert res.gate and "FIU" in res.gate
    assert "never presented as live" in res.gate.lower()


def test_provider_verified_is_separated_from_invalid(tmp_path):
    """The §3.2 litmus encoded: genuine -> VERIFIED, attacker -> INVALID; no constant satisfies both."""
    pinned, attacker = gen_rsa_key(), gen_rsa_key()
    provider = AccountAggregatorProvider(fip_key_dir=write_fip_key_dir(tmp_path, pinned.public_key()))
    good = provider.fetch(_consent(), _req(), payload=aa_envelope(_FI, pinned))
    bad = provider.fetch(_consent(), _req(), payload=aa_envelope(_FI, attacker))
    assert good.signature_status == SignatureStatus.VERIFIED
    assert bad.signature_status == SignatureStatus.INVALID
