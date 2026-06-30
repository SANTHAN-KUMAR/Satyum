"""Source-pull orchestration: select a provider, fetch under consent, guard fail-closed.

Thin, pure orchestration over the provider registry (CLAUDE.md §4). The route layer adds HTTP and
the consent audit; this layer guarantees the cardinal rule — a provider that raises an *unexpected*
exception degrades to a fail-closed :class:`SourceResult` (``NOT_VERIFIED``), never a crash and never
a fabricated pass.
"""

from __future__ import annotations

import logging

from providers.contracts import (
    ConsentArtifact,
    DocRequest,
    ProvenanceMode,
    SignatureStatus,
    SourceResult,
)
from providers.registry import ProviderRegistry

logger = logging.getLogger(__name__)


class UnknownProviderError(LookupError):
    """Raised when a named provider is not registered (the route maps this to HTTP 404)."""


def pull_source(
    registry: ProviderRegistry,
    provider_name: str,
    consent: ConsentArtifact,
    doc_request: DocRequest,
    payload: bytes | None = None,
) -> SourceResult:
    """Run ``provider_name``'s fetch under ``consent``; fail closed on any unexpected error.

    Raises :class:`UnknownProviderError` for an unregistered provider (a client error, surfaced as
    404). Consent's ``doc_class`` must match the request's — a consent record is purpose- and
    scope-bound (DPDP §7.3); a mismatch is refused fail-closed rather than silently honoured.
    """
    provider = registry.get(provider_name)
    if provider is None:
        raise UnknownProviderError(provider_name)

    if consent.doc_class != doc_request.doc_class:
        return SourceResult(
            provider=provider_name,
            doc_class=doc_request.doc_class,
            signature_status=SignatureStatus.NOT_VERIFIED,
            provenance_mode=ProvenanceMode.MANUAL_UPLOAD,
            detail=(
                f"consent scope ({consent.doc_class.value}) does not cover the requested document "
                f"class ({doc_request.doc_class.value}) — refused fail-closed (DPDP purpose limitation)"
            ),
        )

    try:
        return provider.fetch(consent, doc_request, payload)
    except Exception as exc:  # noqa: BLE001 — deliberate fail-closed boundary (§4)
        logger.exception("source provider %r raised unexpectedly", provider_name)
        return SourceResult(
            provider=provider_name,
            doc_class=doc_request.doc_class,
            signature_status=SignatureStatus.NOT_VERIFIED,
            provenance_mode=ProvenanceMode.MANUAL_UPLOAD,
            detail=f"provider error (fail-closed): {exc!r}",
        )
