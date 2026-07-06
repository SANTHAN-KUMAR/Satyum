"""Discrimination tests for the Layer-2 replay cache (forensics/extraction/cache.py).

The cache's job is narrow and safety-critical: replay a reader's *real* transcription for a page it has
already read *and* whose read a human saved, never fabricate one for a page it hasn't, and never let a
staged-but-unsaved read replay in curated mode. Every test here would FAIL against a trivial
implementation (CLAUDE.md §3.2):

  * a constant "always miss" cache re-hits the reader → fails the call-count assertions;
  * a constant "always hit" cache returns the wrong page's data → fails the discrimination-by-bytes test;
  * a cache that replays staging in curated mode → fails the "unsaved read is not replayed" test;
  * a cache that fabricates on a miss → fails the offline-novel-page fail-closed test.

The wrapped reader is a scripted double that counts its live reads (the point is to prove *when the
network is touched*); the cache, its keying, its two tiers, and its on-disk round-trip run for real.
"""

from __future__ import annotations

import pytest

from forensics.extraction.cache import (
    CACHE_MODE_AUTO,
    CACHE_MODE_CURATED,
    CachingExtractor,
    ExtractionCacheStore,
)
from forensics.extraction.interface import (
    ExtractedField,
    PageImage,
    RawExtraction,
    VLMUnavailable,
)


class ScriptedReader:
    """A VLMExtractor double: returns a marked transcription and counts every live read."""

    def __init__(self, *, available: bool = True, name: str = "vlm:scripted") -> None:
        self.name = name
        self._available = available
        self.calls = 0

    @property
    def available(self) -> bool:
        return self._available

    def set_available(self, value: bool) -> None:
        self._available = value

    def handles_script(self, family: str) -> bool:
        return True

    def extract(self, page: PageImage, *, doc_type_hint: str | None = None) -> RawExtraction:
        self.calls += 1
        # Encode the page's identity + a live-call counter into the result so a test can prove whether a
        # returned value came from THIS live read or a replay of an earlier one.
        marker = f"{page.png_bytes.decode()}#call{self.calls}"
        return RawExtraction(
            doc_type="bank_statement",
            fields=[ExtractedField(predicate="bank_name", value=marker, confidence=0.9)],
            model_id="scripted-model-1",
            prompt_hash="deadbeef",
        )


def _page(payload: str, *, index: int = 0) -> PageImage:
    # png_bytes is the content address; a distinct payload ⇒ a distinct page.
    return PageImage(png_bytes=payload.encode(), width=100, height=100, page_index=index)


def _curated(reader: ScriptedReader, tmp_path) -> tuple[CachingExtractor, ExtractionCacheStore]:
    store = ExtractionCacheStore(str(tmp_path))
    return CachingExtractor(reader, store=store, mode=CACHE_MODE_CURATED), store


# --- auto mode: memoize every read ----------------------------------------------------------------


def test_auto_mode_replays_the_same_page_without_touching_the_reader(tmp_path):
    reader = ScriptedReader()
    store = ExtractionCacheStore(str(tmp_path))
    cache = CachingExtractor(reader, store=store, mode=CACHE_MODE_AUTO)
    page = _page("PAGE-A")

    first = cache.extract(page, doc_type_hint="bank_statement")
    second = cache.extract(page, doc_type_hint="bank_statement")

    # The reader was hit exactly once; the second call was served from disk (would be 2 if uncached).
    assert reader.calls == 1
    assert second.fields[0].value == first.fields[0].value
    assert second.fields[0].value.endswith("#call1")
    assert second.model_id == "scripted-model-1"  # real model attribution survives the replay


def test_different_page_bytes_are_a_distinct_cache_entry(tmp_path):
    reader = ScriptedReader()
    store = ExtractionCacheStore(str(tmp_path))
    cache = CachingExtractor(reader, store=store, mode=CACHE_MODE_AUTO)

    a = cache.extract(_page("PAGE-A"), doc_type_hint="bank_statement")
    b = cache.extract(_page("PAGE-B"), doc_type_hint="bank_statement")

    # Different content ⇒ two live reads, two distinct transcriptions (an "always hit" cache would
    # wrongly serve PAGE-A's data for PAGE-B and this would fail).
    assert reader.calls == 2
    assert a.fields[0].value.startswith("PAGE-A")
    assert b.fields[0].value.startswith("PAGE-B")


# --- curated mode: a human keeps only what they're satisfied with ---------------------------------


def test_curated_staged_but_unsaved_read_is_not_replayed(tmp_path):
    """Until the operator saves it, a curated read is staged only — a re-upload still reads live."""
    reader = ScriptedReader()
    cache, store = _curated(reader, tmp_path)
    page = _page("PAGE-A")

    cache.extract(page)  # live read → staged, NOT saved
    assert reader.calls == 1
    assert len(store.list_staged()) == 1
    assert store.list_saved() == []

    cache.extract(page)  # still not saved → reads live again (the human hasn't vouched for it)
    assert reader.calls == 2


def test_curated_promoted_read_replays_on_reupload(tmp_path):
    """Save the staged read, and the same document thereafter replays with no live call."""
    reader = ScriptedReader()
    cache, store = _curated(reader, tmp_path)
    page = _page("PAGE-A")

    cache.extract(page)  # stage
    promoted = store.promote_all_staged()  # the operator is satisfied → keep it
    assert len(promoted) == 1

    replay = cache.extract(page)  # now served from the saved tier
    assert reader.calls == 1  # no second live read
    assert replay.fields[0].value.endswith("#call1")
    assert replay.model_id == "scripted-model-1"


def test_selective_promotion_saves_only_the_chosen_document(tmp_path):
    """'Choose what to save': promoting one page's key must not save the other."""
    reader = ScriptedReader()
    cache, store = _curated(reader, tmp_path)
    page_a, page_b = _page("PAGE-A"), _page("PAGE-B")

    cache.extract(page_a)
    cache.extract(page_b)
    key_a = store.content_key(page_a.png_bytes, None, reader.name)
    assert store.promote(key_a) is True

    saved_keys = {e["key"] for e in store.list_saved()}
    assert key_a in saved_keys
    assert store.content_key(page_b.png_bytes, None, reader.name) not in saved_keys

    reader.set_available(False)  # go offline
    replay_a = cache.extract(page_a)  # A was saved → replays
    assert replay_a.fields[0].value.endswith("#call1")
    with pytest.raises(VLMUnavailable):  # B was never saved → fails closed, never fabricated
        cache.extract(page_b)


# --- demo-resilience + fail-closed ----------------------------------------------------------------


def test_saved_cache_replays_when_the_live_reader_goes_offline(tmp_path):
    """The demo-resilience guarantee: save once, then survive a rate-limited/offline API."""
    reader = ScriptedReader(available=True)
    cache, store = _curated(reader, tmp_path)
    page = _page("PAGE-A")

    warmed = cache.extract(page)
    store.promote_all_staged()
    assert reader.calls == 1

    reader.set_available(False)  # the live API is now rate-limited / offline
    assert cache.available is True  # the layer still runs: a non-empty SAVED tier is availability

    replay = cache.extract(page)
    assert reader.calls == 1
    assert replay.fields[0].value == warmed.fields[0].value


def test_clear_staged_resets_the_buffer_without_touching_saved(tmp_path):
    """'./cache.sh skip/save' hygiene: clearing staging keeps saved entries intact."""
    reader = ScriptedReader()
    cache, store = _curated(reader, tmp_path)

    cache.extract(_page("KEEP"))
    store.promote_all_staged()  # KEEP is now saved
    cache.extract(_page("JUNK"))  # an unwanted read, only staged

    cleared = store.clear_staged()
    assert len(cleared) == 2  # both KEEP's and JUNK's staged copies are gone
    assert store.list_staged() == []
    assert len(store.list_saved()) == 1  # the saved KEEP survived

    reader.set_available(False)
    assert cache.extract(_page("KEEP")).fields[0].value.endswith("#call1")  # KEEP still replays
    with pytest.raises(VLMUnavailable):
        cache.extract(_page("JUNK"))  # JUNK was never saved → not replayed, not fabricated


def test_uncached_page_fails_closed_when_reader_offline(tmp_path):
    """A page the reader never transcribed must NOT be fabricated — it fails closed to pending (§3.4)."""
    reader = ScriptedReader(available=False)
    cache, _ = _curated(reader, tmp_path)

    with pytest.raises(VLMUnavailable):
        cache.extract(_page("NEVER-SEEN"))
    assert reader.calls == 0


def test_a_different_reader_identity_misses_and_re_reads(tmp_path):
    """The key folds in the reader name: swapping the model must not replay the old model's transcription."""
    page = _page("PAGE-A")
    store = ExtractionCacheStore(str(tmp_path))

    reader_a = ScriptedReader(name="vlm:model-a")
    CachingExtractor(reader_a, store=store, mode=CACHE_MODE_AUTO).extract(page)

    reader_b = ScriptedReader(name="vlm:model-b")
    result_b = CachingExtractor(reader_b, store=store, mode=CACHE_MODE_AUTO).extract(page)

    assert reader_b.calls == 1  # model-b did its own read rather than replaying model-a's entry
    assert result_b.fields[0].value.startswith("PAGE-A")


def test_corrupt_saved_entry_falls_back_to_a_live_read(tmp_path):
    """A corrupt/incompatible entry must never crash or replay garbage — fail toward doing the real work."""
    reader = ScriptedReader()
    store = ExtractionCacheStore(str(tmp_path))
    cache = CachingExtractor(reader, store=store, mode=CACHE_MODE_AUTO)
    page = _page("PAGE-A")

    cache.extract(page)  # writes one saved entry
    assert reader.calls == 1
    for entry in (tmp_path / "saved").glob("*.json"):
        entry.write_text("{ this is not valid json")

    result = cache.extract(page)  # miss (unreadable) → live re-read, no exception
    assert reader.calls == 2
    assert result.fields[0].value.endswith("#call2")
