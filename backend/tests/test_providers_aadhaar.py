"""Discrimination + must-fail tests for the Aadhaar offline e-KYC XML provider (real XMLDSig).

Proves the provider separates a genuine UIDAI-signed XML from a tampered / wrong-signer one: signing
with the key we PIN as UIDAI verifies; tampering the XML after signing, or signing with a key we do
NOT pin, fails (CLAUDE.md §3.2). The XML stack (signxml/lxml) is required; skip cleanly if absent.
"""

from __future__ import annotations

import io
import zipfile

import pytest

pytest.importorskip("signxml")
pytest.importorskip("lxml")

from cryptography.hazmat.primitives import serialization  # noqa: E402
from lxml import etree  # noqa: E402
from signxml import XMLSigner, methods  # noqa: E402

from providers.aadhaar import AadhaarOfflineProvider  # noqa: E402
from providers.contracts import ConsentArtifact, DocClass, DocRequest, SignatureStatus  # noqa: E402
from tests.crypto_fixtures import make_ca  # noqa: E402


def _consent() -> ConsentArtifact:
    return ConsentArtifact(consent_id="c-aadhaar", purpose="kyc", doc_class=DocClass.IDENTITY,
                           granted_at="2026-06-30T00:00:00Z")


def _req(share_code: str | None = None) -> DocRequest:
    return DocRequest(doc_class=DocClass.IDENTITY, share_code=share_code)


def _aadhaar_xml() -> etree._Element:
    root = etree.Element("OfflinePaperlessKyc")
    root.set("referenceId", "9012202606301200000")
    ud = etree.SubElement(root, "UidData")
    etree.SubElement(ud, "Poi", name="Asha Kumar", dob="01-01-1990", gender="F")
    etree.SubElement(ud, "Poa", state="Karnataka", dist="Bengaluru")
    return root


def _sign(root: etree._Element, key, cert) -> bytes:
    key_pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption())
    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode("ascii")
    signed = XMLSigner(method=methods.enveloped, signature_algorithm="rsa-sha256",
                       digest_algorithm="sha256").sign(root, key=key_pem, cert=cert_pem)
    return etree.tostring(signed)


def _cert_dir(tmp_path, cert, name="uidai.pem") -> str:
    d = tmp_path / "uidai_certs"
    d.mkdir(exist_ok=True)
    (d / name).write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return str(d)


@pytest.fixture(scope="module")
def uidai():
    return make_ca("UIDAI Test Signing")  # (key, cert) standing in for UIDAI's signing cert


@pytest.fixture(scope="module")
def attacker():
    return make_ca("Not UIDAI")


# --- (a) genuine UIDAI-signed XML -> VERIFIED -----------------------------------------------------

def test_genuine_uidai_xml_is_verified(tmp_path, uidai):
    key, cert = uidai
    xml = _sign(_aadhaar_xml(), key, cert)
    provider = AadhaarOfflineProvider(uidai_cert_dir=_cert_dir(tmp_path, cert))
    res = provider.fetch(_consent(), _req(), payload=xml)
    assert res.signature_status == SignatureStatus.VERIFIED
    assert res.verified_at_source is True
    assert res.measurements["reference_id"] == "9012202606301200000"
    assert set(res.measurements["fields_present"]) == {"name", "dob", "gender"}
    assert "masked" in res.detail.lower()


# --- (b) MUST-FAIL: tampered after signing -> INVALID --------------------------------------------

def test_tampered_xml_is_invalid(tmp_path, uidai):
    key, cert = uidai
    signed = _sign(_aadhaar_xml(), key, cert)
    tampered = signed.replace(b"Asha Kumar", b"Mallory Khan")  # edit a signed value
    provider = AadhaarOfflineProvider(uidai_cert_dir=_cert_dir(tmp_path, cert))
    res = provider.fetch(_consent(), _req(), payload=tampered)
    assert res.signature_status == SignatureStatus.INVALID


# --- (c) MUST-FAIL: signed by a key we do NOT pin -> INVALID -------------------------------------

def test_non_uidai_signature_is_invalid(tmp_path, uidai, attacker):
    _, uidai_cert = uidai
    atk_key, atk_cert = attacker
    forged = _sign(_aadhaar_xml(), atk_key, atk_cert)        # signed by the attacker
    provider = AadhaarOfflineProvider(uidai_cert_dir=_cert_dir(tmp_path, uidai_cert))  # pin ONLY UIDAI
    res = provider.fetch(_consent(), _req(), payload=forged)
    assert res.signature_status == SignatureStatus.INVALID
    assert res.verified_at_source is False


# --- (d) no pinned UIDAI cert -> fail closed -----------------------------------------------------

def test_no_anchor_at_all_fails_closed(tmp_path, uidai, monkeypatch):
    """With NO pinned UIDAI cert AND no CCA root available, the provider cannot assert UIDAI -> fail closed."""
    key, cert = uidai
    xml = _sign(_aadhaar_xml(), key, cert)
    empty = tmp_path / "empty"
    empty.mkdir()
    from app.config import settings as app_settings
    monkeypatch.setattr(app_settings, "trust_anchor_dir", str(empty))  # remove the CCA-root fallback too
    res = AadhaarOfflineProvider(uidai_cert_dir=str(empty)).fetch(_consent(), _req(), payload=xml)
    assert res.signature_status == SignatureStatus.NOT_VERIFIED
    assert res.verified_at_source is False


# --- discrimination litmus (would FAIL against any constant) --------------------------------------

def test_verified_is_separated_from_invalid(tmp_path, uidai, attacker):
    key, cert = uidai
    provider = AadhaarOfflineProvider(uidai_cert_dir=_cert_dir(tmp_path, cert))
    good = provider.fetch(_consent(), _req(), payload=_sign(_aadhaar_xml(), key, cert))
    bad = provider.fetch(_consent(), _req(), payload=_sign(_aadhaar_xml(), attacker[0], attacker[1]))
    assert good.signature_status == SignatureStatus.VERIFIED
    assert bad.signature_status == SignatureStatus.INVALID


# --- ZIP (share-code) extraction path ------------------------------------------------------------

def test_zip_with_share_code_extracts_and_verifies(tmp_path, uidai):
    key, cert = uidai
    xml = _sign(_aadhaar_xml(), key, cert)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:  # (real UIDAI ZIPs are ZipCrypto-encrypted; zipfile decrypts
        zf.writestr("offline_ekyc.xml", xml)  #  with the share-code at runtime — here we exercise extraction)
    provider = AadhaarOfflineProvider(uidai_cert_dir=_cert_dir(tmp_path, cert))
    res = provider.fetch(_consent(), _req(share_code="1234"), payload=buf.getvalue())
    assert res.signature_status == SignatureStatus.VERIFIED


def test_zip_without_share_code_is_refused(tmp_path, uidai):
    key, cert = uidai
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("offline_ekyc.xml", _sign(_aadhaar_xml(), key, cert))
    res = AadhaarOfflineProvider(uidai_cert_dir=_cert_dir(tmp_path, cert)).fetch(
        _consent(), _req(share_code=None), payload=buf.getvalue())
    assert res.signature_status == SignatureStatus.NOT_VERIFIED
    assert "share-code" in res.detail


def test_applicable_only_for_identity():
    p = AadhaarOfflineProvider()
    assert p.applicable(DocRequest(doc_class=DocClass.IDENTITY)) is True
    assert p.applicable(DocRequest(doc_class=DocClass.FINANCIAL_STATEMENT)) is False
