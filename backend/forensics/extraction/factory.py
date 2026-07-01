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
from forensics.extraction.openai_compatible_extractor import OpenAICompatibleVLMExtractor
from forensics.extraction.routing import FAMILY_INDIC, LanguageRoutedExtractor

logger = logging.getLogger(__name__)

# Providers whose clients are implemented + verified against their SDKs.
_IMPLEMENTED = {
    "anthropic", "gemini", "groq",
    "cloudflare", "openai_compatible", "openrouter", "together", "deepinfra", "fireworks", "ollama",
}
# Recognised but not yet wired (honest gate, not a fake client). See module docstring.
_GATED = {"sarvam"}


def _make_extractors(
    *,
    provider: str,
    model: str,
    api_keys_str: str,
    settings: Settings,
    handled_scripts: frozenset[str],
) -> list[VLMExtractor]:
    """Build concrete extractors for each API key provided (comma-separated), or [] if gated/unknown."""
    provider = (provider or "").strip().lower()
    if provider in ("", "none"):
        return []

    keys = [k.strip() for k in (api_keys_str or "").split(",") if k.strip()]
    if not keys:
        keys = [""]  # Allow providers that don't need a key (like ollama) to run once

    extractors: list[VLMExtractor] = []
    for api_key in keys:
        ext = None
        if provider == "anthropic":
            ext = AnthropicVLMExtractor(
                model=model or "claude-sonnet-4-6",
                api_key=api_key,
                max_tokens=settings.vlm_max_tokens,
                timeout=settings.vlm_timeout_seconds,
                handled_scripts=handled_scripts,
            )
        elif provider == "gemini":
            ext = GeminiVLMExtractor(
                model=model or "gemini-2.5-flash",
                api_key=api_key,
                timeout=settings.vlm_timeout_seconds,
                handled_scripts=handled_scripts,
            )
        elif provider == "groq":
            ext = GroqVLMExtractor(
                model=model or "qwen/qwen3.6-27b",
                api_key=api_key,
                max_tokens=settings.vlm_max_tokens,
                timeout=settings.vlm_timeout_seconds,
                handled_scripts=handled_scripts,
                # Groq's vision endpoints sometimes hard-400 on strict JSON mode when an image is
                # attached (KNOWN_ISSUES #1). Ship it off by default so the fallback lane never crashes;
                # the injection-hardened prompt + fence-stripping parser still yield a validated object.
                use_json_response_format=False,
            )
        elif provider == "cloudflare":
            acct = (settings.vlm_cloudflare_account_id or "").strip()
            if not acct:
                logger.warning("VLM provider 'cloudflare' needs SATYUM_VLM_CLOUDFLARE_ACCOUNT_ID — gating")
                return []
            ext = OpenAICompatibleVLMExtractor(
                base_url=f"https://api.cloudflare.com/client/v4/accounts/{acct}/ai/v1",
                model=model or "@cf/mistralai/mistral-small-3.1-24b-instruct",
                api_key=api_key,
                label="cloudflare",
                timeout=settings.vlm_timeout_seconds,
                max_tokens=settings.vlm_max_tokens,
                handled_scripts=handled_scripts,
            )
        elif provider in ("openai_compatible", "openrouter", "together", "deepinfra", "fireworks", "ollama"):
            base = (settings.vlm_base_url or "").strip()
            if not base:
                logger.warning("VLM provider %r needs SATYUM_VLM_BASE_URL — gating", provider)
                return []
            ext = OpenAICompatibleVLMExtractor(
                base_url=base,
                model=model,
                api_key=api_key,
                label=provider,
                timeout=settings.vlm_timeout_seconds,
                max_tokens=settings.vlm_max_tokens,
                require_key=(provider != "ollama"),
                handled_scripts=handled_scripts,
            )
        elif provider in _GATED:
            if not extractors:
                logger.warning(
                    "VLM provider %r is recognised (the Indic specialist) but its client is not yet wired. "
                    "Falling back to the default reader.",
                    provider,
                )
            return []
            
        if ext is not None:
            extractors.append(ext)

    if not extractors and provider not in _GATED:
        logger.warning("VLM provider %r is unknown; no extractor constructed", provider)
    return extractors


def build_default_extractor(settings: Settings) -> VLMExtractor | None:
    """The extractor the Layer-2 analyzer uses, per ``SATYUM_VLM_*`` config. ``None`` ⇒ NOT_EVALUATED gate.

    Wraps the default reader in a :class:`LanguageRoutedExtractor` when an Indic specialist is
    configured, so vernacular documents route to it; otherwise returns the default reader directly.
    """
    primary = _make_extractors(
        provider=settings.vlm_provider,
        model=settings.vlm_model,
        api_keys_str=settings.vlm_api_key,
        settings=settings,
        handled_scripts=frozenset({"latin"}),
    )
    fallback = _make_extractors(
        provider=settings.vlm_fallback_provider,
        model=settings.vlm_fallback_model,
        api_keys_str=settings.vlm_fallback_api_key,
        settings=settings,
        handled_scripts=frozenset({"latin"}),
    )
    fallback2 = _make_extractors(
        provider=settings.vlm_fallback2_provider,
        model=settings.vlm_fallback2_model,
        api_keys_str=settings.vlm_fallback2_api_key,
        settings=settings,
        handled_scripts=frozenset({"latin"}),
    )
    
    # Compose the massive chain. FallbackExtractor natively moves through the list on failure!
    chain = primary + fallback + fallback2
    if not chain:
        return None
    default: VLMExtractor = chain[0] if len(chain) == 1 else FallbackExtractor(chain)

    indic = _make_extractors(
        provider=settings.vlm_indic_provider,
        model=settings.vlm_indic_model,
        api_keys_str=settings.vlm_indic_api_key,
        settings=settings,
        handled_scripts=frozenset({"indic", "latin"}),
    )
    if indic:
        return LanguageRoutedExtractor(
            default=default,
            specialists={FAMILY_INDIC: indic[0]},
            escalate_below_confidence=settings.vlm_escalate_below_confidence,
        )
    return default
