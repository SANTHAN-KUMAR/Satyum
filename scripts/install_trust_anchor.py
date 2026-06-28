"""Validate and install a PUBLIC trust-anchor certificate (e.g. the CCA-India root) for Tier-1.

Satyum verifies a document's PAdES/CMS signature by chaining it to a pinned trust anchor. The demo
ships a stand-in demo root; for REAL DigiLocker / signed-bank-statement / signed-land-record documents
you must install the genuine **public** CCA-India root (https://www.cca.gov.in/ → repository of CA
certificates). This script does NOT invent a certificate — it validates one YOU provide and installs
it, printing exactly what it is so you can confirm provenance.

    python scripts/install_trust_anchor.py /path/to/cca-india-root.cer
    python scripts/install_trust_anchor.py root.pem --dir deploy/trust-anchors

Then point the backend at the directory:  SATYUM_TRUST_ANCHOR_DIR=<dir>  (or mount it in compose).

Honest boundary (CLAUDE.md §3.5): installing the root makes the chain *able* to verify real documents,
but you must still confirm end-to-end against a genuine signed sample before trusting the verdict in
production — this script cannot do that for you without such a sample.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization


def _load_cert(raw: bytes) -> x509.Certificate:
    """Parse PEM or DER — fail loudly if the bytes are not a real X.509 certificate."""
    try:
        return x509.load_pem_x509_certificate(raw)
    except ValueError:
        return x509.load_der_x509_certificate(raw)  # raises if neither -> not a cert


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate + install a public trust-anchor certificate.")
    ap.add_argument("cert", help="path to the PEM or DER certificate to install")
    ap.add_argument("--dir", default="deploy/trust-anchors",
                    help="target trust-anchor directory (default: deploy/trust-anchors)")
    args = ap.parse_args()

    src = Path(args.cert)
    if not src.is_file():
        print(f"ERROR: no such file: {src}", file=sys.stderr)
        return 2
    try:
        cert = _load_cert(src.read_bytes())
    except Exception as exc:  # noqa: BLE001 — report any parse failure plainly
        print(f"ERROR: not a valid X.509 certificate ({exc})", file=sys.stderr)
        return 2

    sha256 = cert.fingerprint(hashes.SHA256()).hex(":")
    print("Certificate validated:")
    print(f"  Subject     : {cert.subject.rfc4514_string()}")
    print(f"  Issuer      : {cert.issuer.rfc4514_string()}")
    print(f"  Valid from  : {cert.not_valid_before_utc.isoformat()}")
    print(f"  Valid until : {cert.not_valid_after_utc.isoformat()}")
    print(f"  SHA-256     : {sha256}")
    is_self_signed = cert.subject == cert.issuer
    print(f"  Self-signed : {is_self_signed}  ({'looks like a root' if is_self_signed else 'an intermediate — install the ROOT'})")

    target_dir = Path(args.dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    out = target_dir / (src.stem + ".pem")
    out.write_bytes(cert.public_bytes(serialization.Encoding.PEM))  # normalise to PEM
    print(f"\nInstalled -> {out}")
    print(f"Point the backend at it:  SATYUM_TRUST_ANCHOR_DIR={target_dir}")
    print("\nNEXT: verify end-to-end against a genuine signed document before trusting it in production.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
