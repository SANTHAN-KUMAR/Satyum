"""Tamper-evident, hash-chained audit ledger (CLAUDE.md §10, the cyber-spine).

Every verdict is appended as a record whose hash chains to the previous record's hash. Altering
any past record (or its order) breaks the chain, which :func:`verify_chain` detects — giving the
bank non-repudiation: a decision can be reconstructed AND proven un-altered.

Pure-Python (hashlib + json); the persistence backend is injected so the in-memory implementation
is fully unit-testable. The ledger stores decision metadata and signal digests — NEVER document
content or imagery (§10).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Protocol

GENESIS_HASH = "0" * 64


def _canonical(payload: dict[str, Any]) -> bytes:
    """Deterministic serialisation so the same logical record always hashes identically."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _record_hash(prev_hash: str, payload: dict[str, Any]) -> str:
    h = hashlib.sha256()
    h.update(prev_hash.encode("ascii"))
    h.update(_canonical(payload))
    return h.hexdigest()


@dataclass(frozen=True)
class AuditRecord:
    seq: int
    timestamp: str  # ISO-8601, supplied by the caller (no wall-clock in pure logic)
    payload: dict[str, Any]  # session_id, verdict, score, tier, signal digests — no imagery
    prev_hash: str
    this_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "timestamp": self.timestamp,
            "payload": self.payload,
            "prev_hash": self.prev_hash,
            "this_hash": self.this_hash,
        }


class LedgerStore(Protocol):
    def append(self, record: AuditRecord) -> None: ...
    def all(self) -> list[AuditRecord]: ...
    def last_hash(self) -> str: ...


@dataclass
class InMemoryLedgerStore:
    _records: list[AuditRecord] = field(default_factory=list)

    def append(self, record: AuditRecord) -> None:
        self._records.append(record)

    def all(self) -> list[AuditRecord]:
        return list(self._records)

    def last_hash(self) -> str:
        return self._records[-1].this_hash if self._records else GENESIS_HASH


class AuditLedger:
    def __init__(self, store: LedgerStore | None = None) -> None:
        self._store = store or InMemoryLedgerStore()

    def record(self, timestamp: str, payload: dict[str, Any]) -> AuditRecord:
        prev_hash = self._store.last_hash()
        seq = len(self._store.all())
        body = {"seq": seq, "timestamp": timestamp, "payload": payload, "prev_hash": prev_hash}
        this_hash = _record_hash(prev_hash, body)
        rec = AuditRecord(seq=seq, timestamp=timestamp, payload=payload,
                          prev_hash=prev_hash, this_hash=this_hash)
        self._store.append(rec)
        return rec

    def verify_chain(self) -> tuple[bool, int | None]:
        """Re-derive every hash and confirm the chain is intact.

        Returns ``(ok, first_broken_seq)``. ``first_broken_seq`` is ``None`` when the chain is sound.
        """
        prev_hash = GENESIS_HASH
        for rec in self._store.all():
            body = {"seq": rec.seq, "timestamp": rec.timestamp,
                    "payload": rec.payload, "prev_hash": prev_hash}
            expected = _record_hash(prev_hash, body)
            if expected != rec.this_hash or rec.prev_hash != prev_hash:
                return False, rec.seq
            prev_hash = rec.this_hash
        return True, None

    def records(self) -> list[AuditRecord]:
        return self._store.all()
