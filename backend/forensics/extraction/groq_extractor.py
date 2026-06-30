"""A third real cloud reader: Groq (Llama-4 Scout vision), behind the same :class:`VLMExtractor`.

Its purpose is resilience: Groq is wired as the **fallback** reader so a single cloud VLM is no longer a
point of failure (CLAUDE.md §4 — graceful degradation). When the primary reader is quota-exhausted or
errors on a page, the Layer-2 analyzer transparently retries with this one before failing closed.

Like the Gemini client it uses structured-JSON mode (``response_format={"type": "json_object"}``)
constrained by the *same* tool schema (``schema.build_tool_schema``) and governed by the *same*
injection-hardened system prompt (``schema.SYSTEM_PROMPT``) — every reader is held to identical rules:
transcription only, normalized boxes, no judgement, no laundering. The downstream cross-read + builder
validate the output regardless of which reader produced it, so the security boundary is unchanged.

Groq's OpenAI-compatible chat API takes the page as a base64 ``image_url`` data URL. The prompt
construction and response parse are pure and unit-testable; the live call needs an API key and is
exercised against real documents.
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Any

from forensics.extraction.interface import (
    PageImage,
    RawExtraction,
    VLMExtractionError,
    VLMExtractor,
    VLMUnavailable,
)
from forensics.extraction.schema import (
    SYSTEM_PROMPT,
    build_tool_schema,
    parse_tool_input,
    prompt_fingerprint,
)

logger = logging.getLogger(__name__)

_IMAGE_MIME_TYPE = "image/png"


def _user_instruction() -> str:
    """The neutral instruction + the exact JSON shape to return. Carries no expected values (§5.1)."""
    schema_json = json.dumps(build_tool_schema(), separators=(",", ":"), sort_keys=True)
    return (
        "Transcribe this document page. Return ONLY a JSON object that conforms to the following JSON "
        "Schema — no markdown, no commentary. Record exactly what is printed, with a normalized "
        "bounding box [x, y, w, h] in [0,1] and a confidence in [0,1] for every value. Do not compute, "
        "correct, or reconcile any value.\n\nJSON Schema:\n" + schema_json
    )


class GroqVLMExtractor(VLMExtractor):
    """Groq-hosted Llama-4 Scout as a box-grounded transcription reader (structured-JSON output)."""

    def __init__(
        self,
        *,
        model: str,
        api_key: str | None,
        temperature: float = 0.0,
        timeout: float = 60.0,
        max_tokens: int = 8192,
        handled_scripts: frozenset[str] = frozenset({"latin"}),
    ) -> None:
        self.model = model
        self._api_key = (api_key or "").strip()
        self._temperature = temperature
        self._timeout = timeout
        self._max_tokens = max_tokens
        self._handled_scripts = handled_scripts
        self._prompt_hash = prompt_fingerprint(model)
        self._client: Any = None

    @property
    def name(self) -> str:
        return f"vlm:{self.model}"

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    def handles_script(self, family: str) -> bool:
        return family in self._handled_scripts

    # --- pure, unit-testable plumbing -------------------------------------------------------------

    def build_prompt(self, *, doc_type_hint: str | None = None) -> str:
        instruction = _user_instruction()
        if doc_type_hint:
            instruction += f"\nThe document is expected to be of type: {doc_type_hint}."
        return instruction

    def parse_response_text(self, text: str) -> RawExtraction:
        """Parse Groq's JSON text into a validated :class:`RawExtraction`. Pure; fail-closed on junk."""
        cleaned = (text or "").strip()
        # Defensive: strip a ```json fence if the model wrapped the object despite instructions.
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:]
            cleaned = cleaned.strip()
        try:
            raw = json.loads(cleaned)
        except (json.JSONDecodeError, ValueError) as exc:
            raise VLMExtractionError(f"{self.name}: response was not valid JSON") from exc
        if not isinstance(raw, dict):
            raise VLMExtractionError(f"{self.name}: response JSON was not an object")
        return parse_tool_input(raw, model_id=self.model, prompt_hash=self._prompt_hash)

    # --- the live call ----------------------------------------------------------------------------

    def _ensure_client(self) -> Any:
        if self._client is None:
            from groq import Groq  # lazy import: optional backend

            self._client = Groq(api_key=self._api_key, timeout=self._timeout)
        return self._client

    def extract(self, page: PageImage, *, doc_type_hint: str | None = None) -> RawExtraction:
        if not self.available:
            raise VLMUnavailable(f"{self.name}: no API key configured")
        try:
            from groq import (  # noqa: F401  — Groq is a presence check
                APIError,
                AuthenticationError,
                Groq,
                PermissionDeniedError,
                RateLimitError,
            )
        except ImportError as exc:
            raise VLMUnavailable(f"{self.name}: groq SDK not installed") from exc

        client = self._ensure_client()
        b64 = base64.b64encode(page.png_bytes).decode("ascii")
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": self.build_prompt(doc_type_hint=doc_type_hint)},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{_IMAGE_MIME_TYPE};base64,{b64}"},
                    },
                ],
            },
        ]
        try:
            response = client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=self._temperature,
                max_tokens=self._max_tokens,
                response_format={"type": "json_object"},
            )
        except (AuthenticationError, PermissionDeniedError) as exc:  # bad/expired key ⇒ unconfigured
            raise VLMUnavailable(f"{self.name}: authentication failed") from exc
        except RateLimitError as exc:  # quota/rate ⇒ availability gate, not a processing fault
            raise VLMUnavailable(f"{self.name}: rate limited / quota exhausted") from exc
        except APIError as exc:  # network/server/timeout ⇒ fail-closed ERROR upstream
            raise VLMExtractionError(f"{self.name}: API error: {type(exc).__name__}") from exc
        except Exception as exc:  # noqa: BLE001 — any unexpected failure fails closed, never a pass
            raise VLMExtractionError(f"{self.name}: unexpected failure: {type(exc).__name__}") from exc

        try:
            text = response.choices[0].message.content
        except (AttributeError, IndexError) as exc:
            raise VLMExtractionError(f"{self.name}: malformed response envelope") from exc
        if not text:
            raise VLMExtractionError(f"{self.name}: empty response")
        return self.parse_response_text(text)
