"""Shared crypto test toolkit — real CAs, real signed PDFs, real detached JWS, all generated.

Reusable builders for the provider/source-pull tests (and any future crypto test). Everything is
generated in-memory with ``cryptography`` + pyHanko — no checked-in binaries, no hand-tuning. These
are TEST helpers (never shipped): they let a discrimination test sign with one key and verify against
another, which is what proves the verifiers actually separate genuine from forged (CLAUDE.md §3.2).
"""

from __future__ import annotations

import base64
import datetime
import io
import json
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.x509.oid import NameOID

# --------------------------------------------------------------------------------------------------
# Keys, CAs, leaf certs.
# --------------------------------------------------------------------------------------------------

def gen_rsa_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def gen_ec_key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


def _name(cn: str) -> x509.Name:
    return x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "IN"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Satyum Test"),
        x509.NameAttribute(NameOID.COMMON_NAME, cn),
    ])


def make_ca(cn: str) -> tuple[rsa.RSAPrivateKey, x509.Certificate]:
    """A self-signed CA certificate (basicConstraints CA=True)."""
    key = gen_rsa_key()
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
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, key_cert_sign=True, crl_sign=True,
                content_commitment=False, key_encipherment=False, data_encipherment=False,
                key_agreement=False, encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .sign(key, hashes.SHA256())
    )
    return key, cert


def make_leaf(
    ca_key: rsa.RSAPrivateKey, ca_cert: x509.Certificate, cn: str
) -> tuple[rsa.RSAPrivateKey, x509.Certificate]:
    """An end-entity signing certificate issued by ``ca_cert`` (non-repudiation key usage)."""
    key = gen_rsa_key()
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(_name(cn))
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=825))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, content_commitment=True,
                key_cert_sign=False, crl_sign=False, key_encipherment=False,
                data_encipherment=False, key_agreement=False, encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )
    return key, cert


def write_anchor_dir(tmp_path, ca_cert: x509.Certificate, name: str = "trusted_ca.pem") -> str:
    """Write ``ca_cert`` as the single pinned trust anchor in a fresh dir; return its path."""
    d = tmp_path / "anchors"
    d.mkdir(exist_ok=True)
    (d / name).write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
    return str(d)


def write_fip_key_dir(tmp_path, public_key: Any, name: str = "fip_pub.pem") -> str:
    """Write a FIP public key (SubjectPublicKeyInfo PEM) into a fresh FIP-key dir; return its path."""
    d = tmp_path / "fip_keys"
    d.mkdir(exist_ok=True)
    pem = public_key.public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    (d / name).write_bytes(pem)
    return str(d)


# --------------------------------------------------------------------------------------------------
# Signed PDFs (pyHanko).
# --------------------------------------------------------------------------------------------------

def _to_asn1_cert(cert: x509.Certificate):
    from asn1crypto import x509 as asn1_x509
    return asn1_x509.Certificate.load(cert.public_bytes(serialization.Encoding.DER))


def _to_asn1_key(key: rsa.RSAPrivateKey):
    from asn1crypto import keys as asn1_keys
    der = key.private_bytes(
        serialization.Encoding.DER,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return asn1_keys.PrivateKeyInfo.load(der)


def minimal_pdf() -> bytes:
    """A structurally-valid one-page PDF (no signature field) built with pyHanko's writer."""
    from pyhanko.pdf_utils import generic
    from pyhanko.pdf_utils.generic import pdf_name
    from pyhanko.pdf_utils.writer import PdfFileWriter

    w = PdfFileWriter()
    page = generic.DictionaryObject({
        pdf_name("/Type"): pdf_name("/Page"),
        pdf_name("/MediaBox"): generic.ArrayObject(
            [generic.NumberObject(x) for x in (0, 0, 612, 792)]
        ),
        pdf_name("/Resources"): generic.DictionaryObject(),
    })
    w.insert_page(page)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def sign_pdf(pdf_bytes: bytes, leaf_key, leaf_cert, ca_cert) -> bytes:
    """Sign ``pdf_bytes`` with the given leaf cert/key, embedding the CA in the chain."""
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.sign import signers
    from pyhanko_certvalidator.registry import SimpleCertificateStore

    registry = SimpleCertificateStore()
    registry.register_multiple([_to_asn1_cert(ca_cert), _to_asn1_cert(leaf_cert)])
    cms_signer = signers.SimpleSigner(
        signing_cert=_to_asn1_cert(leaf_cert),
        signing_key=_to_asn1_key(leaf_key),
        cert_registry=registry,
    )
    pdf_signer = signers.PdfSigner(
        signers.PdfSignatureMetadata(field_name="Signature1"),
        signer=cms_signer,
    )
    out = pdf_signer.sign_pdf(IncrementalPdfFileWriter(io.BytesIO(pdf_bytes)))
    return out.getvalue()


def append_after_signature(signed_pdf: bytes) -> bytes:
    """Append a real incremental-update revision after a signed PDF (the shadow attack)."""
    from pyhanko.pdf_utils import generic
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter

    iw = IncrementalPdfFileWriter(io.BytesIO(signed_pdf))
    iw.add_object(generic.TextStringObject("payload injected after the signature"))
    out = io.BytesIO()
    iw.write(out)
    return out.getvalue()


# --------------------------------------------------------------------------------------------------
# Detached JWS (RFC 7515 App. F) — the signer half, matching providers.account_aggregator's verifier.
# --------------------------------------------------------------------------------------------------

def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def sign_detached_jws(payload: bytes, private_key: Any, alg: str) -> str:
    """Produce a detached JWS over ``payload`` (RFC 7515 App. F): ``b64(header)..b64(sig)``.

    Matches the verifier in ``providers.account_aggregator``: the signing input is
    ``BASE64URL(header) || '.' || BASE64URL(payload)`` and ES256 emits raw ``r||s``.
    """
    header_b64 = _b64url(json.dumps({"alg": alg}, separators=(",", ":")).encode("ascii"))
    signing_input = (header_b64 + "." + _b64url(payload)).encode("ascii")
    if alg == "RS256":
        sig = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    elif alg == "PS256":
        sig = private_key.sign(
            signing_input,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=hashes.SHA256().digest_size),
            hashes.SHA256(),
        )
    elif alg == "ES256":
        der = private_key.sign(signing_input, ec.ECDSA(hashes.SHA256()))
        r, s = decode_dss_signature(der)
        sig = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    else:
        raise ValueError(f"unsupported alg {alg!r}")
    return f"{header_b64}..{_b64url(sig)}"


def aa_envelope(fi: dict[str, Any], private_key: Any, alg: str = "RS256", fip_id: str = "TEST-FIP") -> bytes:
    """Build a signed AA FI envelope: the exact FI bytes + a detached JWS over them, as JSON bytes."""
    fi_bytes = json.dumps(fi, separators=(",", ":")).encode("utf-8")
    jws = sign_detached_jws(fi_bytes, private_key, alg)
    envelope = {
        "fipID": fip_id,
        "payload_b64": _b64url(fi_bytes),
        "signature": jws,
    }
    return json.dumps(envelope).encode("utf-8")
