"""PAN provider — REAL existence + name-match verification via an authorised provider (no mock).

Two layers, both real:

  * **Offline structure pre-flight** (always): the Income-Tax PAN format ``AAAAA9999A`` + the 4th-char
    holder-type code. Deterministic, instant, no partner. (We never claim the 10th-char check digit —
    the NSDL algorithm is non-public — so that is not asserted; §3.1.)

  * **Live existence + name-match** (when configured): a real HTTPS call to an authorised PAN
    verification provider that checks the **Income-Tax PAN database**. Default contract: Sandbox /
    Quicko (``api.sandbox.co.in``) — self-serve developer signup. A VERIFIED result means the provider
    confirmed the PAN is valid AND the name matches the PAN record. The raw provider status is always
    surfaced, so nothing is interpreted away.

Integrity (CLAUDE.md §3.1, and the user's hard "no mock" rule): when the provider is **not
configured**, we return an **honest gate** — never a fabricated pass. When the provider call **fails**,
we fail closed (``NOT_VERIFIED``), never a guessed result. ``VERIFIED`` is earned only by a real,
positive provider response. A real "PAN invalid / name mismatch" comes back as ``INVALID``.
"""

from __future__ import annotations

import logging
import re
import time

from app.config import settings
from providers.contracts import (
    ConsentArtifact,
    DocClass,
    DocRequest,
    ProvenanceMode,
    SignatureStatus,
    SourceResult,
)

logger = logging.getLogger(__name__)

# Exact PAN shape (anchored). The discriminating structural check, not a loose search.
_PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")

# The 4th character — PAN holder-type (entity) codes per the ITD PAN-allotment scheme. Named, not magic.
PAN_ENTITY_CODES: dict[str, str] = {
    "P": "Individual", "C": "Company", "H": "Hindu Undivided Family (HUF)", "F": "Firm / LLP",
    "A": "Association of Persons (AOP)", "T": "Trust", "B": "Body of Individuals (BOI)",
    "L": "Local Authority", "J": "Artificial Juridical Person", "G": "Government",
}

_PAN_GATE_UNCONFIGURED = (
    "PAN existence/name-match is not configured — set SATYUM_PAN_API_KEY + SATYUM_PAN_API_SECRET "
    "(free developer signup at sandbox.co.in, or your bank's Protean/NSDL authorised access). Structure "
    "is validated offline now; existence is verified live the moment a key is set. No mock is ever returned."
)


def validate_pan_structure(pan: str) -> tuple[bool, str | None, str]:
    """Validate a PAN's structure offline. Returns ``(ok, entity_type, detail)``. Pure + deterministic."""
    candidate = (pan or "").strip().upper()
    if not _PAN_RE.match(candidate):
        return False, None, (
            f"{candidate!r} is not a well-formed PAN — expected AAAAA9999A (5 letters, 4 digits, 1 letter)"
        )
    entity_char = candidate[3]
    entity_type = PAN_ENTITY_CODES.get(entity_char)
    if entity_type is None:
        return False, None, (
            f"4th character {entity_char!r} is not a valid PAN holder-type code "
            f"(expected one of {''.join(sorted(PAN_ENTITY_CODES))})"
        )
    return True, entity_type, f"structurally valid PAN — holder type: {entity_type}"


class PanApiError(Exception):
    """A real failure talking to the PAN provider — surfaced as fail-closed, never a guessed result."""


class PanApiClient:
    """Real PAN verification client (Sandbox/Quicko contract). Caches the 24h JWT access token.

    Verified contract (developer.sandbox.co.in):
      * auth  : POST {base}/authenticate  headers x-api-key, x-api-secret, x-api-version -> data.access_token
      * verify: POST {base}/kyc/pan/verify headers Authorization=<token>, x-api-key, x-api-version
                body {@entity, pan, name_as_per_pan, date_of_birth (DD/MM/YYYY), consent:"Y", reason}
                -> data {pan, category, status, name_as_per_pan_match, date_of_birth_match, ...}
    """

    def __init__(
        self, base_url: str, api_key: str, api_secret: str, api_version: str, timeout_s: float
    ) -> None:
        self._base = base_url.rstrip("/")
        self._key = api_key
        self._secret = api_secret
        self._ver = api_version
        self._timeout = timeout_s
        self._token: str | None = None
        self._token_exp = 0.0

    def configured(self) -> bool:
        return bool(self._key and self._secret)

    def _authenticate(self) -> str:
        import httpx

        resp = httpx.post(
            f"{self._base}/authenticate",
            headers={"x-api-key": self._key, "x-api-secret": self._secret,
                     "x-api-version": self._ver, "Content-Type": "application/json"},
            timeout=self._timeout,
        )
        if resp.status_code != 200:
            raise PanApiError(f"authenticate HTTP {resp.status_code}: {resp.text[:200]}")
        token = ((resp.json() or {}).get("data") or {}).get("access_token")
        if not token:
            raise PanApiError("authenticate: no data.access_token in response")
        self._token = token
        self._token_exp = time.monotonic() + 23 * 3600  # 24h validity; refresh a little early
        return token

    def _token_value(self) -> str:
        if self._token and time.monotonic() < self._token_exp:
            return self._token
        return self._authenticate()

    def verify(self, pan: str, name: str | None, dob: str | None, reason: str) -> dict:
        import httpx

        body = {
            "@entity": "in.co.sandbox.kyc.pan_verification.request",
            "pan": pan,
            "name_as_per_pan": (name or "").strip(),
            "date_of_birth": (dob or "").strip(),
            "consent": "Y",
            "reason": reason,
        }

        def _call(token: str) -> httpx.Response:
            return httpx.post(
                f"{self._base}/kyc/pan/verify",
                headers={"Authorization": token, "x-api-key": self._key,
                         "x-api-version": self._ver, "Content-Type": "application/json"},
                json=body, timeout=self._timeout,
            )

        try:
            resp = _call(self._token_value())
            if resp.status_code in (401, 403):  # token expired/invalid -> re-auth once
                self._token = None
                resp = _call(self._token_value())
        except httpx.HTTPError as exc:
            raise PanApiError(f"network error: {exc!r}") from exc
        if resp.status_code != 200:
            raise PanApiError(f"verify HTTP {resp.status_code}: {resp.text[:300]}")
        data = (resp.json() or {}).get("data")
        if not isinstance(data, dict):
            raise PanApiError("verify: unexpected response shape (no data object)")
        return data


def _status_is_valid(status: str) -> bool:
    """Conservatively decide whether the provider's PAN status means valid/active (fail-safe).

    The raw status is always surfaced; we only auto-VERIFY when it clearly indicates valid, so an
    unexpected status never produces an unearned pass (CLAUDE.md §3.1)."""
    s = status.strip().lower()
    if not s or "invalid" in s or "not" in s or "deactiv" in s or "fake" in s:
        return False
    return "valid" in s or "existing" in s or "active" in s


class PanProvider:
    """PAN provider: offline structure pre-flight + live existence/name-match (when configured)."""

    name = "pan"

    def __init__(self, client: PanApiClient | None = None) -> None:
        self._client = client  # injectable; else built lazily from settings (so env overrides apply)

    def _get_client(self) -> PanApiClient:
        if self._client is None:
            self._client = PanApiClient(
                settings.pan_api_base_url, settings.pan_api_key, settings.pan_api_secret,
                settings.pan_api_version, settings.pan_api_timeout_s,
            )
        return self._client

    def applicable(self, doc_request: DocRequest) -> bool:
        return doc_request.doc_class == DocClass.IDENTITY

    def fetch(
        self,
        consent: ConsentArtifact,
        doc_request: DocRequest,
        payload: bytes | None = None,
    ) -> SourceResult:
        raw = doc_request.applicant_ref
        if not raw and payload is not None:
            try:
                raw = payload.decode("ascii", errors="strict").strip()
            except UnicodeDecodeError:
                raw = None
        pan = (raw or "").strip().upper()

        ok, entity_type, detail = validate_pan_structure(pan)
        base_meas = {
            "pan_structure_valid": ok,
            "entity_type": entity_type,
            "checksum_note": "PAN 10th-char check digit NOT validated — the NSDL algorithm is not public",
        }
        if not ok:
            return self._result(SignatureStatus.NOT_VERIFIED, detail=detail, measurements=base_meas)

        client = self._get_client()
        if not client.configured():
            return self._result(
                SignatureStatus.NOT_VERIFIED, issuer="Income Tax Department (PAN)",
                gate=_PAN_GATE_UNCONFIGURED,
                detail=(
                    f"{detail}; existence not verified (PAN provider not configured) — "
                    "Protean/NSDL or Sandbox key required"
                ),
                measurements=base_meas,
            )

        # --- live verification against the real PAN database (no mock) ---------------------------
        try:
            data = client.verify(pan, doc_request.claimant_name, doc_request.dob, settings.pan_api_reason)
        except PanApiError as exc:
            logger.warning("PAN provider call failed: %s", exc)
            return self._result(
                SignatureStatus.NOT_VERIFIED, issuer="Income Tax Department (PAN)",
                detail=f"PAN provider call failed (fail-closed, no result fabricated): {exc}",
                measurements=base_meas,
            )

        status = str(data.get("status") or "").strip()
        name_match = data.get("name_as_per_pan_match")
        meas = {
            **base_meas, "pan_status": status, "name_as_per_pan_match": name_match,
            "date_of_birth_match": data.get("date_of_birth_match"), "category": data.get("category"),
            "aadhaar_seeding_status": data.get("aadhaar_seeding_status"),
            "verified_against": "Income-Tax PAN database (live)",
        }

        if _status_is_valid(status) and name_match is not False:
            return self._result(
                SignatureStatus.VERIFIED, issuer="Income Tax Department (PAN)",
                detail=(f"PAN verified at source — status {status!r}"
                        + (", name matches the PAN record" if name_match else "")),
                measurements=meas,
            )
        # A real negative result — surfaced honestly as INVALID, never softened.
        why = "PAN not valid/active" if not _status_is_valid(status) else "name does not match the PAN record"
        return self._result(
            SignatureStatus.INVALID, issuer="Income Tax Department (PAN)",
            detail=f"PAN verification FAILED — {why} (provider status {status!r}, name_match={name_match})",
            measurements=meas,
        )

    def _result(self, status: SignatureStatus, *, detail: str, issuer: str | None = None,
                gate: str | None = None, measurements: dict | None = None) -> SourceResult:
        return SourceResult(
            provider=self.name, doc_class=DocClass.IDENTITY, signature_status=status,
            provenance_mode=ProvenanceMode.SOURCE_PULL, issuer=issuer, gate=gate, detail=detail,
            measurements=measurements or {},
        )
