"""Thin OpenAI-compatible client for the interpretability layer (narrator + copilot).

This layer only *explains* the immutable evidence pack — it never decides anything (the firewall
discards any narrative that contradicts the deterministic verdict). It is a **text** model and is
configured independently of the vision reader: set ``SATYUM_INTERPRET_*`` to point it at a SOTA text
reasoner (e.g. DeepSeek v4) while a separate vision model does the document reading. When the
``interpret_*`` settings are unset it transparently falls back to the ``vlm_*`` reader credential, so a
single-key deployment keeps working.
"""

from __future__ import annotations

from typing import Any

from openai import AsyncOpenAI

from app.config import settings

# Known text-LLM hosts whose base URL we can derive from the provider name alone. For any other
# OpenAI-compatible host, set SATYUM_INTERPRET_BASE_URL explicitly.
_PROVIDER_BASE_URLS = {
    "deepseek": "https://api.deepseek.com",
    "groq": "https://api.groq.com/openai/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "openai": "https://api.openai.com/v1",
}


def _resolve_interpreter() -> tuple[str | None, str, str]:
    """Resolve (base_url, api_key, model) for the interpretation LLM.

    Prefers the decoupled ``interpret_*`` settings; falls back to the ``vlm_*`` reader so a one-key
    deployment still narrates. Pure config resolution — no network — so it is unit-testable.
    """
    provider = (settings.interpret_provider or settings.vlm_provider or "").lower()

    api_key = settings.interpret_api_key or settings.vlm_api_key
    model = settings.interpret_model or settings.vlm_model

    # Base URL: explicit override wins, then a provider-derived default, then the vlm base URL.
    base_url: str | None = settings.interpret_base_url or None
    if not base_url:
        if provider == "cloudflare" and settings.vlm_cloudflare_account_id:
            base_url = (
                f"https://api.cloudflare.com/client/v4/accounts/"
                f"{settings.vlm_cloudflare_account_id}/ai/v1"
            )
        elif provider in _PROVIDER_BASE_URLS:
            base_url = _PROVIDER_BASE_URLS[provider]
        else:
            base_url = settings.vlm_base_url or None

    return base_url, api_key, model


def get_openai_client() -> tuple[AsyncOpenAI, str]:
    """Return an AsyncOpenAI client for the interpretation LLM, plus the model id."""
    base_url, api_key, model = _resolve_interpreter()
    client = AsyncOpenAI(base_url=base_url, api_key=api_key or "")
    return client, model


def interpreter_available() -> bool:
    """True when an interpretation LLM is actually configured (a real key resolved)."""
    _, api_key, _ = _resolve_interpreter()
    return bool(api_key)


async def generate_completion(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    response_format: dict[str, Any] | None = None,
) -> Any:
    """Generate a single completion. Optionally supports tools and a JSON response format.

    Returns the message object from the first choice. Raises on transport/API error so the caller
    (narrator/copilot) degrades to the deterministic fallback (CLAUDE.md §4 fail-safe).
    """
    client, model = get_openai_client()

    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": 0.0,
        "max_tokens": settings.interpret_max_tokens,
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
    if response_format:
        kwargs["response_format"] = response_format

    response = await client.chat.completions.create(**kwargs)
    return response.choices[0].message
