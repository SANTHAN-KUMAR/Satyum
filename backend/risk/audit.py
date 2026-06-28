"""Tamper-evident, hash-chained audit ledger (CLAUDE.md §10, the cyber-spine).

Every verdict is appended as a record whose hash chains to the previous record's hash. Altering
any past record's content, or reordering the recorded sequence, breaks the chain — which
:func:`AuditLedger.verify_chain` detects. A decision can therefore be reconstructed and any
in-place edit of a retained record proven.

Honest bound (CLAUDE.md §3.5): a bare hash chain is only as trustworthy as its HEAD. On its own it
cannot detect a wholesale re-forge (an attacker with write access who recomputes every hash forward)
or a tail TRUNCATION (dropping the most recent records) — both yield a chain that is internally
consistent. Closing that gap requires anchoring the head outside the ledger. :meth:`AuditLedger.head`
exposes that anchor ``(count, last_hash)`` for a caller to persist/sign/timestamp; passing a
previously-captured anchor back to :meth:`AuditLedger.verify_chain` then detects truncation and
re-forge relative to it. Production should persist the anchor to durable, append-only storage (and,
ideally, a signed external timestamp) — tracked as the path to full non-repudiation.

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

    def head(self) -> tuple[int, str]:
        """The chain anchor: ``(record_count, last_hash)``.

        Persist/sign this out-of-band to later detect tail truncation or a wholesale re-forge that an
        internally-consistent chain alone cannot catch (see module docstring). ``last_hash`` is the
        genesis hash for an empty ledger.
        """
        records = self._store.all()
        return len(records), (records[-1].this_hash if records else GENESIS_HASH)

    def verify_chain(self, anchor: tuple[int, str] | None = None) -> tuple[bool, int | None]:
        """Re-derive every hash and confirm the chain is intact.

        Returns ``(ok, first_broken_seq)``; ``first_broken_seq`` is ``None`` when the chain is sound.
        When ``anchor`` (a previously-captured :meth:`head`) is supplied, the chain must additionally
        still contain at least ``anchor`` records and the record at that count must carry the anchored
        hash — this is what catches a tail TRUNCATION or a forward RE-FORGE that an unanchored chain
        cannot. A failed anchor check reports the seq at/after which the anchored history diverged.
        """
        prev_hash = GENESIS_HASH
        for rec in self._store.all():
            body = {"seq": rec.seq, "timestamp": rec.timestamp,
                    "payload": rec.payload, "prev_hash": prev_hash}
            expected = _record_hash(prev_hash, body)
            if expected != rec.this_hash or rec.prev_hash != prev_hash:
                return False, rec.seq
            prev_hash = rec.this_hash

        if anchor is not None:
            anchored_count, anchored_hash = anchor
            records = self._store.all()
            if len(records) < anchored_count:
                # Records were dropped after the anchor was taken (truncation).
                return False, len(records)
            if anchored_count > 0 and records[anchored_count - 1].this_hash != anchored_hash:
                # The anchored record's hash no longer matches (re-forge of the anchored history).
                return False, anchored_count - 1

        return True, None

    def records(self) -> list[AuditRecord]:
        return self._store.all()
