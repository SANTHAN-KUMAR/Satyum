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
    def count(self) -> int: ...


@dataclass
class InMemoryLedgerStore:
    _records: list[AuditRecord] = field(default_factory=list)

    def append(self, record: AuditRecord) -> None:
        self._records.append(record)

    def all(self) -> list[AuditRecord]:
        return list(self._records)

    def last_hash(self) -> str:
        return self._records[-1].this_hash if self._records else GENESIS_HASH

    def count(self) -> int:
        return len(self._records)


class AuditLedger:
    def __init__(self, store: LedgerStore | None = None) -> None:
        self._store = store or InMemoryLedgerStore()

    def record(self, timestamp: str, payload: dict[str, Any]) -> AuditRecord:
        prev_hash = self._store.last_hash()
        seq = self._store.count()  # next seq = current length (the chain is append-only)
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
        return self._store.count(), self._store.last_hash()

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


# --- Durable backend: a SQLAlchemy/Postgres-backed ledger store --------------------------------
# The hash-chain logic above is storage-agnostic (it talks only to the LedgerStore Protocol), so a
# durable store is a drop-in: the SAME tamper-evidence guarantees now survive a process restart.
# SQLAlchemy keeps it portable — SQLite for tests, Postgres in production (CLAUDE.md §11).
#
# Concurrency note: seq + prev_hash are derived from the store's current state, so a single writer is
# assumed (the deployment runs one backend worker). The seq PRIMARY KEY makes a concurrent double-write
# fail loudly (IntegrityError) rather than silently fork the chain — fail-closed, not silent corruption.

try:  # SQLAlchemy is an optional runtime dep; the in-memory store needs none of this.
    from sqlalchemy import JSON as SA_JSON
    from sqlalchemy import Integer, String, create_engine, func, select
    from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

    class _Base(DeclarativeBase):
        pass

    class _AuditRow(_Base):
        __tablename__ = "audit_records"
        seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
        timestamp: Mapped[str] = mapped_column(String(40))
        payload: Mapped[dict[str, Any]] = mapped_column(SA_JSON)
        prev_hash: Mapped[str] = mapped_column(String(64))
        this_hash: Mapped[str] = mapped_column(String(64))

    class SqlAlchemyLedgerStore:
        """A durable :class:`LedgerStore` over any SQLAlchemy-supported DB (Postgres in prod).

        The table is created on init if absent (idempotent); Alembic owns schema evolution in a real
        deployment. Payloads are stored as JSON and round-trip identically, so the re-derived hash in
        :meth:`AuditLedger.verify_chain` still matches — tampering with a row in the DB breaks the chain.
        """

        def __init__(self, url: str) -> None:
            # pool_pre_ping recovers cleanly if Postgres drops idle connections.
            self._engine = create_engine(url, pool_pre_ping=True, future=True)
            _Base.metadata.create_all(self._engine)

        def append(self, record: AuditRecord) -> None:
            with Session(self._engine) as s:
                s.add(_AuditRow(seq=record.seq, timestamp=record.timestamp,
                                payload=record.payload, prev_hash=record.prev_hash,
                                this_hash=record.this_hash))
                s.commit()

        def all(self) -> list[AuditRecord]:
            with Session(self._engine) as s:
                rows = s.scalars(select(_AuditRow).order_by(_AuditRow.seq)).all()
                return [
                    AuditRecord(seq=r.seq, timestamp=r.timestamp, payload=r.payload,
                                prev_hash=r.prev_hash, this_hash=r.this_hash)
                    for r in rows
                ]

        def last_hash(self) -> str:
            with Session(self._engine) as s:
                row = s.scalars(
                    select(_AuditRow).order_by(_AuditRow.seq.desc()).limit(1)
                ).first()
                return row.this_hash if row is not None else GENESIS_HASH

        def count(self) -> int:
            with Session(self._engine) as s:
                return s.scalar(select(func.count()).select_from(_AuditRow)) or 0

except ImportError:  # SQLAlchemy not installed -> only the in-memory store is available.
    SqlAlchemyLedgerStore = None  # type: ignore[assignment,misc]
