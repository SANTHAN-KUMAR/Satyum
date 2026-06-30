"""Account Aggregator provider — real FIP detached-JWS signature verification; live-pull gated.

PROPOSAL-001 §4.4 / BUILD-MANIFEST (`GATED_BUT_REAL_SUBSTITUTE`): the Account Aggregator framework
delivers FIP-signed financial information. Two halves, honestly separated:

  * **Real, no-partner:** the FIP signs the FI payload with a **detached JWS** (RFC 7515 Appendix F).
    We verify that signature for real — reconstruct the JWS signing input
    ``BASE64URL(header) || '.' || BASE64URL(payload)`` and check it against a **pinned FIP public key**
    (a cert or raw public key shipped in the FIP-key store, mirroring the Tier-1 trust-anchor model).
    Supported algorithms: RS256, PS256 (RSA), ES256 (ECDSA P-256, JOSE raw ``r||s``). This answers the
    issuer+integrity question with no partner — exactly the substitute BUILD-MANIFEST names.
  * **Genuinely gated:** the production *live transaction-pull* requires RBI/SEBI-regulated FIU /
    NBFC-AA onboarding (a real regulatory credential). Its unique signal is data **freshness**, which a
    signature cannot replace. We label that gate precisely and **never** present fabricated data as
    live (CLAUDE.md §3.4). A real self-serve sandbox payload (Setu/Finvu/OneMoney) flows through the
    same verifier; only freshness is gated.

Fail-closed (§4): with no pinned FIP keys we cannot assert a chain → ``NOT_VERIFIED`` (never an
auto-pass). A present-but-failing signature → ``INVALID`` (tamper evidence). VERIFIED is earned only
by a signature that actually verifies against a pinned key (CLAUDE.md §3.1).
"""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Any

from providers.contracts import (
    ConsentArtifact,
    DocClass,
    DocRequest,
    ProvenanceMode,
    SignatureStatus,
    SourceResult,
)

logger = logging.getLogger(__name__)

# The precise gate for the half that genuinely needs a regulated credential (data freshness only).
_AA_PRODUCTION_GATE = (
    "Account Aggregator production live-pull requires RBI/SEBI-regulated FIU/NBFC-AA onboarding — the "
    "FIP signature is verified for real here; only live data FRESHNESS is gated. Never presented as live."
)

# P-256 ES256 signature is raw r||s, 32 bytes each (RFC 7518 §3.4).
_ES256_SIG_LEN = 64
_P256_COORD_LEN = 32


def _b64url_decode(segment: str) -> bytes:
    """Decode a base64url segment, restoring stripped padding (RFC 7515 §2)."""
    padding = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + padding)


def _b64url_encode(data: bytes) -> str:
    """base64url-encode without padding (the JWS wire form)."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _verify_signature(alg: str, public_key: Any, signing_input: bytes, signature: bytes) -> None:
    """Verify ``signature`` over ``signing_input`` with ``public_key`` per JOSE ``alg``.

    Raises ``cryptography.exceptions.InvalidSignature`` on a bad signature, or ``ValueError`` on an
    unsupported algorithm / malformed signature. Uses only ``cryptography`` primitives (verified API).
    """
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec, padding
    from cryptography.hazmat.primitives.asymmetric import utils as asym_utils

    if alg == "RS256":
        public_key.verify(signature, signing_input, padding.PKCS1v15(), hashes.SHA256())
    elif alg == "PS256":
        public_key.verify(
            signature,
            signing_input,
            # JOSE PS256 mandates salt length == hash length (RFC 7518 §3.5).
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=hashes.SHA256().digest_size),
            hashes.SHA256(),
        )
    elif alg == "ES256":
        if len(signature) != _ES256_SIG_LEN:
            raise ValueError(f"ES256 signature must be {_ES256_SIG_LEN} bytes (got {len(signature)})")
        r = int.from_bytes(signature[:_P256_COORD_LEN], "big")
        s = int.from_bytes(signature[_P256_COORD_LEN:], "big")
        der = asym_utils.encode_dss_signature(r, s)  # JOSE raw r||s -> DER for cryptography
        public_key.verify(der, signing_input, ec.ECDSA(hashes.SHA256()))
    else:
        raise ValueError(f"unsupported JWS alg {alg!r} (supported: RS256, PS256, ES256)")


def verify_detached_jws(jws: str, payload: bytes, public_key: Any) -> tuple[bool, dict[str, Any]]:
    """Verify a **detached** JWS (RFC 7515 App. F) over ``payload`` against ``public_key``.

    A detached JWS compact serialisation is ``BASE64URL(header) . '' . BASE64URL(signature)`` — the
    middle (payload) segment is empty and the real payload travels separately. We reconstruct the
    signing input from the header and the supplied detached ``payload`` and verify.

    Returns ``(ok, info)``; ``info`` carries the parsed ``alg`` / header or an ``error`` string. Pure
    and deterministic: the result changes with the payload, the signature, and the key (§3.1).
    """
    from cryptography.exceptions import InvalidSignature

    parts = jws.split(".")
    if len(parts) != 3:
        return False, {"error": "not a compact JWS (expected 3 dot-separated segments)"}
    header_b64, middle, sig_b64 = parts
    if middle != "":
        # We only accept a DETACHED JWS; an attached payload would be ambiguous about what was signed.
        return False, {"error": "expected a DETACHED JWS (the payload segment must be empty)"}
    try:
        header = json.loads(_b64url_decode(header_b64))
    except (ValueError, json.JSONDecodeError) as exc:
        return False, {"error": f"unparsable JWS header: {exc!r}"}
    alg = header.get("alg")
    if not isinstance(alg, str):
        return False, {"error": "JWS header missing a string 'alg'"}

    signing_input = header_b64.encode("ascii") + b"." + _b64url_encode(payload).encode("ascii")
    try:
        signature = _b64url_decode(sig_b64)
    except (ValueError, base64.binascii.Error) as exc:  # type: ignore[attr-defined]
        return False, {"error": f"unparsable signature segment: {exc!r}"}

    try:
        _verify_signature(alg, public_key, signing_input, signature)
    except InvalidSignature:
        return False, {"alg": alg, "error": "signature does not verify against the pinned FIP key"}
    except ValueError as exc:
        return False, {"alg": alg, "error": str(exc)}
    return True, {"alg": alg, "header": header}


def _load_fip_public_keys(key_dir: Path) -> list[tuple[str, Any]]:
    """Load pinned FIP public keys from PEM certificates or raw PEM public keys in ``key_dir``.

    Returns ``[(label, public_key)]``. A FIP key may be shipped as its X.509 cert (chaining, in
    production, to the CCA root) or as a bare public key; we accept either. Empty → caller fails closed.
    """
    from cryptography import x509
    from cryptography.hazmat.primitives.serialization import load_pem_public_key

    out: list[tuple[str, Any]] = []
    if not key_dir.is_dir():
        return out
    for path in sorted(key_dir.iterdir()):
        if not path.is_file() or path.suffix.lower() not in (".pem", ".crt", ".cer"):
            continue
        try:
            data = path.read_bytes()
        except OSError as exc:
            logger.warning("skipping unreadable FIP key %s: %s", path.name, exc)
            continue
        pub = None
        try:
            pub = x509.load_pem_x509_certificate(data).public_key()
        except (ValueError, TypeError):
            try:
                pub = load_pem_public_key(data)
            except (ValueError, TypeError) as exc:
                logger.warning("skipping unparsable FIP key %s: %s", path.name, exc)
                continue
        out.append((path.stem, pub))
    return out


class AccountAggregatorProvider:
    """AA source-pull adapter: verify a FIP detached-JWS-signed FI payload; live-pull gated.

    ``fetch`` payload is the AA FI response JSON bytes carrying the exact signed payload and the
    detached JWS. We verify the signature against the pinned FIP key store and report the real outcome
    plus the FIP-asserted freshness (the AA-unique signal). The expected input shape is::

        {"fipID": "...", "payload_b64": "<base64 of the exact signed FI bytes>",
         "signature": "<base64url(header)>..<base64url(sig)>", "freshness": "<iso-ts>"}

    ``payload_b64`` is the precise bytes the FIP signed (no canonicalisation ambiguity — we verify over
    exactly those bytes). The decoded FI JSON is parsed best-effort for freshness / masked account.
    """

    name = "account_aggregator"

    def __init__(self, fip_key_dir: str | None = None) -> None:
        # Pinned FIP-key store (config-over-hardcode, §5). Defaults to a sibling of the trust anchors.
        self._fip_key_dir = fip_key_dir

    def applicable(self, doc_request: DocRequest) -> bool:
        return doc_request.doc_class == DocClass.FINANCIAL_STATEMENT

    def _resolve_key_dir(self) -> Path:
        if self._fip_key_dir is not None:
            return Path(self._fip_key_dir)
        # Default location: backend/verification/fip_keys (public FIP certs only — never private keys).
        return Path(__file__).resolve().parent.parent / "verification" / "fip_keys"

    def fetch(
        self,
        consent: ConsentArtifact,
        doc_request: DocRequest,
        payload: bytes | None = None,
    ) -> SourceResult:
        if payload is None:
            # A live transaction-pull was requested — regulator-gated. Honest, never fabricated.
            return SourceResult(
                provider=self.name,
                doc_class=doc_request.doc_class,
                signature_status=SignatureStatus.NOT_VERIFIED,
                provenance_mode=ProvenanceMode.SANDBOX,
                gate=_AA_PRODUCTION_GATE,
                detail="live AA pull is FIU-onboarding-gated; supply a FIP-signed FI payload to verify",
            )
        return self._verify_fi_payload(doc_request, payload)

    def _verify_fi_payload(self, doc_request: DocRequest, payload: bytes) -> SourceResult:
        try:
            envelope = json.loads(payload)
        except (ValueError, json.JSONDecodeError) as exc:
            return SourceResult(
                provider=self.name, doc_class=doc_request.doc_class,
                signature_status=SignatureStatus.NOT_VERIFIED,
                provenance_mode=ProvenanceMode.SANDBOX,
                detail=f"AA FI payload is not valid JSON (fail-closed): {exc}",
            )

        jws = envelope.get("signature")
        payload_b64 = envelope.get("payload_b64")
        fip_id = envelope.get("fipID")
        if not isinstance(jws, str) or not isinstance(payload_b64, str):
            return SourceResult(
                provider=self.name, doc_class=doc_request.doc_class,
                signature_status=SignatureStatus.ABSENT,
                provenance_mode=ProvenanceMode.SANDBOX,
                detail="AA FI payload carries no detached JWS signature / signed bytes — cannot verify",
            )

        try:
            signed_bytes = _b64url_decode(payload_b64)
        except (ValueError, base64.binascii.Error) as exc:  # type: ignore[attr-defined]
            return SourceResult(
                provider=self.name, doc_class=doc_request.doc_class,
                signature_status=SignatureStatus.NOT_VERIFIED,
                provenance_mode=ProvenanceMode.SANDBOX,
                detail=f"AA signed-bytes are not valid base64 (fail-closed): {exc}",
            )

        keys = _load_fip_public_keys(self._resolve_key_dir())
        if not keys:
            # Fail-closed: with no pinned FIP key we cannot assert the signer (§4/§10) — never auto-pass.
            return SourceResult(
                provider=self.name, doc_class=doc_request.doc_class,
                signature_status=SignatureStatus.NOT_VERIFIED,
                provenance_mode=ProvenanceMode.SANDBOX,
                gate=_AA_PRODUCTION_GATE,
                detail=f"no pinned FIP keys in {self._resolve_key_dir()} — cannot verify FIP signature",
            )

        verified_label: str | None = None
        last_info: dict[str, Any] = {}
        for label, pub in keys:
            ok, info = verify_detached_jws(jws, signed_bytes, pub)
            last_info = info
            if ok:
                verified_label = label
                break

        freshness = self._extract_freshness(signed_bytes, envelope)
        measurements = {
            "fip_id": fip_id,
            "jws_alg": last_info.get("alg"),
            "pinned_fip_keys": [label for label, _ in keys],
            "freshness_note": "FIP-asserted; live-pull freshness is gated (production FIU onboarding)",
        }

        if verified_label is not None:
            return SourceResult(
                provider=self.name, doc_class=doc_request.doc_class,
                signature_status=SignatureStatus.VERIFIED,
                provenance_mode=ProvenanceMode.SANDBOX,
                issuer=fip_id or verified_label,
                freshness_ts=freshness,
                gate=_AA_PRODUCTION_GATE,  # the signature is real; only live freshness is gated
                detail=(
                    f"FIP signature verified ({measurements['jws_alg']}) against pinned key "
                    f"{verified_label!r} — issuer+integrity proven; production live-pull gated"
                ),
                measurements=measurements,
                structured_json=self._safe_json(signed_bytes),
            )

        # Present but failed against every pinned key -> tamper / wrong-signer evidence.
        return SourceResult(
            provider=self.name, doc_class=doc_request.doc_class,
            signature_status=SignatureStatus.INVALID,
            provenance_mode=ProvenanceMode.SANDBOX,
            issuer=fip_id,
            detail=(
                "FIP signature present but does NOT verify against any pinned FIP key — "
                f"tampering or untrusted signer ({last_info.get('error', 'no detail')})"
            ),
            measurements=measurements,
        )

    @staticmethod
    def _extract_freshness(signed_bytes: bytes, envelope: dict[str, Any]) -> str | None:
        """Best-effort FIP-asserted freshness timestamp (the AA-unique signal). None if unavailable."""
        data = AccountAggregatorProvider._safe_json(signed_bytes) or {}
        for key in ("freshness", "timestamp", "ts", "generatedAt"):
            val = data.get(key) if isinstance(data, dict) else None
            if isinstance(val, str):
                return val
        val = envelope.get("freshness")
        return val if isinstance(val, str) else None

    @staticmethod
    def _safe_json(data: bytes) -> dict[str, Any] | None:
        try:
            parsed = json.loads(data)
        except (ValueError, json.JSONDecodeError):
            return None
        return parsed if isinstance(parsed, dict) else None
