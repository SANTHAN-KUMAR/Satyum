"""Management surface for the Layer-2 replay cache (forensics/extraction/cache.py).

The extractor auto-*stages* every live VLM read; these routes let a human keep the loop: review what was
just read, then explicitly **save** the ones they're satisfied with. A saved entry is what the read path
replays on a re-upload of the same document — instantly, offline, with no live API call. Nothing here
fabricates or edits a transcription: promotion only copies a real staged read into the saved tier
(CLAUDE.md §3.1/§3.3), and a listing returns summaries only (never a document's contents).

The store is constructed per-request over ``settings.vlm_cache_dir`` — the same directory the extractor
writes to — so no shared object or session state is needed (stateless; CLAUDE.md §4).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import settings
from forensics.extraction.cache import ExtractionCacheStore

router = APIRouter(prefix="/api/vlm-cache", tags=["vlm-cache"])
logger = logging.getLogger(__name__)


def _store() -> ExtractionCacheStore:
    return ExtractionCacheStore(settings.vlm_cache_dir)


class CacheListing(BaseModel):
    mode: str
    saved: list[dict]
    staged: list[dict]


class KeysRequest(BaseModel):
    keys: list[str]


class PromoteResult(BaseModel):
    promoted: list[str]
    saved_total: int


class RemoveResult(BaseModel):
    removed: list[str]


@router.get("", response_model=CacheListing)
def list_cache() -> CacheListing:
    """List saved (replayed) and staged (just-read, not yet kept) transcriptions — summaries only."""
    store = _store()
    return CacheListing(mode=settings.vlm_cache_mode, saved=store.list_saved(), staged=store.list_staged())


@router.post("/promote", response_model=PromoteResult)
def promote(request: KeysRequest) -> PromoteResult:
    """Save specific staged transcriptions (the ones the operator is satisfied with) so they replay."""
    store = _store()
    promoted = [key for key in request.keys if store.promote(key)]
    logger.info("vlm-cache: promoted %d/%d requested entries to saved", len(promoted), len(request.keys))
    return PromoteResult(promoted=promoted, saved_total=len(store.list_saved()))


@router.post("/promote-all-staged", response_model=PromoteResult)
def promote_all_staged() -> PromoteResult:
    """Save every staged transcription — the "keep the document I just ran" convenience."""
    store = _store()
    promoted = store.promote_all_staged()
    logger.info("vlm-cache: promoted all %d staged entries to saved", len(promoted))
    return PromoteResult(promoted=promoted, saved_total=len(store.list_saved()))


@router.post("/discard-staged", response_model=RemoveResult)
def discard_staged(request: KeysRequest) -> RemoveResult:
    """Drop staged transcriptions the operator does not want to keep."""
    store = _store()
    removed = [key for key in request.keys if store.discard_staged(key)]
    return RemoveResult(removed=removed)


@router.post("/clear-staged", response_model=RemoveResult)
def clear_staged() -> RemoveResult:
    """Empty the staging buffer — reset after saving (or skipping) the document just run."""
    store = _store()
    removed = store.clear_staged()
    logger.info("vlm-cache: cleared %d staged entries", len(removed))
    return RemoveResult(removed=removed)


@router.delete("/saved", response_model=RemoveResult)
def delete_saved(request: KeysRequest) -> RemoveResult:
    """Forget saved transcriptions, so the next upload of those documents reads live again."""
    store = _store()
    removed = [key for key in request.keys if store.delete_saved(key)]
    return RemoveResult(removed=removed)
