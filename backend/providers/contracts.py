"""Stable contracts for the source-pull provider layer (PROPOSAL-001 §4.4).

These types are the published boundary between the onboarding orchestration and any concrete
provider (DigiLocker, Account Aggregator, PAN, …). A provider takes a :class:`DocRequest` plus an
explicit :class:`ConsentArtifact` and returns exactly one :class:`SourceResult` — the orchestration
depends only on this interface, never on a provider's wire shape (Dependency Inversion, CLAUDE.md §4).

The integrity invariant of this layer (CLAUDE.md §3.1/§3.4): a :class:`SourceResult` must report the
*real* outcome of a *real* verification. ``provenance_mode`` and ``signature_status`` are facts about
what was actually checked; a ``gate`` is set if — and only if — a regulated credential or live
data-freshness that genuinely cannot be obtained no-partner is involved, and it names that gate
precisely. Fabricated data is never presented as live.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field


class SignatureStatus(StrEnum):
    """The cryptographic-signature outcome of a source document.

    This mirrors the Tier-1 vocabulary in ``verification/signature.py`` (verified / tampered /
    absent) so a source-pull result composes cleanly with the verification core. ``NOT_VERIFIED`` is
    distinct from ``ABSENT``: it means *we did not attempt or could not complete* the cryptographic
    check on this path (e.g. a gated live-pull), and is never an auto-pass.
    """

    VERIFIED = "VERIFIED"          # signature present, valid, chains to a pinned anchor
    INVALID = "INVALID"            # signature present but failed (forged chain / appended bytes / bad digest)
    ABSENT = "ABSENT"             # no signature present on the artifact
    NOT_VERIFIED = "NOT_VERIFIED"  # not cryptographically checked on this path (e.g. gated) — never a pass


class ProvenanceMode(StrEnum):
    """How a document reached us — the provenance waterfall position (PROPOSAL-001 §2.6/§4).

    ``SOURCE_PULL`` (signed, pulled/derived from the issuer) is the strongest; ``MANUAL_UPLOAD`` is
    the fallback; ``LIVE_CAPTURE`` is the Tier-3 escalation for un-sourceable wet-ink documents.
    ``SANDBOX`` means a *real* sandbox client + *real* signature verifier, with production
    live-data-freshness honestly gated (BUILD-MANIFEST: Account Aggregator).
    """

    SOURCE_PULL = "SOURCE_PULL"
    SANDBOX = "SANDBOX"
    MANUAL_UPLOAD = "MANUAL_UPLOAD"
    LIVE_CAPTURE = "LIVE_CAPTURE"


class DocClass(StrEnum):
    """The class of document being requested — drives which providers are applicable."""

    FINANCIAL_STATEMENT = "financial_statement"  # primary target document (CLAUDE.md §1)
    IDENTITY = "identity"                         # PAN / Aadhaar-offline / DigiLocker ID docs
    LAND_RECORD = "land_record"                   # RoR / EC
    LEGAL_DEED = "legal_deed"
    OTHER = "other"


class DocRequest(BaseModel):
    """What the applicant is being asked to provide. Providers decide applicability from this."""

    doc_class: DocClass
    issuer_hint: str | None = None        # normalised issuer key (e.g. "sbi") if known
    applicant_ref: str | None = None      # an opaque, non-PII case reference — NOT a raw identifier
    share_code: str | None = None         # Aadhaar offline e-KYC ZIP share-code (password), when applicable
    claimant_name: str | None = None      # applicant name as on the document (for PAN name-match)
    dob: str | None = None                # applicant date of birth, DD/MM/YYYY (for PAN verification)
    pdf_password: str | None = None       # unlocks an encrypted PDF in memory to verify its signature


class ConsentArtifact(BaseModel):
    """An explicit, purpose-bound consent record for a source-pull (DPDP Act 2023 — PROPOSAL-001 §7.3).

    Source-pull touches a citizen's data at its issuer, so it is consent-gated by law. This artifact
    is the auditable proof of consent: who consented, for what purpose, over what scope, when. It is
    frozen — a consent record must not mutate after capture. ``consent_id`` is the reference the audit
    ledger and the provider both cite.

    NB: this is the *artifact* (the record of consent). The real DigiLocker/AA OAuth + consent-handle
    exchange that mints it in production is a partner-gated flow (Path A / FIU onboarding); the
    no-partner build verifies the *signature* on documents the applicant supplies, under a consent
    record captured in the onboarding UI.
    """

    model_config = {"frozen": True}

    consent_id: str
    purpose: str                          # e.g. "loan_underwriting_document_verification"
    doc_class: DocClass
    granted_at: str                       # ISO-8601 timestamp (caller-supplied; audited)
    applicant_ref: str | None = None


class SourceResult(BaseModel):
    """The normalised output of any provider. The orchestration consumes only this shape.

    Exactly one of ``signed_bytes`` / ``structured_json`` is the payload (a signed PDF, or signed
    structured data such as an AA FI block); both may be ``None`` for a purely-attestational result
    (e.g. PAN structure validation, which yields a fact, not a document). ``gate`` is non-empty iff a
    regulated/credentialed step was genuinely required and not performed — and then it names that gate
    exactly (CLAUDE.md §3.4). ``signature_status`` and ``provenance_mode`` are the load-bearing,
    honest facts the Evidence Pack surfaces to the underwriter.
    """

    provider: str
    doc_class: DocClass
    signature_status: SignatureStatus
    provenance_mode: ProvenanceMode
    issuer: str | None = None             # extracted from the verified signer cert, when available
    freshness_ts: str | None = None       # issuer-asserted freshness (AA) — the signal a signature can't give
    gate: str | None = None               # precise regulatory/credential gate, or None when fully real
    detail: str = ""                      # human-readable summary for the UI / evidence pack
    measurements: dict[str, Any] = Field(default_factory=dict)
    # The payload, when the provider yields a verifiable document to feed the verification core.
    # These are NEVER logged or persisted (CLAUDE.md §10); they live only for the request's lifetime.
    signed_bytes: bytes | None = Field(default=None, exclude=True, repr=False)
    structured_json: dict[str, Any] | None = Field(default=None, exclude=True, repr=False)

    @property
    def verified_at_source(self) -> bool:
        """True iff a real signature verified and chained to a pinned anchor (integrity at the root)."""
        return self.signature_status == SignatureStatus.VERIFIED


@runtime_checkable
class SourceProvider(Protocol):
    """Every source-pull adapter is one of these (PROPOSAL-001 §4.4).

    Contract:
      * ``name`` is the stable provider key used by the registry and the API route.
      * ``applicable(doc_request)`` decides whether this provider can serve the request.
      * ``fetch(consent, doc_request, payload)`` performs the *real* verification/derivation and
        returns exactly one :class:`SourceResult`. It must NOT raise for ordinary bad input — it
        returns a ``SourceResult`` whose ``signature_status`` reflects the failure (fail-closed, §4);
        the service layer still guards against unexpected exceptions.
      * It must NEVER fabricate ``VERIFIED`` — only a real signature that chains to a pinned anchor
        earns it (CLAUDE.md §3.1).
    """

    name: str

    def applicable(self, doc_request: DocRequest) -> bool: ...

    def fetch(
        self,
        consent: ConsentArtifact,
        doc_request: DocRequest,
        payload: bytes | None = None,
    ) -> SourceResult: ...
