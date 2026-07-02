"""A second real cloud reader: Google Gemini, behind the same :class:`VLMExtractor` interface.

Two purposes: (1) it proves the interface is genuinely swappable — Claude and Gemini are drop-in
alternates selected by config, no downstream change (ADR-004 §7); (2) Gemini's strong multilingual +
2D-grounding makes it a real option for non-English documents alongside Claude.

It uses Gemini's structured-JSON mode (``response_mime_type="application/json"``) constrained by the
*same* tool schema (``schema.build_tool_schema``) and governed by the *same* injection-hardened system
prompt (``schema.SYSTEM_PROMPT``) — so both readers are held to identical rules: transcription only,
normalized boxes, no judgement, no laundering. The downstream cross-read + builder validate the output
regardless of which reader produced it.

As with the Anthropic client, the prompt construction and the response parse are pure and unit-tested;
the live call needs an API key and is exercised against real documents.
"""

from __future__ import annotations

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


class GeminiVLMExtractor(VLMExtractor):
    """Google Gemini as a box-grounded transcription reader (structured-JSON output)."""

    def __init__(
        self,
        *,
        model: str,
        api_key: str | None,
        temperature: float = 0.0,
        timeout: float = 60.0,
        max_tokens: int = 8192,
        handled_scripts: frozenset[str] = frozenset({"latin", "indic"}),
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
        """Parse Gemini's JSON text into a validated :class:`RawExtraction`. Pure; fail-closed on junk."""
        cleaned = text.strip()
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
            from google import genai  # lazy import: optional backend

            self._client = genai.Client(api_key=self._api_key)
        return self._client

    def extract(self, page: PageImage, *, doc_type_hint: str | None = None) -> RawExtraction:
        if not self.available:
            raise VLMUnavailable(f"{self.name}: no API key configured")
        try:
            from google import genai  # noqa: F401  — presence check
            from google.genai import errors as genai_errors
            from google.genai import types
        except ImportError as exc:
            raise VLMUnavailable(f"{self.name}: google-genai SDK not installed") from exc

        client = self._ensure_client()
        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=self._temperature,
            response_mime_type="application/json",
            http_options=types.HttpOptions(timeout=int(self._timeout * 1000)),
            max_output_tokens=self._max_tokens,
            # Gemini 2.5+ models think by default, and thinking tokens are drawn from the SAME
            # max_output_tokens budget as the final answer — with no cap, a dense page (many
            # transaction rows -> a large structured JSON reply) can have its entire token budget
            # consumed by internal reasoning before any JSON is emitted, truncating or emptying the
            # response ("response was not valid JSON" / "empty response"). This task is pure
            # box-grounded TRANSCRIPTION with no judgement (SYSTEM_PROMPT), so reasoning tokens buy
            # nothing here — disable thinking outright so the full budget goes to the actual output.
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        )
        contents = [
            types.Part.from_bytes(data=page.png_bytes, mime_type=_IMAGE_MIME_TYPE),
            self.build_prompt(doc_type_hint=doc_type_hint),
        ]
        try:
            response = client.models.generate_content(model=self.model, contents=contents, config=config)
        except genai_errors.ClientError as exc:
            code = getattr(exc, "code", None)
            if code in (401, 403):
                raise VLMUnavailable(f"{self.name}: authentication failed (HTTP {code})") from exc
            if code == 429:
                # Quota exhausted is a transient availability gate, not a processing fault.
                # Treat as NOT_EVALUATED so the pipeline degrades gracefully without an ERROR signal.
                raise VLMUnavailable(f"{self.name}: quota exhausted — retry later (HTTP 429)") from exc
            # Other client errors: surface the HTTP code only, not the full quota-details JSON blob.
            raise VLMExtractionError(f"{self.name}: client error HTTP {code}") from exc
        except genai_errors.APIError as exc:
            code = getattr(exc, "code", None)
            raise VLMExtractionError(f"{self.name}: API error HTTP {code}") from exc
        except Exception as exc:  # noqa: BLE001 — fail-closed on anything unexpected
            raise VLMExtractionError(f"{self.name}: unexpected failure: {type(exc).__name__}") from exc

        # Diagnose a token-budget truncation explicitly (finish_reason != STOP, e.g. "MAX_TOKENS")
        # instead of letting it surface as an opaque "not valid JSON" further down — this is exactly
        # the failure mode max_output_tokens/thinking_config above are meant to prevent, so a future
        # recurrence (an unusually dense page) should say so plainly, not look like a parsing bug.
        candidates = getattr(response, "candidates", None) or []
        finish_reason = getattr(candidates[0], "finish_reason", None) if candidates else None
        if finish_reason is not None and str(finish_reason).upper() not in ("STOP", "FINISHREASON.STOP"):
            raise VLMExtractionError(
                f"{self.name}: response cut off before completion (finish_reason={finish_reason}) — "
                "likely hit the output token limit on a dense page"
            )

        text = getattr(response, "text", None)
        if not text:
            raise VLMExtractionError(f"{self.name}: empty response")
        return self.parse_response_text(text)
