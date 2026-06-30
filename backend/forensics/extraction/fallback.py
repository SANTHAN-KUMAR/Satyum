"""Resilient multi-reader fallback for Layer 2 (CLAUDE.md §4 — graceful degradation, no SPOF).

A single cloud VLM is a single point of failure: a quota cap, an auth blip, or a transient server
error on the primary reader would otherwise gate the entire understanding layer to NOT_EVALUATED and
collapse discrimination (genuine and tampered both fall through to the peripheral signals). The
:class:`FallbackExtractor` removes that: it holds an ordered list of readers and, on each extraction,
tries them in turn until one returns a transcription, only surfacing a failure when *every* reader is
exhausted.

This is a transparent :class:`VLMExtractor` wrapper — it composes with :class:`LanguageRoutedExtractor`
and changes nothing downstream. The security boundary is unchanged: each reader is held to the same
schema + injection-hardened prompt, and the deterministic cross-read re-verifies whichever reader's
output survives. The wrapper has no decision authority; it only chooses *which reader read*, never what
the figure is or whether the document is genuine.

Error semantics (fail-closed):
  * ``VLMUnavailable`` from a reader (quota/auth/not-configured) → try the next reader.
  * ``VLMExtractionError`` from a reader (a real fault on the attempt) → try the next reader.
  * if all readers fail: re-raise a ``VLMExtractionError`` if any reader actually *attempted* and
    faulted (fail-closed → ERROR/REVIEW), else ``VLMUnavailable`` (honest pending — nothing was
    configured to run).
"""

from __future__ import annotations

import logging

from forensics.extraction.interface import (
    PageImage,
    RawExtraction,
    VLMExtractionError,
    VLMExtractor,
    VLMUnavailable,
)

logger = logging.getLogger(__name__)


class FallbackExtractor(VLMExtractor):
    """Try an ordered list of readers until one transcribes the page (primary → fallback → …)."""

    def __init__(self, readers: list[VLMExtractor]) -> None:
        if not readers:
            raise ValueError("FallbackExtractor needs at least one reader")
        self._readers = readers

    @property
    def name(self) -> str:
        # The primary reader's name identifies the chain in logs/audit; the audit also records the
        # actual model that produced each extraction via RawExtraction.model_id, so a fallback hit is
        # never silently attributed to the primary.
        return self._readers[0].name

    @property
    def available(self) -> bool:
        return any(r.available for r in self._readers)

    def handles_script(self, family: str) -> bool:
        return any(r.handles_script(family) for r in self._readers)

    def extract(self, page: PageImage, *, doc_type_hint: str | None = None) -> RawExtraction:
        attempted_and_failed = False
        last_error: Exception | None = None

        for reader in self._readers:
            if not reader.available:
                continue
            try:
                result = reader.extract(page, doc_type_hint=doc_type_hint)
            except VLMUnavailable as exc:
                # Configured but unusable right now (quota/auth) — degrade to the next reader.
                logger.warning("extraction: reader %s unavailable, trying fallback: %s", reader.name, exc)
                last_error = exc
                continue
            except VLMExtractionError as exc:
                # A real fault on this attempt — try the next reader rather than fail the page outright.
                logger.warning("extraction: reader %s errored, trying fallback: %s", reader.name, exc)
                attempted_and_failed = True
                last_error = exc
                continue

            if reader is not self._readers[0]:
                logger.info("extraction: served by fallback reader %s", reader.name)
            return result

        # Every reader exhausted. Fail closed: an attempted-and-faulted chain is an ERROR (→ REVIEW);
        # a chain where nothing was usable is an honest gate (→ NOT_EVALUATED/pending).
        detail = str(last_error) if last_error is not None else "no reader configured"
        if attempted_and_failed:
            raise VLMExtractionError(f"all VLM readers failed; last: {detail}")
        raise VLMUnavailable(f"no VLM reader available; last: {detail}")
