"""Content-addressed replay cache for Layer 2 (CLAUDE.md §4 resilience / §7 perf; ADR-004 §5.6).

A cloud VLM read is the one network-dependent, rate-limited step in an otherwise local, deterministic
pipeline. Re-reading the *identical* page bytes over the network on every request is both wasteful and
fragile: a quota cap or a transient outage gates the whole understanding layer to NOT_EVALUATED, even
for a document the reader already transcribed perfectly minutes earlier.

This module replays the reader's **real** :class:`RawExtraction` for a page it has already read — never a
fabricated or hand-edited value — so nothing about the honesty contract changes:

  * The stored artifact is genuine model output. It records the original ``model_id`` + ``prompt_hash``
    (ADR-004 §5.6), so the audit still attributes each figure to the exact reader that produced it, and a
    cache hit is logged as a *replay* — never silently presented as a fresh live pull.
  * The cache holds *only* the VLM transcription. The page is re-rendered locally every run and the
    deterministic OCR cross-read re-verifies the cached boxes live (ClaimGraphBuilder) — the
    box-grounded verification Layer 2's safety rests on (§5.2) is **never** shortcut by the cache.
  * The wrapper has zero decision authority (like FallbackExtractor): it only decides *whether a reader
    needs to run*, never what a figure is or whether a document is genuine.

Two tiers, so a human stays in the loop (curated mode — the default when caching is on):

  * ``staging/`` — every live read is written here automatically, so a just-run extraction can be kept.
  * ``saved/``   — the durable tier the read path replays. An entry lands here **only** by explicit
    promotion: the operator reviewed the extraction and chose to keep it (see the ``/api/vlm-cache``
    routes). This is what "save the ones I'm satisfied with, replay them on re-upload" means.

In ``auto`` mode there is no staging: every live read is memoized straight to ``saved`` (a plain
content-hash memoization of a temperature-0 call — reproducible by design). Editing a cached file to
change a figure would be a §3.3 violation (chasing the result); entries are only ever written from a
real read. Invalidation is by construction — the key folds in the reader's ``name`` and
``_SCHEMA_VERSION`` — so swapping the model or evolving the stored shape misses cleanly.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import UTC, datetime
from typing import Any

from forensics.extraction.interface import (
    PageImage,
    RawExtraction,
    VLMExtractor,
    VLMUnavailable,
)

logger = logging.getLogger(__name__)

# Bump when the stored envelope shape or the RawExtraction contract changes — old entries then miss
# cleanly (a stale-shaped replay is worse than a re-read). Part of the cache key, not a magic literal.
_SCHEMA_VERSION = "1"

# Cache modes (SATYUM_VLM_CACHE_MODE):
#   "off"     — no caching; every read is live (production default).
#   "curated" — live reads land in staging; the read path replays ONLY explicitly-saved entries.
#   "auto"    — memoize every read straight to the saved tier (no human in the loop).
CACHE_MODE_OFF = "off"
CACHE_MODE_CURATED = "curated"
CACHE_MODE_AUTO = "auto"


class ExtractionCacheStore:
    """The on-disk two-tier store. Reader-agnostic: it deals in content keys + JSON envelopes only.

    Shared purely by directory: the extractor and the management API each construct a store over the
    same ``cache_dir`` (stateless — CLAUDE.md §4), so nothing has to hold a live reference to anything.
    """

    def __init__(self, cache_dir: str) -> None:
        self.saved_dir = os.path.join(cache_dir, "saved")
        self.staging_dir = os.path.join(cache_dir, "staging")
        os.makedirs(self.saved_dir, exist_ok=True)
        os.makedirs(self.staging_dir, exist_ok=True)

    # --- keying -----------------------------------------------------------------------------------

    @staticmethod
    def content_key(png_bytes: bytes, doc_type_hint: str | None, reader_name: str) -> str:
        h = hashlib.sha256()
        h.update(png_bytes)  # the exact pixels the reader saw — the content address
        h.update(b"\x00")
        h.update((doc_type_hint or "").encode("utf-8"))
        h.update(b"\x00")
        h.update(reader_name.encode("utf-8"))  # a different reader is a different transcription
        h.update(b"\x00")
        h.update(_SCHEMA_VERSION.encode("utf-8"))
        return h.hexdigest()

    # --- read -------------------------------------------------------------------------------------

    def load_saved(self, key: str) -> RawExtraction | None:
        return self._load(self.saved_dir, key)

    def load_staging(self, key: str) -> RawExtraction | None:
        return self._load(self.staging_dir, key)

    def _load(self, directory: str, key: str) -> RawExtraction | None:
        envelope = self._read_envelope(directory, key)
        if envelope is None:
            return None
        try:
            return RawExtraction.model_validate(envelope["extraction"])
        except (ValueError, KeyError) as exc:
            # A corrupt/incompatible entry must never crash or masquerade as a valid read — drop it and
            # let the caller fall through to a live re-extraction (fail toward doing the real work).
            logger.warning("extraction cache: ignoring unreadable entry %s/%s: %s", directory, key, exc)
            return None

    def _read_envelope(self, directory: str, key: str) -> dict[str, Any] | None:
        path = os.path.join(directory, f"{key}.json")
        if not os.path.exists(path):
            return None
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else None
        except (OSError, ValueError) as exc:
            logger.warning("extraction cache: unreadable file %s: %s", path, exc)
            return None

    # --- write ------------------------------------------------------------------------------------

    def stage(
        self, key: str, page: PageImage, doc_type_hint: str | None, reader_name: str, raw: RawExtraction
    ) -> None:
        self._write(self.staging_dir, self._envelope(key, page, doc_type_hint, reader_name, raw))

    def save_direct(
        self, key: str, page: PageImage, doc_type_hint: str | None, reader_name: str, raw: RawExtraction
    ) -> None:
        self._write(self.saved_dir, self._envelope(key, page, doc_type_hint, reader_name, raw))

    def _envelope(
        self, key: str, page: PageImage, doc_type_hint: str | None, reader_name: str, raw: RawExtraction
    ) -> dict[str, Any]:
        return {
            "key": key,
            "schema_version": _SCHEMA_VERSION,
            "reader_name": reader_name,
            "model_id": raw.model_id,
            "doc_type": raw.doc_type,
            "doc_type_hint": doc_type_hint or "",
            "page_index": page.page_index,
            "cached_at": datetime.now(UTC).isoformat(),
            "extraction": raw.model_dump(mode="json"),
        }

    def _write(self, directory: str, envelope: dict[str, Any]) -> None:
        path = os.path.join(directory, f"{envelope['key']}.json")
        tmp = f"{path}.{os.getpid()}.tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(envelope, fh)
            os.replace(tmp, path)  # atomic publish — a concurrent read never sees a half-written file
        except OSError as exc:
            logger.warning("extraction cache: failed to write %s: %s", path, exc)
            try:
                os.remove(tmp)
            except OSError:
                pass

    # --- management (used by the /api/vlm-cache routes) -------------------------------------------

    def promote(self, key: str) -> bool:
        """Copy a staged entry into the saved tier. Returns True if the key is saved afterward."""
        if self._read_envelope(self.saved_dir, key) is not None:
            return True  # already saved — idempotent
        envelope = self._read_envelope(self.staging_dir, key)
        if envelope is None:
            return False
        self._write(self.saved_dir, envelope)
        return True

    def promote_all_staged(self) -> list[str]:
        """Promote every staged entry (the "save the document I just ran" convenience). Returns keys."""
        promoted: list[str] = []
        for key in self._keys(self.staging_dir):
            if self.promote(key):
                promoted.append(key)
        return promoted

    def discard_staged(self, key: str) -> bool:
        return self._remove(self.staging_dir, key)

    def clear_staged(self) -> list[str]:
        """Empty the staging buffer (the just-run, not-yet-saved reads). Returns the keys removed.

        Lets a per-document flow stay clean: after saving (or deciding not to save) the document you
        just ran, reset the buffer so a later "save" cannot accidentally keep an earlier unwanted read.
        Never touches the saved tier.
        """
        return [key for key in self._keys(self.staging_dir) if self._remove(self.staging_dir, key)]

    def delete_saved(self, key: str) -> bool:
        return self._remove(self.saved_dir, key)

    def _remove(self, directory: str, key: str) -> bool:
        path = os.path.join(directory, f"{key}.json")
        try:
            os.remove(path)
            return True
        except OSError:
            return False

    def list_saved(self) -> list[dict[str, Any]]:
        return self._list(self.saved_dir, saved=True)

    def list_staged(self) -> list[dict[str, Any]]:
        return self._list(self.staging_dir, saved=False)

    def _list(self, directory: str, *, saved: bool) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for key in self._keys(directory):
            envelope = self._read_envelope(directory, key)
            if envelope is None:
                continue
            # Summary only — never the full transcription (keeps the listing light and avoids echoing a
            # document's contents through a management endpoint).
            entries.append(
                {
                    "key": envelope.get("key", key),
                    "reader_name": envelope.get("reader_name", ""),
                    "model_id": envelope.get("model_id", ""),
                    "doc_type": envelope.get("doc_type", ""),
                    "page_index": envelope.get("page_index", 0),
                    "cached_at": envelope.get("cached_at", ""),
                    "saved": saved,
                }
            )
        entries.sort(key=lambda e: e.get("cached_at", ""), reverse=True)
        return entries

    def _keys(self, directory: str) -> list[str]:
        try:
            return [name[:-5] for name in os.listdir(directory) if name.endswith(".json")]
        except OSError:
            return []

    def has_any_saved(self) -> bool:
        return bool(self._keys(self.saved_dir))

    def stored_at(self, key: str) -> str:
        envelope = self._read_envelope(self.saved_dir, key) or self._read_envelope(self.staging_dir, key)
        return str(envelope.get("cached_at", "unknown")) if envelope else "unknown"


class CachingExtractor(VLMExtractor):
    """Wrap a reader so a page it has already read (and, in curated mode, whose read was *saved*) replays."""

    def __init__(self, inner: VLMExtractor, *, store: ExtractionCacheStore, mode: str) -> None:
        self._inner = inner
        self._store = store
        self._mode = mode

    @property
    def name(self) -> str:
        # Identify the underlying reader in logs/audit; RawExtraction.model_id still records the exact
        # model that produced each cached transcription, so replay is never misattributed.
        return self._inner.name

    @property
    def available(self) -> bool:
        # Available if the live reader can run OR we hold at least one *saved* transcription. The second
        # case is what lets a pre-warmed demo replay real extractions with the live API rate-limited or
        # entirely offline — a novel (unsaved) page then still fails closed at extract() time.
        return self._inner.available or self._store.has_any_saved()

    def handles_script(self, family: str) -> bool:
        return self._inner.handles_script(family)

    def extract(self, page: PageImage, *, doc_type_hint: str | None = None) -> RawExtraction:
        key = self._store.content_key(page.png_bytes, doc_type_hint, self._inner.name)

        saved = self._store.load_saved(key)
        if saved is not None:
            self._log_replay(page.page_index, saved, key, tier="saved")
            return saved

        # In auto mode the saved tier IS the whole cache, so a hit above is the only replay path. In
        # curated mode a live read stages the result but is NOT replayed until a human promotes it — so a
        # re-upload before saving still reads live (the operator hasn't vouched for it yet).
        if not self._inner.available:
            raise VLMUnavailable(
                f"no saved transcription for this page and live reader {self._inner.name!r} is unavailable"
            )

        raw = self._inner.extract(page, doc_type_hint=doc_type_hint)  # may raise; propagate (fail-closed)
        if self._mode == CACHE_MODE_AUTO:
            self._store.save_direct(key, page, doc_type_hint, self._inner.name, raw)
        else:  # curated
            self._store.stage(key, page, doc_type_hint, self._inner.name, raw)
        return raw

    def _log_replay(self, page_index: int, raw: RawExtraction, key: str, *, tier: str) -> None:
        logger.info(
            "extraction: CACHE HIT (%s) page %d — replaying real transcription from %s (stored %s); "
            "no live VLM call",
            tier,
            page_index,
            raw.model_id or self._inner.name,
            self._store.stored_at(key),
        )
