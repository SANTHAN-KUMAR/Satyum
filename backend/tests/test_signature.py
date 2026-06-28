"""Discrimination + must-fail fixtures for Tier-1 cryptographic provenance (BUILD-MANIFEST, §3.2).

These are the **cyber must-fail fixtures** for signature verification. They are generated
programmatically with ``cryptography`` (a self-made test CA + an attacker CA) and pyHanko's own
signing utilities — no checked-in binaries, no hand-tuning. The suite proves the analyzer
*separates*:

  (a) PDF signed by a test CA we ALSO pin as the trust root  -> **verified** (suspicion 0.0);
  (b) PDF signed by a DIFFERENT (attacker) CA we do NOT pin  -> **tampered** (chain fails);
  (c) a validly-signed PDF with bytes appended after the signature -> **tampered**
      (ByteRange/coverage no longer covers the whole file);
  (d) an unsigned PDF -> **absent** / NOT_EVALUATED.

(a) MUST be separated from (b)/(c) or the test fails — and every case would FAIL against a constant
return (no single constant yields suspicion 0.0 for (a), 1.0 for (b)/(c), and NOT_EVALUATED for (d)).

Honest non-coverage (TESTING-STRATEGY §3 Tier-1): a validly-signed document proves *origin +
integrity*, not *truthfulness* — asserted below as "verified source, not a fraud verdict".

All pyHanko / cryptography APIs used here are pinned in requirements.txt; if pyHanko is not yet
installed in the test environment the whole module skips (it cannot run without the heavy dep).
"""

from __future__ import annotations

import datetime
import importlib.util
import io

import pytest

from app.contracts import AnalysisContext, Mode, SignalStatus

# The whole module is meaningless without the crypto stack — skip cleanly rather than error.
pytest.importorskip("cryptography")
pyhanko = pytest.importorskip("pyhanko")

from cryptography import x509  # noqa: E402
from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402
from cryptography.x509.oid import NameOID  # noqa: E402

from verification.signature import (  # noqa: E402
    PROV_ABSENT,
    PROV_TAMPERED,
    PROV_VERIFIED,
    PadesSignatureAnalyzer,
)

# --------------------------------------------------------------------------------------------------
# Fixture generation: a real CA, a real leaf, a real signed PDF — all in memory.
# --------------------------------------------------------------------------------------------------

def _gen_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _name(cn: str) -> x509.Name:
    return x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "IN"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Satyum Test"),
        x509.NameAttribute(NameOID.COMMON_NAME, cn),
    ])


def _make_ca(cn: str) -> tuple[rsa.RSAPrivateKey, x509.Certificate]:
    """A self-signed CA certificate (basicConstraints CA=True)."""
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


def _make_leaf(
    ca_key: rsa.RSAPrivateKey, ca_cert: x509.Certificate, cn: str
) -> tuple[rsa.RSAPrivateKey, x509.Certificate]:
    """An end-entity signing certificate issued by ``ca_cert`` (non-repudiation key usage)."""
    key = _gen_key()
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
                digital_signature=True, content_commitment=True,  # content_commitment = non-repudiation
                key_cert_sign=False, crl_sign=False, key_encipherment=False,
                data_encipherment=False, key_agreement=False, encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )
    return key, cert


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


def _minimal_pdf() -> bytes:
    """A structurally-valid one-page PDF (no signature field), built with pyHanko's own writer so
    the xref/trailer are correct. pyHanko adds the signature field during signing."""
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


_MINIMAL_PDF = _minimal_pdf()


def _sign_pdf(pdf_bytes: bytes, leaf_key, leaf_cert, ca_cert) -> bytes:
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


# --------------------------------------------------------------------------------------------------
# Session-scoped artifacts (key generation + signing are slow; build each fixture once).
# --------------------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def trusted_ca():
    return _make_ca("Satyum Trusted Test CA")


@pytest.fixture(scope="module")
def attacker_ca():
    return _make_ca("Attacker Self-Signed CA")


@pytest.fixture(scope="module")
def anchor_dir(tmp_path_factory, trusted_ca) -> str:
    """A trust-anchor directory pinning ONLY the trusted test CA (not the attacker)."""
    _, ca_cert = trusted_ca
    d = tmp_path_factory.mktemp("trust_anchors")
    (d / "trusted_ca.pem").write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
    return str(d)


@pytest.fixture(scope="module")
def pdf_signed_trusted(trusted_ca) -> bytes:
    ca_key, ca_cert = trusted_ca
    leaf_key, leaf_cert = _make_leaf(ca_key, ca_cert, "statements.bank.example")
    return _sign_pdf(_MINIMAL_PDF, leaf_key, leaf_cert, ca_cert)


@pytest.fixture(scope="module")
def pdf_signed_attacker(attacker_ca) -> bytes:
    ca_key, ca_cert = attacker_ca
    leaf_key, leaf_cert = _make_leaf(ca_key, ca_cert, "statements.bank.example")
    return _sign_pdf(_MINIMAL_PDF, leaf_key, leaf_cert, ca_cert)


@pytest.fixture(scope="module")
def pdf_appended_after_signature(pdf_signed_trusted) -> bytes:
    """A validly-signed PDF with a REAL incremental-update revision appended after the signature
    (the shadow / incremental-update attack).

    Built with pyHanko's own ``IncrementalPdfFileWriter`` so the result is still a parseable PDF —
    the realistic attack, not a corrupt blob. The original signature's /ByteRange now covers only
    its own revision (coverage drops from ENTIRE_FILE to ENTIRE_REVISION), so the analyzer must
    treat it as tampered: the signature no longer covers the whole file.
    """
    from pyhanko.pdf_utils import generic
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter

    iw = IncrementalPdfFileWriter(io.BytesIO(pdf_signed_trusted))
    # Append an object in a new revision — bytes added AFTER the signed range.
    iw.add_object(generic.TextStringObject("payload injected after the signature"))
    out = io.BytesIO()
    iw.write(out)
    return out.getvalue()


def _ctx(pdf_bytes: bytes) -> AnalysisContext:
    return AnalysisContext(
        session_id="t", intake_mode=Mode.FILE,
        file_bytes=pdf_bytes, file_name="doc.pdf", file_mime="application/pdf",
    )


# --------------------------------------------------------------------------------------------------
# (a) Positive control: signed by the pinned CA -> verified.
# --------------------------------------------------------------------------------------------------

def test_a_trusted_signature_is_verified(anchor_dir, pdf_signed_trusted):
    az = PadesSignatureAnalyzer(anchor_dir=anchor_dir)
    ctx = _ctx(pdf_signed_trusted)
    assert az.applicable(ctx) is True

    sig = az.analyze(ctx)
    assert sig.status == SignalStatus.VALID
    assert sig.suspicion == 0.0
    assert sig.measurements["provenance"] == PROV_VERIFIED
    assert sig.measurements["method"] == "PAdES"
    # the signature must actually cover the whole file
    assert sig.measurements["signatures"][0]["covers_whole_file"] is True
    assert sig.measurements["signatures"][0]["trusted"] is True
    # downstream contract: a verified chain publishes provenance for the red-flag / cross-doc logic
    assert ctx.shared.get("provenance_verified") is True


# --------------------------------------------------------------------------------------------------
# (b) MUST-FAIL: attacker's own CA, not pinned -> chain fails -> tampered.
# --------------------------------------------------------------------------------------------------

def test_b_attacker_cert_chain_fails(anchor_dir, pdf_signed_attacker):
    az = PadesSignatureAnalyzer(anchor_dir=anchor_dir)
    ctx = _ctx(pdf_signed_attacker)

    sig = az.analyze(ctx)
    assert sig.status == SignalStatus.VALID
    assert sig.suspicion == 1.0, "an attacker-CA signature must be flagged as tampered"
    assert sig.measurements["provenance"] == PROV_TAMPERED
    # The CMS math may be intact, but the chain must NOT reach a pinned anchor — that is the attack.
    assert sig.measurements["signatures"][0]["trusted"] is False
    # never publish provenance for an unverified chain
    assert ctx.shared.get("provenance_verified") is not True


# --------------------------------------------------------------------------------------------------
# (c) MUST-FAIL: bytes appended after /ByteRange (shadow attack) -> coverage/digest fails -> tampered.
# --------------------------------------------------------------------------------------------------

def test_c_appended_bytes_after_signature_is_tampered(anchor_dir, pdf_appended_after_signature):
    az = PadesSignatureAnalyzer(anchor_dir=anchor_dir)
    ctx = _ctx(pdf_appended_after_signature)

    sig = az.analyze(ctx)
    assert sig.status == SignalStatus.VALID
    assert sig.suspicion == 1.0, "appended bytes after the signature must be flagged as tampered"
    assert sig.measurements["provenance"] == PROV_TAMPERED
    # The signature no longer covers the whole file (the defining property of the shadow attack).
    assert sig.measurements["signatures"][0]["covers_whole_file"] is False
    assert ctx.shared.get("provenance_verified") is not True


# --------------------------------------------------------------------------------------------------
# (d) Unsigned PDF -> absent -> NOT_EVALUATED (route to Tier 2; never a pass).
# --------------------------------------------------------------------------------------------------

def test_d_unsigned_pdf_is_absent_not_evaluated(anchor_dir):
    az = PadesSignatureAnalyzer(anchor_dir=anchor_dir)
    ctx = _ctx(_MINIMAL_PDF)

    sig = az.analyze(ctx)
    assert sig.status == SignalStatus.NOT_EVALUATED
    assert sig.suspicion is None  # never a fabricated pass
    assert sig.measurements.get("provenance") == PROV_ABSENT
    assert ctx.shared.get("provenance_verified") is not True


# --------------------------------------------------------------------------------------------------
# The discrimination claim, stated explicitly (would FAIL against any constant return).
# --------------------------------------------------------------------------------------------------

def test_verified_is_separated_from_tampered(anchor_dir, pdf_signed_trusted, pdf_signed_attacker):
    az = PadesSignatureAnalyzer(anchor_dir=anchor_dir)
    good = az.analyze(_ctx(pdf_signed_trusted))
    bad = az.analyze(_ctx(pdf_signed_attacker))
    # No constant can satisfy both — this is the §3.2 litmus encoded as an assertion.
    assert good.suspicion is not None and bad.suspicion is not None
    assert good.suspicion == 0.0 and bad.suspicion == 1.0
    assert good.suspicion < bad.suspicion


def test_no_pinned_anchors_fails_closed(tmp_path, pdf_signed_trusted):
    """With an EMPTY trust store the analyzer must fail closed (ERROR), never auto-pass (§10)."""
    empty = tmp_path / "empty_anchors"
    empty.mkdir()
    az = PadesSignatureAnalyzer(anchor_dir=str(empty))
    sig = az.analyze(_ctx(pdf_signed_trusted))
    assert sig.status == SignalStatus.ERROR
    assert sig.suspicion is None


def test_unparsable_pdf_fails_closed(anchor_dir):
    """Garbage that claims to be a PDF must degrade to ERROR, never crash or pass."""
    az = PadesSignatureAnalyzer(anchor_dir=anchor_dir)
    ctx = _ctx(b"%PDF-1.7\nthis is not a real pdf body at all \x00\xff")
    sig = az.analyze(ctx)
    assert sig.status in (SignalStatus.ERROR, SignalStatus.NOT_EVALUATED)
    assert sig.suspicion is None


# --------------------------------------------------------------------------------------------------
# Honest non-coverage (TESTING-STRATEGY §3 Tier-1): provenance proves ORIGIN + INTEGRITY,
# not TRUTHFULNESS. A validly-signed statement is "verified source", NOT a fraud verdict.
# --------------------------------------------------------------------------------------------------

def test_honest_bound_verified_means_origin_not_truthfulness(anchor_dir, pdf_signed_trusted):
    az = PadesSignatureAnalyzer(anchor_dir=anchor_dir)
    sig = az.analyze(_ctx(pdf_signed_trusted))
    # We assert ONLY that origin+integrity verified (suspicion 0.0) — the analyzer makes no claim
    # about whether the *content* is honest. Content fraud is the Tier-2 arithmetic engine's job.
    assert sig.status == SignalStatus.VALID and sig.suspicion == 0.0
    assert "verified" in sig.reason.lower()
    # It does NOT assert a clean fraud verdict for the document as a whole.
    assert "fraud" not in sig.reason.lower()


# --------------------------------------------------------------------------------------------------
# Protocol conformance: attributes the registry/orchestrator rely on.
# --------------------------------------------------------------------------------------------------

def test_analyzer_protocol_attributes():
    az = PadesSignatureAnalyzer()
    assert az.name == "pades_signature"
    assert az.layer == 1
    assert az.mode == Mode.FILE
    assert az.order == 10


def test_not_applicable_on_non_pdf():
    az = PadesSignatureAnalyzer()
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    ctx = AnalysisContext(session_id="t", intake_mode=Mode.FILE, file_bytes=png)
    assert az.applicable(ctx) is False
    # And on a camera intake it must never claim applicability (mode-tagging invariant).
    cam = AnalysisContext(session_id="t", intake_mode=Mode.CAMERA, file_bytes=_MINIMAL_PDF)
    assert az.applicable(cam) is False


# ==================================================================================================
# C2PA content-provenance analyzer.
#
# The c2pa SDK (c2pa-python==0.6.1) is an optional heavy dependency; when it is not installed these
# tests skip cleanly (they cannot run without it — never a false green). The decision logic mirrors
# PAdES: a present manifest that is NOT trusted (self-signed / unpinned) is the documented C2PA
# exploit and must be flagged; an image with no manifest routes to forensics (NOT_EVALUATED).
# ==================================================================================================

from verification.signature import C2paProvenanceAnalyzer  # noqa: E402

# c2pa is an OPTIONAL heavy dep: skip ONLY the c2pa runtime tests when it's absent (never the PAdES
# suite, and never a false green). Module-level importorskip would skip the whole file — avoid it.
_c2pa_spec = importlib.util.find_spec("c2pa")
requires_c2pa = pytest.mark.skipif(
    _c2pa_spec is None, reason="c2pa SDK not installed — image-provenance path untested here"
)

# A genuinely valid PNG with NO C2PA manifest, Pillow-encoded once at import.
# NB: a hand-rolled minimal PNG is REJECTED by c2pa-rs's image reader ("asset could not be parsed"),
# which is a *different* condition from "no manifest". To exercise the real absent-manifest path the
# SDK must be handed a structurally valid image — so we encode one rather than hand-write bytes.
def _valid_png_no_manifest() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (123, 200, 50)).save(buf, format="PNG")
    return buf.getvalue()


_VALID_PNG_NO_MANIFEST = _valid_png_no_manifest()


def _png_ctx() -> AnalysisContext:
    return AnalysisContext(
        session_id="t", intake_mode=Mode.FILE,
        file_bytes=_VALID_PNG_NO_MANIFEST, file_name="img.png", file_mime="image/png",
    )


@requires_c2pa
def test_c2pa_no_manifest_routes_to_forensics(anchor_dir):
    """An image with NO C2PA manifest must be NOT_EVALUATED (route to Tier 2) — never an auto-pass."""
    az = C2paProvenanceAnalyzer(anchor_dir=anchor_dir)
    ctx = _png_ctx()
    assert az.applicable(ctx) is True
    sig = az.analyze(ctx)
    assert sig.status == SignalStatus.NOT_EVALUATED
    assert sig.suspicion is None
    assert sig.measurements.get("provenance") == PROV_ABSENT
    assert ctx.shared.get("provenance_verified") is not True


@requires_c2pa
def test_c2pa_no_pinned_anchors_fails_closed(tmp_path):
    """Validating a manifest WITHOUT a pinned trust list is the self-signed exploit — fail closed."""
    empty = tmp_path / "empty"
    empty.mkdir()
    az = C2paProvenanceAnalyzer(anchor_dir=str(empty))
    sig = az.analyze(_png_ctx())
    # With no pinned anchors the analyzer refuses up front (ERROR) — it will not validate an unpinned
    # manifest (the documented self-signed exploit). Whichever path, it must never fabricate a pass.
    assert sig.status in (SignalStatus.ERROR, SignalStatus.NOT_EVALUATED)
    assert sig.suspicion is None


@requires_c2pa
def test_c2pa_unparsable_image_fails_closed_to_error(anchor_dir):
    """A corrupt/undecodable image must fail closed to ERROR — NOT a fabricated 'tampered' verdict.

    Discrimination: 'could not parse the asset' is a different cyber-fact from 'a manifest is present
    and its signature is invalid'. The former is ERROR (-> human REVIEW); only the latter is tamper
    evidence (suspicion 1.0). This pins that the analyzer does not manufacture a tamper claim out of a
    parse failure (§3.1). Would FAIL against a constant 'tampered' return.
    """
    az = C2paProvenanceAnalyzer(anchor_dir=anchor_dir)
    # Valid PNG magic so the image path is selected, then bytes c2pa-rs cannot decode as an image.
    corrupt = b"\x89PNG\r\n\x1a\n" + b"\x00\x01\x02\x03 not a real png \xff\xfe" * 4
    ctx = AnalysisContext(
        session_id="t", intake_mode=Mode.FILE,
        file_bytes=corrupt, file_name="x.png", file_mime="image/png",
    )
    assert az.applicable(ctx) is True
    sig = az.analyze(ctx)
    assert sig.status == SignalStatus.ERROR
    # ERROR carries no suspicion — it is "could not evaluate", never an unearned tamper score.
    assert sig.suspicion is None
    assert ctx.shared.get("provenance_verified") is not True


def test_c2pa_protocol_attributes():
    az = C2paProvenanceAnalyzer()
    assert az.name == "c2pa_provenance"
    assert az.layer == 1
    assert az.mode == Mode.FILE
    assert az.order == 11
