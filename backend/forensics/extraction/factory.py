"""Construct the configured :class:`VLMExtractor` from settings (ADR-004 §7 — config-driven swap).

Which reader runs, and whether an Indic specialist is registered for vernacular routing, is entirely a
configuration decision — no code change to add Gemini alongside Claude, or to point the Indic lane at a
self-hosted model. The factory is the single place that maps ``SATYUM_VLM_*`` settings to concrete
extractors.

Honest backend status (CLAUDE.md §3.4, §6): ``anthropic`` and ``gemini`` are fully implemented and
verified against their installed SDKs. ``sarvam`` is a recognised provider — the designated sovereign
Indic specialist — but its concrete client is intentionally NOT fabricated here: Sarvam Vision is an
async-job API whose per-field bounding-box response schema we have not been able to confirm against a
live key, and writing a parser against guessed field names would be exactly the kind of fake the
integrity charter forbids. Selecting it logs a clear gate and yields no extractor (the default still
runs); the client lands the moment its response contract is confirmed.
"""

from __future__ import annotations

import logging

from app.config import Settings
from forensics.extraction.anthropic_extractor import AnthropicVLMExtractor
from forensics.extraction.fallback import FallbackExtractor
from forensics.extraction.gemini_extractor import GeminiVLMExtractor
from forensics.extraction.groq_extractor import GroqVLMExtractor
from forensics.extraction.interface import VLMExtractor
from forensics.extraction.routing import FAMILY_INDIC, LanguageRoutedExtractor

logger = logging.getLogger(__name__)

# Providers whose clients are implemented + verified against their SDKs.
_IMPLEMENTED = {"anthropic", "gemini", "groq"}
# Recognised but not yet wired (honest gate, not a fake client). See module docstring.
_GATED = {"sarvam"}


def _make_extractor(
    *,
    provider: str,
    model: str,
    api_key: str,
    settings: Settings,
    handled_scripts: frozenset[str],
) -> VLMExtractor | None:
    """Build one concrete extractor, or ``None`` if the provider is gated/unknown (never a fake)."""
    provider = (provider or "").strip().lower()
    if provider in ("", "none"):
        return None
    if provider == "anthropic":
        return AnthropicVLMExtractor(
            model=model or "claude-sonnet-4-6",
            api_key=api_key,
            max_tokens=settings.vlm_max_tokens,
            timeout=settings.vlm_timeout_seconds,
            handled_scripts=handled_scripts,
        )
    if provider == "gemini":
        return GeminiVLMExtractor(
            model=model or "gemini-2.5-flash",
            api_key=api_key,
            timeout=settings.vlm_timeout_seconds,
            handled_scripts=handled_scripts,
        )
    if provider == "groq":
        return GroqVLMExtractor(
            model=model or "meta-llama/llama-4-scout-17b-16e-instruct",
            api_key=api_key,
            max_tokens=settings.vlm_max_tokens,
            timeout=settings.vlm_timeout_seconds,
            handled_scripts=handled_scripts,
        )
    if provider in _GATED:
        logger.warning(
            "VLM provider %r is recognised (the Indic specialist) but its client is not yet wired: "
            "Sarvam Vision's bounding-box response schema is unconfirmed without a live key. Falling "
            "back to the default reader; the specialist lands once its response contract is confirmed.",
            provider,
        )
        return None
    logger.warning("VLM provider %r is unknown; no extractor constructed", provider)
    return None


def build_default_extractor(settings: Settings) -> VLMExtractor | None:
    """The extractor the Layer-2 analyzer uses, per ``SATYUM_VLM_*`` config. ``None`` ⇒ NOT_EVALUATED gate.

    Wraps the default reader in a :class:`LanguageRoutedExtractor` when an Indic specialist is
    configured, so vernacular documents route to it; otherwise returns the default reader directly.
    """
    primary = _make_extractor(
        provider=settings.vlm_provider,
        model=settings.vlm_model,
        api_key=settings.vlm_api_key,
        settings=settings,
        handled_scripts=frozenset({"latin"}),
    )
    fallback = _make_extractor(
        provider=settings.vlm_fallback_provider,
        model=settings.vlm_fallback_model,
        api_key=settings.vlm_fallback_api_key,
        settings=settings,
        handled_scripts=frozenset({"latin"}),
    )
    # Compose the default reader with its fallback (ADR-004 §7 resilience). If only the fallback is
    # configured it simply becomes the default — a configured reader is never wasted.
    chain = [r for r in (primary, fallback) if r is not None]
    if not chain:
        return None
    default: VLMExtractor = chain[0] if len(chain) == 1 else FallbackExtractor(chain)

    indic = _make_extractor(
        provider=settings.vlm_indic_provider,
        model=settings.vlm_indic_model,
        api_key=settings.vlm_indic_api_key,
        settings=settings,
        handled_scripts=frozenset({"indic", "latin"}),
    )
    if indic is not None:
        return LanguageRoutedExtractor(
            default=default,
            specialists={FAMILY_INDIC: indic},
            escalate_below_confidence=settings.vlm_escalate_below_confidence,
        )
    return default
