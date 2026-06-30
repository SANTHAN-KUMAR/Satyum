"""Tests for the registry privacy primitives (PROPOSAL-001 §6.2/§6.8).

Prove the constructions actually do what we claim — and refuse to overclaim:
  * salted pHash PRESERVES Hamming distance (so members can still match) while changing the value;
  * HMAC entity tokens are deterministic, pepper-dependent, kind-separated, and non-invertible.
"""

from __future__ import annotations

import pytest

from federation.tokens import (
    entity_token,
    entity_tokens,
    hamming_hex,
    normalise_entity,
    salt_phash,
)

_BASE = "f0e1d2c3b4a5968778695a4b3c2d1e0f0123456789abcdef0123456789abcdef"  # 64 hex = 256 bits
_SALT = "9a3c1f00deadbeefcafe1234567890abfedcba98765432100f1e2d3c4b5a6978"
_PEPPER = b"consortium-test-pepper"


def _flip_bits(hex_str: str, n: int) -> str:
    val = int(hex_str, 16)
    for i in range(n):
        val ^= (1 << i)
    return f"{val:064x}"


# --- salted pHash: Hamming-preserving, value-changing -------------------------------------------

def test_salt_changes_the_value():
    assert salt_phash(_BASE, _SALT) != _BASE  # non-zero salt actually de-correlates the stored value


def test_salt_preserves_hamming_distance():
    other = _flip_bits(_BASE, 5)  # 5 bits different
    assert hamming_hex(_BASE, other) == 5
    # XOR with a shared salt must not change the distance members rely on for matching.
    assert hamming_hex(salt_phash(_BASE, _SALT), salt_phash(other, _SALT)) == 5


def test_salt_is_deterministic_and_reversible_for_members():
    a = salt_phash(_BASE, _SALT)
    b = salt_phash(_BASE, _SALT)
    assert a == b                       # deterministic for a given salt
    assert salt_phash(a, _SALT) == _BASE  # XOR is its own inverse (members can recover the raw pHash)


def test_zero_salt_is_a_noop_documented_dev_default():
    assert salt_phash(_BASE, "00" * 32) == _BASE  # the dev default provides no de-correlation (honest)


def test_salt_rejects_malformed_length():
    with pytest.raises(ValueError):
        salt_phash("abcd", _SALT)
    with pytest.raises(ValueError):
        salt_phash(_BASE, "abcd")


# --- HMAC entity tokens --------------------------------------------------------------------------

def test_entity_token_is_deterministic_and_pepper_dependent():
    t1 = entity_token("pan", "ABCPK1234L", _PEPPER)
    t2 = entity_token("pan", "ABCPK1234L", _PEPPER)
    t3 = entity_token("pan", "ABCPK1234L", b"a-different-pepper")
    assert t1 == t2                     # same input + pepper -> same token
    assert t1 != t3                     # a different pepper yields a different token (pepper-gated)
    assert len(t1) == 64                # sha256 hexdigest


def test_entity_token_normalises_so_banks_agree():
    # The same identifier written differently must tokenise identically across banks (§11).
    assert entity_token("pan", "abcpk1234l", _PEPPER) == entity_token("pan", "ABCPK 1234 L", _PEPPER)
    assert entity_token("account", "1234-5678-90", _PEPPER) == entity_token("account", "1234567890", _PEPPER)


def test_entity_token_is_kind_separated():
    # A PAN and an account number with identical characters must NOT collide to the same token.
    assert entity_token("pan", "123456789", _PEPPER) != entity_token("account", "123456789", _PEPPER)


def test_entity_token_is_non_invertible_form():
    # The token reveals nothing structural about the input (no substring of the PAN appears).
    tok = entity_token("pan", "ABCPK1234L", _PEPPER)
    assert "ABCPK" not in tok and "1234" not in tok


def test_entity_tokens_skips_empty_values():
    tokens = entity_tokens({"pan": "ABCPK1234L", "account": "", "ifsc": None}, _PEPPER)  # type: ignore[dict-item]
    assert set(tokens) == {"pan"}


def test_normalise_entity_canonicalises():
    assert normalise_entity("pan", " abcpk1234l ") == "ABCPK1234L"
    assert normalise_entity("account", "1234 5678") == "12345678"
    assert normalise_entity("phone", "+91 98765 43210") == "9876543210"
