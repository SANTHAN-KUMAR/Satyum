"""A provider-agnostic VLM reader for ANY OpenAI-compatible ``/chat/completions`` endpoint.

One extractor, many backends (CLAUDE.md §11 — the reader is swappable behind ``VLMExtractor``). Point
``base_url`` at whichever host serves a capable vision model and you get a real, box-grounded reader
without a vendor SDK:

  * **Cloudflare Workers AI** — ``https://api.cloudflare.com/client/v4/accounts/<acct>/ai/v1`` with
    e.g. ``@cf/mistralai/mistral-small-3.1-24b-instruct`` (tool-calling; fills the structured schema
    Llama-4-Scout cannot) or ``@cf/google/gemma-3-12b-it``.
  * **OpenRouter** — ``https://openrouter.ai/api/v1`` with ``qwen/qwen-2.5-vl-72b-instruct`` etc.
  * **Together / DeepInfra / Fireworks** — their ``/v1`` base + a hosted Qwen2.5-VL / Llama-3.2-Vision.
  * **Ollama (local, last resort)** — ``http://localhost:11434/v1`` with ``qwen2.5vl:7b`` (no key).

It uses the *same* injection-hardened ``SYSTEM_PROMPT`` + ``build_tool_schema`` + ``parse_tool_input``
as every other reader, so the trust boundary (transcription-only, box-grounded, cross-read-verified
downstream) is identical regardless of which host produced the JSON. Pure plumbing is unit-testable;
the live call uses ``httpx`` (already a dependency) — no extra SDK.
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


class OpenAICompatibleVLMExtractor(VLMExtractor):
    """Box-grounded transcription reader over any OpenAI-compatible chat-completions vision endpoint."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str | None,
        label: str | None = None,
        temperature: float = 0.0,
        timeout: float = 90.0,
        max_tokens: int = 8192,
        require_key: bool = True,
        handled_scripts: frozenset[str] = frozenset({"latin"}),
        use_json_response_format: bool = True,
    ) -> None:
        self._base_url = (base_url or "").rstrip("/")
        self.model = model
        self._api_key = (api_key or "").strip()
        self._label = label or "openai-compatible"
        self._temperature = temperature
        self._timeout = timeout
        self._max_tokens = max_tokens
        # Local backends (Ollama) need no key; hosted ones do. ``require_key=False`` lets a keyless
        # local endpoint be ``available`` so the analyzer actually calls it instead of gating.
        self._require_key = require_key
        # Whether to send ``response_format={"type": "json_object"}``. Some vision endpoints reject
        # strict JSON mode with an image attached (HTTP 400 — see KNOWN_ISSUES #1); we default it ON
        # (most hosts honour it) but self-heal a 400 by retrying without it, and the prompt+parser
        # guarantee a bare JSON object regardless. Configurable so a known-incompatible host opts out.
        self._use_json_response_format = use_json_response_format
        self._handled_scripts = handled_scripts
        self._prompt_hash = prompt_fingerprint(f"{self._label}:{model}")

    @property
    def name(self) -> str:
        return f"vlm:{self.model}"

    @property
    def available(self) -> bool:
        return bool(self._base_url) and (bool(self._api_key) or not self._require_key)

    def handles_script(self, family: str) -> bool:
        return family in self._handled_scripts

    # --- pure, unit-testable plumbing -------------------------------------------------------------

    def build_prompt(self, *, doc_type_hint: str | None = None) -> str:
        instruction = _user_instruction()
        if doc_type_hint:
            instruction += f"\nThe document is expected to be of type: {doc_type_hint}."
        return instruction

    def parse_response_text(self, text: str) -> RawExtraction:
        """Parse the model's JSON text into a validated :class:`RawExtraction`. Pure; fail-closed."""
        cleaned = (text or "").strip()
        if cleaned.startswith("```"):  # strip a ```json fence if the model wrapped the object
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

    def extract(self, page: PageImage, *, doc_type_hint: str | None = None) -> RawExtraction:
        if not self.available:
            raise VLMUnavailable(f"{self.name}: no base_url/API key configured")
        import httpx

        b64 = base64.b64encode(page.png_bytes).decode("ascii")
        base_payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
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
            ],
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
        }
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        def _post(json_mode: bool) -> httpx.Response:
            payload = dict(base_payload)
            if json_mode:
                payload["response_format"] = {"type": "json_object"}
            try:
                return httpx.post(
                    f"{self._base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=self._timeout,
                )
            except httpx.HTTPError as exc:  # network/timeout ⇒ fail-closed ERROR upstream
                raise VLMExtractionError(f"{self.name}: transport error: {type(exc).__name__}") from exc

        response = _post(self._use_json_response_format)
        # Self-heal the documented JSON-mode rejection (KNOWN_ISSUES #1): a vision endpoint that 400s on
        # strict JSON mode with an image attached. Retry once WITHOUT it before failing — the prompt
        # already requests a bare JSON object and the parser fence-strips + validates it.
        if response.status_code == 400 and self._use_json_response_format:
            logger.warning(
                "extraction: %s rejected strict JSON mode (HTTP 400); retrying without it", self.name
            )
            response = _post(False)

        if response.status_code in (401, 403):  # bad/missing key ⇒ unconfigured (gate, not fault)
            raise VLMUnavailable(f"{self.name}: authentication failed (HTTP {response.status_code})")
        if response.status_code == 429:  # quota/rate ⇒ availability gate
            raise VLMUnavailable(f"{self.name}: rate limited / quota exhausted")
        if response.status_code >= 400:
            raise VLMExtractionError(f"{self.name}: API error HTTP {response.status_code}")

        try:
            body = response.json()
            text = body["choices"][0]["message"]["content"]
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            raise VLMExtractionError(f"{self.name}: malformed response envelope") from exc
        if not text:
            raise VLMExtractionError(f"{self.name}: empty response")
        return self.parse_response_text(text)
