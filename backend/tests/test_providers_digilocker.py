"""Discrimination + must-fail tests for the DigiLocker Path B provider (offline PAdES verify).

Path B is the no-partner hero: verify a DigiLocker-issued PDF's embedded CCA-chained PAdES signature
offline. These tests reuse the real signed-PDF builders and prove the provider separates:

  * a PDF signed by a CA we PIN            -> VERIFIED at source (+ issuer extracted for the badge);
  * a PDF signed by an attacker CA we DON'T -> INVALID (chain fails — tamper evidence);
  * a validly-signed PDF with bytes appended -> INVALID (coverage no longer whole-file);
  * an unsigned PDF                         -> ABSENT (route to fallback; never an auto-pass).

Also pins the honest gate: a live pull (no bytes) returns the Path A gate, never a fake pull.
The crypto stack (pyHanko) is required; skip cleanly if absent.
"""

from __future__ import annotations

import pytest

pytest.importorskip("cryptography")
pytest.importorskip("pyhanko")

from providers.contracts import ConsentArtifact, DocClass, DocRequest, SignatureStatus  # noqa: E402
from providers.digilocker import DigiLockerProvider  # noqa: E402
from tests.crypto_fixtures import (  # noqa: E402
    append_after_signature,
    make_ca,
    make_leaf,
    minimal_pdf,
    sign_pdf,
    write_anchor_dir,
)


def _consent() -> ConsentArtifact:
    return ConsentArtifact(
        consent_id="c-dl", purpose="loan_underwriting_document_verification",
        doc_class=DocClass.FINANCIAL_STATEMENT, granted_at="2026-06-30T00:00:00Z",
    )


def _req() -> DocRequest:
    return DocRequest(doc_class=DocClass.FINANCIAL_STATEMENT)


@pytest.fixture(scope="module")
def trusted_ca():
    return make_ca("Satyum CCA Test Root")


@pytest.fixture(scope="module")
def attacker_ca():
    return make_ca("Attacker Self-Signed CA")


@pytest.fixture
def anchor_dir(tmp_path, trusted_ca):
    _, ca_cert = trusted_ca
    return write_anchor_dir(tmp_path, ca_cert)


@pytest.fixture(scope="module")
def _pdf():
    return minimal_pdf()


@pytest.fixture(scope="module")
def signed_trusted(trusted_ca, _pdf):
    ca_key, ca_cert = trusted_ca
    leaf_key, leaf_cert = make_leaf(ca_key, ca_cert, "NeGD DigiLocker Issuer")
    return sign_pdf(_pdf, leaf_key, leaf_cert, ca_cert)


@pytest.fixture(scope="module")
def signed_attacker(attacker_ca, _pdf):
    ca_key, ca_cert = attacker_ca
    leaf_key, leaf_cert = make_leaf(ca_key, ca_cert, "NeGD DigiLocker Issuer")
    return sign_pdf(_pdf, leaf_key, leaf_cert, ca_cert)


# --- (a) positive control: pinned chain -> verified at source, issuer extracted -------------------

def test_path_b_trusted_pdf_is_verified_at_source(anchor_dir, signed_trusted):
    provider = DigiLockerProvider(anchor_dir=anchor_dir)
    res = provider.fetch(_consent(), _req(), payload=signed_trusted)

    assert res.signature_status == SignatureStatus.VERIFIED
    assert res.verified_at_source is True
    # The issuer is extracted from the verified signer cert for the "issued by X" trust badge (§4.1).
    assert res.issuer == "NeGD DigiLocker Issuer"
    assert "verified at source" in res.detail.lower()
    # The verified bytes are handed onward to feed the full verification core.
    assert res.signed_bytes == signed_trusted


# --- (b) MUST-FAIL: attacker CA not pinned -> chain fails -> INVALID -------------------------------

def test_path_b_attacker_pdf_is_invalid(anchor_dir, signed_attacker):
    provider = DigiLockerProvider(anchor_dir=anchor_dir)
    res = provider.fetch(_consent(), _req(), payload=signed_attacker)
    assert res.signature_status == SignatureStatus.INVALID
    assert res.verified_at_source is False
    assert res.signed_bytes is None  # never hand unverified bytes onward as "source-verified"


# --- (c) MUST-FAIL: appended bytes after the signature -> INVALID ---------------------------------

def test_path_b_appended_bytes_is_invalid(anchor_dir, signed_trusted):
    provider = DigiLockerProvider(anchor_dir=anchor_dir)
    tampered = append_after_signature(signed_trusted)
    res = provider.fetch(_consent(), _req(), payload=tampered)
    assert res.signature_status == SignatureStatus.INVALID
    assert res.verified_at_source is False


# --- (d) unsigned PDF -> ABSENT (route to fallback, never an auto-pass) ----------------------------

def test_path_b_unsigned_pdf_is_absent(anchor_dir, _pdf):
    provider = DigiLockerProvider(anchor_dir=anchor_dir)
    res = provider.fetch(_consent(), _req(), payload=_pdf)
    assert res.signature_status == SignatureStatus.ABSENT
    assert res.verified_at_source is False


# --- discrimination litmus (would FAIL against any constant) --------------------------------------

def test_verified_is_separated_from_invalid(anchor_dir, signed_trusted, signed_attacker):
    provider = DigiLockerProvider(anchor_dir=anchor_dir)
    good = provider.fetch(_consent(), _req(), payload=signed_trusted)
    bad = provider.fetch(_consent(), _req(), payload=signed_attacker)
    assert good.signature_status == SignatureStatus.VERIFIED
    assert bad.signature_status == SignatureStatus.INVALID


# --- fail-closed + honest gates -------------------------------------------------------------------

def test_no_pinned_anchors_fails_closed(tmp_path, signed_trusted):
    empty = tmp_path / "empty"
    empty.mkdir()
    provider = DigiLockerProvider(anchor_dir=str(empty))
    res = provider.fetch(_consent(), _req(), payload=signed_trusted)
    # Empty trust store -> cannot assert a chain -> NOT_VERIFIED (fail-closed), never VERIFIED.
    assert res.signature_status == SignatureStatus.NOT_VERIFIED
    assert res.verified_at_source is False


def test_live_pull_without_bytes_is_path_a_gated(anchor_dir):
    provider = DigiLockerProvider(anchor_dir=anchor_dir)
    res = provider.fetch(_consent(), _req(), payload=None)
    assert res.signature_status == SignatureStatus.NOT_VERIFIED
    assert res.gate and "Path A" in res.gate
    assert res.verified_at_source is False


def test_non_pdf_payload_is_absent(anchor_dir):
    provider = DigiLockerProvider(anchor_dir=anchor_dir)
    res = provider.fetch(_consent(), _req(), payload=b"\x89PNG\r\n\x1a\n not a pdf")
    assert res.signature_status == SignatureStatus.ABSENT
