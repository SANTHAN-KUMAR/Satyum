"""Privacy primitives for the shared fraud registry (PROPOSAL-001 §6.2 / §6.8).

Two constructions, each with an HONESTLY-STATED privacy property (CLAUDE.md §3.1/§3.4 — never
overclaim the crypto):

  * **Salted perceptual hash** — ``salted = phash XOR consortium_salt`` (256-bit). XOR **preserves
    Hamming distance** (``H(a⊕s, b⊕s) == H(a, b)``), so members who share the salt can still match
    resubmitted/near-duplicate documents by Hamming radius, while a party WITHOUT the salt sees only
    opaque bitstrings it cannot align to any external pHash corpus. A pHash is already non-invertible
    to the document; the salt additionally de-correlates the stored values from any outside index.

  * **HMAC entity token** — ``token = HMAC-SHA256(pepper, normalise(value))``. The pepper is held only
    by consortium members (never the neutral registry operator), so identifiers (PAN / account /
    phone) become non-invertible, enumeration-resistant tokens. Exact-match set membership on tokens
    answers "have we seen this exact PAN/account before?" without sharing the raw identifier.

**What this gives, stated plainly:** non-invertible, pepper/salt-gated set membership across banks —
the registry operator never sees a raw document, image, name, or account number, and cannot invert a
token or align a salted hash to an external corpus. **What it does NOT give (named, not hidden):**
full DH/OPRF Private Set Intersection that *also* hides a querier's lookup tokens from the operator.
That query-hiding hardening is a Stage-3 item (§6.8); this is the salted-hash / tokenised-membership
form PROPOSAL-001 §6.2 names as the Stage-2 mechanism. We do not call it cryptographic PSI.
"""

from __future__ import annotations

import hashlib
import hmac
import re

# A pHash here is the 256-bit (64 hex char) imagehash pHash (hash_size=16 — see forensics/phash.py).
PHASH_HEX_LEN = 64
PHASH_BITS = 256


def salt_phash(phash_hex: str, salt_hex: str) -> str:
    """Return ``phash XOR salt`` as a 64-char hex string. Hamming-distance preserving.

    Raises ``ValueError`` if either input is not a 256-bit hex value — a malformed salt must never
    silently weaken the construction.
    """
    if len(phash_hex) != PHASH_HEX_LEN:
        raise ValueError(f"phash must be {PHASH_HEX_LEN} hex chars (got {len(phash_hex)})")
    if len(salt_hex) != PHASH_HEX_LEN:
        raise ValueError(f"consortium salt must be {PHASH_HEX_LEN} hex chars (got {len(salt_hex)})")
    xored = int(phash_hex, 16) ^ int(salt_hex, 16)
    return f"{xored:0{PHASH_HEX_LEN}x}"


def hamming_hex(a_hex: str, b_hex: str) -> int:
    """Hamming distance between two equal-length hex bitstrings (popcount of XOR)."""
    if len(a_hex) != len(b_hex):
        raise ValueError("hamming_hex requires equal-length hex strings")
    return bin(int(a_hex, 16) ^ int(b_hex, 16)).count("1")


# --- entity normalisation (so the same identifier tokenises identically across banks, §11 risk) ---

def _normalise_pan(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def _normalise_account(value: str) -> str:
    return re.sub(r"[^0-9]", "", value)


def _normalise_phone(value: str) -> str:
    digits = re.sub(r"[^0-9]", "", value)
    return digits[-10:] if len(digits) >= 10 else digits  # last 10 digits (India mobile)


def _normalise_generic(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().upper())


_NORMALISERS = {
    "pan": _normalise_pan,
    "account": _normalise_account,
    "account_number": _normalise_account,
    "payout_account": _normalise_account,
    "phone": _normalise_phone,
    "ifsc": _normalise_pan,  # alnum, upper
    # "device" and "employer" fall through to the generic normaliser (upper + collapse whitespace).
}


def normalise_entity(kind: str, value: str) -> str:
    """Canonicalise an identifier so the SAME value tokenises identically at every bank (§11)."""
    return _NORMALISERS.get(kind, _normalise_generic)(value)


def entity_token(kind: str, value: str, pepper: bytes) -> str:
    """HMAC-SHA256 token of a normalised identifier under the consortium ``pepper``.

    Non-invertible and enumeration-resistant (the pepper is secret to members). The ``kind`` is mixed
    in so a PAN and an account number with the same digits cannot collide to the same token.
    """
    norm = normalise_entity(kind, value)
    msg = f"{kind}:{norm}".encode()
    return hmac.new(pepper, msg, hashlib.sha256).hexdigest()


def entity_tokens(fields: dict[str, str], pepper: bytes) -> dict[str, str]:
    """Tokenise a mapping of ``{kind: value}`` (empty/None values skipped). Returns ``{kind: token}``."""
    out: dict[str, str] = {}
    for kind, value in fields.items():
        if value:
            out[kind] = entity_token(kind, value, pepper)
    return out
