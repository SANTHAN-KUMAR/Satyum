"""Provider registry — the one place that knows the concrete source-pull adapter set.

Mirrors ``app/registry_assembly.py`` for analyzers: the onboarding service depends only on this
registry, never on a concrete provider (Dependency Inversion, CLAUDE.md §4). Registration is eager
and explicit; a provider is selected by name (the API route) or by applicability to a
:class:`~providers.contracts.DocRequest`.
"""

from __future__ import annotations

from providers.aadhaar import AadhaarOfflineProvider
from providers.account_aggregator import AccountAggregatorProvider
from providers.contracts import DocRequest, SourceProvider
from providers.digilocker import DigiLockerProvider
from providers.pan import PanProvider


class ProviderRegistry:
    def __init__(self) -> None:
        self._by_name: dict[str, SourceProvider] = {}
        self._order: list[SourceProvider] = []

    def register(self, provider: SourceProvider) -> SourceProvider:
        if provider.name in self._by_name:
            raise ValueError(f"duplicate provider name {provider.name!r}")
        self._by_name[provider.name] = provider
        self._order.append(provider)
        return provider

    def get(self, name: str) -> SourceProvider | None:
        return self._by_name.get(name)

    def applicable(self, doc_request: DocRequest) -> list[SourceProvider]:
        """Providers that can serve this request, in registration order (source-pull preference)."""
        return [p for p in self._order if p.applicable(doc_request)]

    def all(self) -> list[SourceProvider]:
        return list(self._order)


def build_provider_registry(
    trust_anchor_dir: str | None = None,
    fip_key_dir: str | None = None,
    uidai_cert_dir: str | None = None,
) -> ProviderRegistry:
    """Construct and return the fully-wired provider registry.

    Args:
        trust_anchor_dir: pinned PKI trust store for DigiLocker Path B (defaults to settings).
        fip_key_dir: pinned FIP-key store for Account Aggregator signature verification.
        uidai_cert_dir: pinned UIDAI cert store for Aadhaar offline e-KYC XML verification.
    """
    registry = ProviderRegistry()
    # Order = source-pull preference: signed-document pulls first, then attestational checks.
    registry.register(DigiLockerProvider(anchor_dir=trust_anchor_dir))
    registry.register(AccountAggregatorProvider(fip_key_dir=fip_key_dir))
    registry.register(AadhaarOfflineProvider(uidai_cert_dir=uidai_cert_dir))
    registry.register(PanProvider())
    return registry
