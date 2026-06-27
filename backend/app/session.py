"""In-memory, ephemeral session store for the verification pipeline (CLAUDE.md §4 / §10).

Session state (the per-request :class:`AnalysisContext`, including any camera frames) lives in memory
for the duration of one verification only. The cardinal privacy rule (§10): **frames are never
persisted and are dropped the instant scoring completes** — :meth:`SessionManager.drop_frames` is
called by the WebSocket handler after the final :class:`TrustScore` is produced, and an idle session
is reaped after a TTL. There is no disk or DB write path here by design; the durable record of a
verdict is the hash-chained audit ledger (decision metadata only, never imagery).

Designed to be swappable for Redis later (ADR-002 §4 "session state in one place"); the interface is
deliberately narrow. Thread-safety is provided by a lock because FastAPI runs blocking analyzer work
in a threadpool while the event loop may concurrently reap.
"""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

from app.contracts import AnalysisContext, Mode

# Session lifetime: a verification is interactive and short. An abandoned camera session must not
# pin frames in memory indefinitely (privacy + bounded memory, §10/§7). DEFAULT — needs calibration.
DEFAULT_TTL_SECONDS: float = 300.0


@dataclass
class _Entry:
    ctx: AnalysisContext
    created_at: float
    last_seen: float
    scored: bool = field(default=False)


class SessionManager:
    """Create, look up, and reap ephemeral sessions; never persists frames.

    Time is injected (``time_fn``) so the TTL behaviour is unit-testable without sleeping.
    """

    def __init__(
        self,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        time_fn=time.monotonic,
    ) -> None:
        self._ttl = float(ttl_seconds)
        self._now = time_fn
        self._sessions: dict[str, _Entry] = {}
        self._lock = threading.Lock()

    # --- lifecycle ------------------------------------------------------------------------

    def create(
        self,
        intake_mode: Mode,
        *,
        doc_type: Optional[str] = None,
        file_bytes: Optional[bytes] = None,
        file_name: Optional[str] = None,
        file_mime: Optional[str] = None,
        source_was_pullable: bool = False,
    ) -> AnalysisContext:
        """Mint a new session with a cryptographically-random id and return its context."""
        session_id = secrets.token_urlsafe(16)
        ctx = AnalysisContext(
            session_id=session_id,
            intake_mode=intake_mode,
            doc_type=doc_type,
            file_bytes=file_bytes,
            file_name=file_name,
            file_mime=file_mime,
            source_was_pullable=source_was_pullable,
        )
        now = self._now()
        with self._lock:
            self._reap_locked(now)
            self._sessions[session_id] = _Entry(ctx=ctx, created_at=now, last_seen=now)
        return ctx

    def get(self, session_id: str) -> Optional[AnalysisContext]:
        """Return the live context, or ``None`` if unknown or expired (lazily reaped)."""
        now = self._now()
        with self._lock:
            self._reap_locked(now)
            entry = self._sessions.get(session_id)
            if entry is None:
                return None
            entry.last_seen = now
            return entry.ctx

    def touch(self, session_id: str) -> None:
        """Mark a session as recently active so it is not reaped mid-stream."""
        now = self._now()
        with self._lock:
            entry = self._sessions.get(session_id)
            if entry is not None:
                entry.last_seen = now

    def mark_scored(self, session_id: str) -> None:
        with self._lock:
            entry = self._sessions.get(session_id)
            if entry is not None:
                entry.scored = True

    def drop_frames(self, session_id: str) -> None:
        """Drop camera frames immediately after scoring (§10 — frames never outlive their use)."""
        with self._lock:
            entry = self._sessions.get(session_id)
            if entry is not None:
                entry.ctx.frames.clear()

    def add_frame(self, session_id: str, frame) -> bool:
        """Append a camera frame to a live session. Returns False if the session is gone."""
        now = self._now()
        with self._lock:
            entry = self._sessions.get(session_id)
            if entry is None:
                return False
            entry.ctx.frames.append(frame)
            entry.last_seen = now
            return True

    def end(self, session_id: str) -> None:
        """Explicitly terminate a session and drop everything it held."""
        with self._lock:
            entry = self._sessions.pop(session_id, None)
            if entry is not None:
                entry.ctx.frames.clear()

    # --- internals ------------------------------------------------------------------------

    def _reap_locked(self, now: float) -> None:
        """Remove expired sessions (caller holds the lock); clears their frames first."""
        expired = [
            sid for sid, e in self._sessions.items() if now - e.last_seen > self._ttl
        ]
        for sid in expired:
            entry = self._sessions.pop(sid, None)
            if entry is not None:
                entry.ctx.frames.clear()

    def active_count(self) -> int:
        with self._lock:
            self._reap_locked(self._now())
            return len(self._sessions)
