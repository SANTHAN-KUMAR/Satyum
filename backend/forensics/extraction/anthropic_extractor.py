"""The cloud POC extractor: Claude reads a page into a :class:`RawExtraction` (ADR-004 §7, §5).

This is a complete, real client — vision input + a forced structured tool call at temperature 0. It is
swappable behind :class:`~forensics.extraction.interface.VLMExtractor`: the same interface accepts a
Gemini client or a self-hosted Qwen2.5-VL endpoint with no change downstream.

What makes it safe to use in a fraud pipeline lives upstream (the prompt + schema in ``schema.py``,
which forbid judgement/laundering) and downstream (the OCR cross-read in ``cross_read.py`` and the
builder's hostile-input validation). This module's job is narrow: turn pixels into the typed,
box-grounded transcription, and fail honestly when it cannot.

Design for verifiability: request construction (:meth:`build_request`) and response parsing
(:meth:`extract_tool_input`) are pure functions, unit-tested without a network call — so the exact
payload (temperature 0, the image block, the forced tool, the system prompt) and the parse are proven
real even though the live round-trip needs an API key and is exercised against real documents.
"""

from __future__ import annotations

import base64
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
    TOOL_NAME,
    build_tool_schema,
    parse_tool_input,
    prompt_fingerprint,
)

logger = logging.getLogger(__name__)

# Claude expects base64 image data with one of a fixed set of media types; we render PDF pages to PNG.
_IMAGE_MEDIA_TYPE = "image/png"

_TOOL_DESCRIPTION = (
    "Record every value LITERALLY printed on the document page, each with a tight normalized bounding "
    "box and a confidence. Transcription only — never compute, correct, or reconcile a value."
)

# Short user turn alongside the image. Deliberately carries NO expected values and NO arithmetic "
# context (ADR-004 §5.1): the reader must never be primed toward a 'consistent' number.
_USER_INSTRUCTION = (
    "Transcribe this document page using the {tool} tool. Record exactly what is printed, with a "
    "bounding box and confidence for every value. Do not compute or correct anything."
)


class AnthropicVLMExtractor(VLMExtractor):
    """Claude (Sonnet 4.6 default / Opus 4.8 hard-doc lane) as a box-grounded transcription reader."""

    def __init__(
        self,
        *,
        model: str,
        api_key: str | None,
        max_tokens: int = 4096,
        timeout: float = 60.0,
        max_retries: int = 2,
        handled_scripts: frozenset[str] = frozenset({"latin"}),
    ) -> None:
        self.model = model
        self._api_key = (api_key or "").strip()
        self._max_tokens = max_tokens
        self._timeout = timeout
        self._max_retries = max_retries
        self._handled_scripts = handled_scripts
        self._prompt_hash = prompt_fingerprint(model)
        self._client: Any = None  # lazily constructed on first real call

    @property
    def name(self) -> str:
        return f"vlm:{self.model}"

    @property
    def available(self) -> bool:
        """Configured to run iff an API key is present. No key ⇒ the analyzer gates to NOT_EVALUATED."""
        return bool(self._api_key)

    def handles_script(self, family: str) -> bool:
        return family in self._handled_scripts

    # --- pure, unit-testable request/response plumbing --------------------------------------------

    def build_request(self, page: PageImage, *, doc_type_hint: str | None = None) -> dict[str, Any]:
        """Construct the exact ``messages.create`` kwargs. Pure — no network, fully assertable.

        Forces the structured tool (``tool_choice``), pins ``temperature=0`` for reproducibility
        (ADR-004 §5.5/§5.6), and sends the page as a base64 PNG image block followed by a neutral
        instruction that carries no expected values.
        """
        image_b64 = base64.standard_b64encode(page.png_bytes).decode("ascii")
        instruction = _USER_INSTRUCTION.format(tool=TOOL_NAME)
        if doc_type_hint:
            instruction += f"\nThe document is expected to be of type: {doc_type_hint}."
        return {
            "model": self.model,
            "max_tokens": self._max_tokens,
            "temperature": 0.0,
            "system": SYSTEM_PROMPT,
            "tools": [
                {
                    "name": TOOL_NAME,
                    "description": _TOOL_DESCRIPTION,
                    "input_schema": build_tool_schema(),
                }
            ],
            "tool_choice": {"type": "tool", "name": TOOL_NAME},
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": _IMAGE_MEDIA_TYPE,
                                "data": image_b64,
                            },
                        },
                        {"type": "text", "text": instruction},
                    ],
                }
            ],
        }

    @staticmethod
    def extract_tool_input(message: Any) -> dict[str, Any]:
        """Pull the structured tool input out of a Messages response. Pure; duck-typed for testability.

        Returns the model's tool-call ``input`` dict, or raises :class:`VLMExtractionError` if the model
        did not emit the forced tool call (fail-closed — never fabricate an empty extraction).
        """
        for block in getattr(message, "content", None) or []:
            if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == TOOL_NAME:
                tool_input = getattr(block, "input", None)
                if isinstance(tool_input, dict):
                    return tool_input
        raise VLMExtractionError("model did not return the structured tool call")

    # --- the live call ----------------------------------------------------------------------------

    def _ensure_client(self) -> Any:
        if self._client is None:
            import anthropic  # lazy: a missing SDK degrades to a gate, never an import-time crash

            self._client = anthropic.Anthropic(
                api_key=self._api_key, timeout=self._timeout, max_retries=self._max_retries
            )
        return self._client

    def extract(self, page: PageImage, *, doc_type_hint: str | None = None) -> RawExtraction:
        if not self.available:
            raise VLMUnavailable(f"{self.name}: no API key configured")
        try:
            import anthropic
        except ImportError as exc:  # declared dependency; degrade to a gate if absent
            raise VLMUnavailable(f"{self.name}: anthropic SDK not installed") from exc

        client = self._ensure_client()
        request = self.build_request(page, doc_type_hint=doc_type_hint)
        try:
            message = client.messages.create(**request)
        except anthropic.AuthenticationError as exc:  # bad/expired key ⇒ unconfigured, not a fault
            raise VLMUnavailable(f"{self.name}: authentication failed") from exc
        except anthropic.APIError as exc:  # network/server/timeout ⇒ fail-closed ERROR upstream
            raise VLMExtractionError(f"{self.name}: API error: {exc}") from exc
        except Exception as exc:  # noqa: BLE001 — any unexpected failure fails closed, never a pass
            raise VLMExtractionError(f"{self.name}: unexpected failure: {exc!r}") from exc

        raw = self.extract_tool_input(message)
        return parse_tool_input(raw, model_id=self.model, prompt_hash=self._prompt_hash)
