"""Discrimination tests for the legacy ``/adbe.x509.rsa_sha1`` PDF signature verifier.

This is a genuinely different container format from modern PAdES/CMS (module docstring in
``verification/legacy_pdf_signature.py``): pyHanko's CMS-only parser raises on it, so this module reads
the signature field directly (pikepdf) and does the RSA-PKCS1v15-SHA1 math itself. Per CLAUDE.md §3.2,
every check here proves the real cryptographic behaviour — genuine bytes verify, a single tampered byte
in the covered range breaks it, a DER-wrapped signature is unwrapped correctly (real bug this session:
an unwrap gap misreported a genuine document as tampered), and a chain to an unpinned CA is rejected.
"""

from __future__ import annotations

import datetime
import io

import pytest

pytest.importorskip("cryptography")

from asn1crypto import x509 as asn1_x509  # noqa: E402
from cryptography import x509  # noqa: E402
from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import padding, rsa  # noqa: E402
from cryptography.x509.oid import NameOID  # noqa: E402

from verification.legacy_pdf_signature import (  # noqa: E402
    _parse_pdf_date,
    _unwrap_octet_string,
    extract_signature_fields,
    validate_chain_with_point_in_time,
    verify_rsa_sha1,
)

# --------------------------------------------------------------------------------------------------
# Fixture generation: real RSA keys + real X.509 certs, in memory (mirrors test_signature.py).
# --------------------------------------------------------------------------------------------------


def _gen_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _name(cn: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])


def _make_ca(cn: str) -> tuple[rsa.RSAPrivateKey, x509.Certificate]:
    key = _gen_key()
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(_name(cn))
        .issuer_name(_name(cn))
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    return key, cert


def _make_leaf(
    ca_key: rsa.RSAPrivateKey,
    ca_cert: x509.Certificate,
    cn: str,
    *,
    not_before: datetime.datetime | None = None,
    not_after: datetime.datetime | None = None,
) -> tuple[rsa.RSAPrivateKey, x509.Certificate]:
    key = _gen_key()
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(_name(cn))
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before or (now - datetime.timedelta(days=1)))
        .not_valid_after(not_after or (now + datetime.timedelta(days=365)))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    return key, cert


def _to_asn1_cert(cert: x509.Certificate) -> asn1_x509.Certificate:
    return asn1_x509.Certificate.load(cert.public_bytes(serialization.Encoding.DER))


@pytest.fixture(scope="module")
def trusted_ca():
    return _make_ca("Satyum Legacy Test CA")


@pytest.fixture(scope="module")
def attacker_ca():
    return _make_ca("Attacker Legacy CA")


@pytest.fixture(scope="module")
def anchor_dir(trusted_ca) -> list:
    _, ca_cert = trusted_ca
    return [_to_asn1_cert(ca_cert)]


def _field(byte_range: list, contents: bytes, certs: list[bytes], signing_time=None) -> dict:
    return {
        "sub_filter": "adbe.x509.rsa_sha1",
        "byte_range": byte_range,
        "contents": contents,
        "certs": certs,
        "signing_time": signing_time,
    }


def _sign_rsa_sha1(key: rsa.RSAPrivateKey, covered: bytes) -> bytes:
    return key.sign(covered, padding.PKCS1v15(), hashes.SHA1())


# --------------------------------------------------------------------------------------------------
# verify_rsa_sha1: genuine signature verifies; a single altered byte in the covered range breaks it.
# --------------------------------------------------------------------------------------------------


def test_genuine_signature_is_intact(trusted_ca):
    key, cert = trusted_ca
    doc = b"%PDF-1.4 fake covered content for legacy signature test" + b"\x00" * 20
    sig = _sign_rsa_sha1(key, doc)
    field = _field([0, len(doc), len(doc), 0], sig, [_to_asn1_cert(cert).dump()])
    result = verify_rsa_sha1(doc, field)
    assert result["intact"] is True
    assert result["valid"] is True
    assert result["certificate"] is not None


def test_single_byte_tamper_in_covered_range_breaks_signature(trusted_ca):
    """The §3.2 litmus: a genuinely different byte inside the /ByteRange must invalidate the RSA
    signature — the whole point of signing over the covered bytes."""
    key, cert = trusted_ca
    doc = bytearray(b"%PDF-1.4 fake covered content for legacy signature test" + b"\x00" * 20)
    sig = _sign_rsa_sha1(key, bytes(doc))
    tampered = bytearray(doc)
    tampered[10] ^= 0xFF  # flip one covered byte after signing
    field = _field([0, len(tampered), len(tampered), 0], sig, [_to_asn1_cert(cert).dump()])
    result = verify_rsa_sha1(bytes(tampered), field)
    assert result["intact"] is False
    assert result["valid"] is False


def test_discrimination_genuine_vs_tampered(trusted_ca):
    key, cert = trusted_ca
    doc = b"%PDF-1.4 genuine content" + b"\x00" * 20
    sig = _sign_rsa_sha1(key, doc)
    certs = [_to_asn1_cert(cert).dump()]
    good = verify_rsa_sha1(doc, _field([0, len(doc), len(doc), 0], sig, certs))
    bad = verify_rsa_sha1(
        doc.replace(b"genuine", b"altered"), _field([0, len(doc), len(doc), 0], sig, certs)
    )
    # No constant satisfies both (§3.2): genuine -> intact True, tampered -> intact False.
    assert good["intact"] is True and bad["intact"] is False


def test_no_embedded_cert_fails_closed():
    doc = b"content"
    field = _field([0, len(doc), len(doc), 0], b"\x00" * 256, [])
    result = verify_rsa_sha1(doc, field)
    assert result["intact"] is False
    assert result["certificate"] is None
    assert "no /Cert" in result["error"]


def test_covers_whole_file_flag(trusted_ca):
    key, cert = trusted_ca
    doc = b"%PDF-1.4 content" + b"\x00" * 20
    sig = _sign_rsa_sha1(key, doc)
    certs = [_to_asn1_cert(cert).dump()]
    whole = verify_rsa_sha1(doc, _field([0, len(doc), len(doc), 0], sig, certs))
    assert whole["covers_whole_file"] is True
    # Coverage ending before the true end of the file (bytes appended after) is NOT the whole file.
    partial = verify_rsa_sha1(doc + b"appended", _field([0, len(doc), len(doc), 0], sig, certs))
    assert partial["covers_whole_file"] is False


# --------------------------------------------------------------------------------------------------
# _unwrap_octet_string: the real bug this session — a DER OCTET STRING wrapper around the raw RSA
# signature must be unwrapped, or a genuine signature misreports as "does not match" (tampered).
# --------------------------------------------------------------------------------------------------


def test_der_wrapped_signature_is_unwrapped():
    from asn1crypto.core import OctetString

    raw_sig = b"\x11" * 256
    wrapped = OctetString(raw_sig).dump()
    assert wrapped != raw_sig  # the wrapper actually adds bytes (this is the point of the test)
    assert _unwrap_octet_string(wrapped) == raw_sig


def test_bare_signature_is_left_unchanged():
    """A genuinely bare (non-wrapped) signature must NOT be mangled by a false-positive unwrap —
    even one that happens to start with byte 0x04 (the OCTET STRING tag)."""
    # Deliberately not a valid OCTET STRING encoding for its own length (round-trip fails).
    bare = b"\x04\x82\x00\x01" + b"\xAB" * 250  # header claims a length that doesn't match the payload
    assert _unwrap_octet_string(bare) == bare


def test_end_to_end_wrapped_signature_still_verifies(trusted_ca):
    """The exact scenario that broke a real document this session: sign, DER-OCTET-STRING-wrap the
    signature bytes (as some signing tools do), and confirm verify_rsa_sha1 still succeeds only because
    it unwraps first."""
    from asn1crypto.core import OctetString

    key, cert = trusted_ca
    doc = b"%PDF-1.4 content requiring unwrap" + b"\x00" * 20
    raw_sig = _sign_rsa_sha1(key, doc)
    wrapped_sig = OctetString(raw_sig).dump()
    certs = [_to_asn1_cert(cert).dump()]
    result = verify_rsa_sha1(doc, _field([0, len(doc), len(doc), 0], wrapped_sig, certs))
    assert result["intact"] is True, "a DER-wrapped genuine signature must still verify, not tamper-flag"


# --------------------------------------------------------------------------------------------------
# validate_chain_with_point_in_time: pinned vs unpinned CA, and the short-lived-cert rescue.
# --------------------------------------------------------------------------------------------------


def test_pinned_ca_chain_is_trusted(trusted_ca, anchor_dir):
    _, leaf_cert = _make_leaf(*trusted_ca, "legacy.signer.example")
    trusted, point_in_time = validate_chain_with_point_in_time(
        _to_asn1_cert(leaf_cert), trust_roots=anchor_dir, crls=[], revocation_mode="soft-fail",
        signing_time=None,
    )
    assert trusted is True
    assert point_in_time is False


def test_unpinned_ca_chain_is_not_trusted(attacker_ca, anchor_dir):
    _, leaf_cert = _make_leaf(*attacker_ca, "attacker.signer.example")
    trusted, _ = validate_chain_with_point_in_time(
        _to_asn1_cert(leaf_cert), trust_roots=anchor_dir, crls=[], revocation_mode="soft-fail",
        signing_time=None,
    )
    assert trusted is False


def test_discrimination_pinned_vs_unpinned_chain(trusted_ca, attacker_ca, anchor_dir):
    _, good_leaf = _make_leaf(*trusted_ca, "good.example")
    _, bad_leaf = _make_leaf(*attacker_ca, "bad.example")
    good, _ = validate_chain_with_point_in_time(
        _to_asn1_cert(good_leaf), trust_roots=anchor_dir, crls=[], revocation_mode="soft-fail",
        signing_time=None,
    )
    bad, _ = validate_chain_with_point_in_time(
        _to_asn1_cert(bad_leaf), trust_roots=anchor_dir, crls=[], revocation_mode="soft-fail",
        signing_time=None,
    )
    assert good is True and bad is False  # no constant satisfies both (§3.2)


def test_expired_cert_is_rescued_by_point_in_time_signing_time(trusted_ca, anchor_dir):
    """A leaf whose validity window has already passed (as of 'now') but WAS valid at the signed
    /M time must be rescued by the retry — the same short-lived-cert pattern as the CMS path."""
    ca_key, ca_cert = trusted_ca
    now = datetime.datetime.now(datetime.UTC)
    signed_at = now - datetime.timedelta(days=30)
    _, leaf_cert = _make_leaf(
        ca_key, ca_cert, "expired.signer.example",
        not_before=signed_at - datetime.timedelta(minutes=5),
        not_after=signed_at + datetime.timedelta(minutes=30),
    )
    trusted, point_in_time = validate_chain_with_point_in_time(
        _to_asn1_cert(leaf_cert), trust_roots=anchor_dir, crls=[], revocation_mode="soft-fail",
        signing_time=signed_at,
    )
    assert trusted is True
    assert point_in_time is True


def test_expired_cert_without_signing_time_is_not_rescued(trusted_ca, anchor_dir):
    """Without a signed time to retry against, an expired cert must stay untrusted — never guess a
    moment to rescue a chain (§3.1 honesty: no fabricated pass)."""
    ca_key, ca_cert = trusted_ca
    now = datetime.datetime.now(datetime.UTC)
    _, leaf_cert = _make_leaf(
        ca_key, ca_cert, "expired-no-time.signer.example",
        not_before=now - datetime.timedelta(days=60),
        not_after=now - datetime.timedelta(days=30),
    )
    trusted, point_in_time = validate_chain_with_point_in_time(
        _to_asn1_cert(leaf_cert), trust_roots=anchor_dir, crls=[], revocation_mode="soft-fail",
        signing_time=None,
    )
    assert trusted is False
    assert point_in_time is False


# --------------------------------------------------------------------------------------------------
# _parse_pdf_date: real ISO-32000 PDF date parsing, never a guessed time.
# --------------------------------------------------------------------------------------------------


def test_parse_pdf_date_with_timezone():
    dt = _parse_pdf_date("D:20230615143000+05'30'")
    assert dt is not None
    assert (dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second) == (2023, 6, 15, 14, 30, 0)
    assert dt.utcoffset() == datetime.timedelta(hours=5, minutes=30)


def test_parse_pdf_date_utc_z():
    dt = _parse_pdf_date("D:20230615143000Z")
    assert dt is not None
    assert dt.tzinfo == datetime.UTC


def test_parse_pdf_date_malformed_returns_none():
    assert _parse_pdf_date("not a pdf date") is None
    assert _parse_pdf_date("") is None


# --------------------------------------------------------------------------------------------------
# extract_signature_fields: real pikepdf field parsing against a hand-built AcroForm.
# --------------------------------------------------------------------------------------------------


def _build_pdf_with_rsa_sha1_field(contents: bytes, cert_der: bytes) -> bytes:
    import pikepdf

    pdf = pikepdf.new()
    pdf.add_blank_page()
    sig_dict = pikepdf.Dictionary(
        {
            "/Type": pikepdf.Name("/Sig"),
            "/Filter": pikepdf.Name("/Adobe.PPKLite"),
            "/SubFilter": pikepdf.Name("/adbe.x509.rsa_sha1"),
            "/ByteRange": pikepdf.Array([0, 10, 20, 5]),
            "/Contents": pikepdf.String(contents),
            "/Cert": pikepdf.Array([pikepdf.String(cert_der)]),
            "/M": pikepdf.String("D:20230615143000+05'30'"),
        }
    )
    field_dict = pikepdf.Dictionary(
        {"/FT": pikepdf.Name("/Sig"), "/V": sig_dict, "/T": pikepdf.String("Sig1")}
    )
    pdf.Root.AcroForm = pikepdf.Dictionary({"/Fields": pikepdf.Array([field_dict])})
    buf = io.BytesIO()
    pdf.save(buf)
    return buf.getvalue()


def test_extract_signature_fields_reads_real_field(trusted_ca):
    _, cert = trusted_ca
    cert_der = _to_asn1_cert(cert).dump()
    contents = b"\xAB" * 256
    pdf_bytes = _build_pdf_with_rsa_sha1_field(contents, cert_der)

    fields = extract_signature_fields(pdf_bytes)
    assert len(fields) == 1
    f = fields[0]
    assert f["sub_filter"] == "adbe.x509.rsa_sha1"
    assert f["byte_range"] == [0, 10, 20, 5]
    assert f["contents"] == contents
    assert f["certs"] == [cert_der]
    assert f["signing_time"] is not None
    assert f["signing_time"].year == 2023


def test_extract_signature_fields_on_unsigned_pdf_yields_nothing():
    import pikepdf

    pdf = pikepdf.new()
    pdf.add_blank_page()
    buf = io.BytesIO()
    pdf.save(buf)
    assert extract_signature_fields(buf.getvalue()) == []


def test_extract_signature_fields_on_garbage_bytes_never_crashes():
    assert extract_signature_fields(b"not a pdf at all") == []
