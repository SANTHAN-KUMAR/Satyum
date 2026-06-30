"""Password-protected-PDF handling — detect, prompt, and decrypt IN MEMORY without breaking the signature.

Government/bank PDFs (Aadhaar, CAMS, signed e-statements) ship password-locked. The honest flow is to
take the password in-app and decrypt in memory — NOT to route the user through a 3rd-party "unlock"
tool, which re-saves the file and destroys the digital signature.

Discriminative claims proven here (CLAUDE.md §3.2/§8):
  * the signature SURVIVES in-memory decrypt (encrypt-then-sign, the real issuance order) — the headline;
  * an encrypted upload with NO password is a recoverable prompt (NOT_EVALUATED / PasswordRequired),
    never a silent pass, an ERROR crash, or a fraud REJECT;
  * a WRONG password is rejected before any analyzer runs;
  * a correct password makes the document readable (the render path decrypts) AND runs the pipeline;
  * decrypting never mutates the original bytes (that is exactly what preserves the signature).

These would all fail against a stubbed implementation (e.g. one that ignored encryption, or re-saved
the file to strip the password).
"""

from __future__ import annotations

import io

import pikepdf
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.contracts import AnalysisContext, Mode, SignalStatus
from app.orchestrator import AnalyzerRegistry, AuditLedger
from app.routes.verify import router as verify_router
from app.session import SessionManager
from forensics.extraction.render import render_pages
from tests.crypto_fixtures import (
    _to_asn1_cert,
    _to_asn1_key,
    make_ca,
    make_leaf,
    minimal_pdf,
    write_anchor_dir,
)
from verification.pdf_crypto import is_pdf_encrypted, password_unlocks
from verification.signature import PadesSignatureAnalyzer

PW = "Aadhaar1981"  # a realistic Aadhaar-style password (name-prefix + birth year)


def _encrypt(pdf_bytes: bytes, password: str) -> bytes:
    """Apply user+owner password encryption (what a govt portal does on download)."""
    with pikepdf.open(io.BytesIO(pdf_bytes)) as p:
        out = io.BytesIO()
        p.save(out, encryption=pikepdf.Encryption(user=password, owner=password, R=6))
        return out.getvalue()


def _encrypt_then_sign(password: str, leaf_key, leaf_cert, ca_cert) -> bytes:
    """A signed AND encrypted PDF in the REAL issuance order (encrypt, then sign the encrypted bytes),
    so the signature's digest covers the stored (encrypted) bytes and verifies after in-memory decrypt."""
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.sign import signers
    from pyhanko_certvalidator.registry import SimpleCertificateStore

    enc = _encrypt(minimal_pdf(), password)
    reg = SimpleCertificateStore()
    reg.register_multiple([_to_asn1_cert(ca_cert), _to_asn1_cert(leaf_cert)])
    cms = signers.SimpleSigner(
        signing_cert=_to_asn1_cert(leaf_cert),
        signing_key=_to_asn1_key(leaf_key),
        cert_registry=reg,
    )
    writer = IncrementalPdfFileWriter(io.BytesIO(enc))
    writer.encrypt(password)  # authenticate so the signing revision is written encrypted
    signer = signers.PdfSigner(signers.PdfSignatureMetadata(field_name="Signature1"), signer=cms)
    return signer.sign_pdf(writer).getvalue()


@pytest.fixture(scope="module")
def ca():
    return make_ca("Demo CCA Root")


@pytest.fixture(scope="module")
def leaf(ca):
    ca_key, ca_cert = ca
    return make_leaf(ca_key, ca_cert, "statements.bank.example")


@pytest.fixture()
def anchor_dir(tmp_path, ca):
    return write_anchor_dir(tmp_path, ca[1])


@pytest.fixture()
def signed_encrypted(leaf, ca):
    leaf_key, leaf_cert = leaf
    return _encrypt_then_sign(PW, leaf_key, leaf_cert, ca[1])


def _ctx(raw: bytes, password: str | None = None) -> AnalysisContext:
    return AnalysisContext(
        session_id="t", intake_mode=Mode.FILE, file_bytes=raw,
        file_name="doc.pdf", file_mime="application/pdf", pdf_password=password,
    )


# --- 1. detection / password-validation helpers ---------------------------------------------------

def test_detects_encrypted_vs_plain():
    assert is_pdf_encrypted(_encrypt(minimal_pdf(), PW)) is True
    assert is_pdf_encrypted(minimal_pdf()) is False
    assert is_pdf_encrypted(b"not a pdf") is False  # fail-safe: non-PDF is not "encrypted"


def test_password_unlocks_only_with_correct_password():
    enc = _encrypt(minimal_pdf(), PW)
    assert password_unlocks(enc, PW) is True
    assert password_unlocks(enc, "wrong") is False
    assert password_unlocks(enc, None) is False


# --- 2. THE HEADLINE: in-memory decrypt PRESERVES the signature -----------------------------------

def test_signature_survives_in_memory_decrypt(signed_encrypted, anchor_dir):
    az = PadesSignatureAnalyzer(anchor_dir=anchor_dir)
    sig = az.analyze(_ctx(signed_encrypted, PW))
    assert sig.status == SignalStatus.VALID
    assert sig.suspicion == 0.0  # intact, chains to the pinned anchor — NOT broken by decryption
    assert "verified" in (sig.reason or "").lower()


def test_encrypted_signature_without_password_is_pending_not_crash(signed_encrypted, anchor_dir):
    az = PadesSignatureAnalyzer(anchor_dir=anchor_dir)
    sig = az.analyze(_ctx(signed_encrypted, None))
    assert sig.status == SignalStatus.NOT_EVALUATED  # never a silent pass, never an ERROR crash
    assert sig.suspicion is None
    assert "password" in (sig.reason or "").lower()


def test_decrypt_does_not_mutate_original_bytes(signed_encrypted, anchor_dir):
    before = bytes(signed_encrypted)  # copy
    PadesSignatureAnalyzer(anchor_dir=anchor_dir).analyze(_ctx(signed_encrypted, PW))
    assert signed_encrypted == before  # we never re-save — that is what preserves the signature


# --- 3. the read path decrypts so the document can actually be understood -------------------------

def test_render_decrypts_encrypted_pdf_with_password():
    enc = _encrypt(minimal_pdf(), PW)
    pages_ok, _ = render_pages(_ctx(enc, PW), max_pages=4)
    assert pages_ok, "with the password, the encrypted PDF must render for the reader"
    pages_locked, reason = render_pages(_ctx(enc, None), max_pages=4)
    assert not pages_locked  # without the password it cannot be read (never a blank fabricated page)


# --- 4. the API gate: prompt for a password, reject a wrong one -----------------------------------

@pytest.fixture()
def client() -> TestClient:
    app = FastAPI()
    app.state.ledger = AuditLedger()
    app.state.registry = AnalyzerRegistry()  # empty registry is fine: the password gate runs first
    app.state.sessions = SessionManager()
    app.include_router(verify_router)
    return TestClient(app)


def test_route_prompts_for_password_on_encrypted_upload(client):
    enc = _encrypt(minimal_pdf(), PW)
    resp = client.post("/api/verify", files={"file": ("locked.pdf", enc, "application/pdf")})
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("needs_password") is True  # a recoverable prompt, NOT a verdict
    assert "verdict" not in body
    assert body.get("password_error") is None


def test_route_rejects_wrong_password(client):
    enc = _encrypt(minimal_pdf(), PW)
    resp = client.post(
        "/api/verify",
        files={"file": ("locked.pdf", enc, "application/pdf")},
        data={"pdf_password": "definitely-wrong"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("needs_password") is True
    assert body.get("password_error")  # an explicit, retryable error — not a confusing pipeline failure


def test_route_does_not_prompt_for_unencrypted_pdf(client):
    resp = client.post(
        "/api/verify", files={"file": ("open.pdf", minimal_pdf(), "application/pdf")}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("needs_password") is not True  # an open PDF is scored, never gated for a password
