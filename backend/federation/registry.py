"""The privacy-preserving shared fraud registry (PROPOSAL-001 §6.2).

A neutral consortium store of *what fraud looks like*, holding only non-invertible artifacts: salted
perceptual hashes and HMAC entity tokens (``federation/tokens.py``) — never a raw document, image,
name, or account number (§6.8 / CLAUDE.md §10). It answers one question — *"have we seen this exact
thing before?"* — via set membership:

  * **Document reuse:** a candidate salted pHash within ``hamming_threshold`` bits of a stored one →
    the same forged document resubmitted / laundered across applicants (pHash survives rescale/mild
    blur). The threshold is ``settings.phash_hamming_threshold`` (ROC-calibrated — no magic number).
  * **Entity reuse:** a candidate HMAC token equal to a stored one → the same PAN / account / phone
    seen in prior fraud, without anyone sharing the raw identifier.

PSI-style disclosure: a query returns ONLY the entries that matched (the intersection) — never the
rest of the registry. "Seen at ≥N banks" is a secure-aggregated count over distinct reporters.

The store is dependency-injected (in-memory here; a production store shards by hash prefix and is
encrypted at rest — §10) so the query semantics are testable without infrastructure.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from federation.tokens import hamming_hex


@dataclass
class FraudRegistryEntry:
    """One known-fraud fingerprint. Holds only non-invertible tokens + opaque metadata (no PII)."""

    label: str                                   # opaque case ref at the reporting bank (NOT PII)
    threat_class: str                            # e.g. "forged_statement", "salary_slip_ring"
    salted_phash: str | None = None              # 256-bit salted perceptual hash, or None
    entity_tokens: dict[str, str] = field(default_factory=dict)  # kind -> HMAC token
    banks: set[str] = field(default_factory=set)  # distinct reporters (secure-agg count source)
    seen_count: int = 0
    first_seen: str = ""


@dataclass(frozen=True)
class RegistryMatch:
    """A single intersection hit returned to a querying bank (the only thing it learns)."""

    label: str
    threat_class: str
    phash_distance: int | None            # Hamming bits to the matched stored hash, or None
    matched_token_kinds: tuple[str, ...]  # which entity kinds matched (e.g. ("pan", "account"))
    banks_seen: int                       # distinct banks that have reported this entry
    seen_count: int

    @property
    def strength(self) -> float:
        """A 0..1 match strength for ranking — tighter pHash + more shared entities + more banks."""
        s = 0.0
        if self.phash_distance is not None:
            s = max(s, 1.0 - self.phash_distance / 16.0)  # 0 bits -> 1.0; fades with distance
        s += 0.15 * len(self.matched_token_kinds)
        s += 0.05 * max(0, self.banks_seen - 1)
        return min(1.0, s)


@dataclass
class RegistryQueryResult:
    matches: list[RegistryMatch] = field(default_factory=list)

    @property
    def matched(self) -> bool:
        return bool(self.matches)

    @property
    def best(self) -> RegistryMatch | None:
        return max(self.matches, key=lambda m: m.strength) if self.matches else None


class FraudRegistry:
    """In-memory consortium fraud registry. Linear scan (256-bit Hamming per row is cheap)."""

    def __init__(self) -> None:
        self._entries: list[FraudRegistryEntry] = []

    def report(
        self,
        *,
        label: str,
        threat_class: str,
        bank_id: str,
        timestamp: str,
        salted_phash: str | None = None,
        entity_tokens: dict[str, str] | None = None,
    ) -> FraudRegistryEntry:
        """Submit a confirmed-fraud fingerprint. Dedups on an identical salted pHash (increments the
        seen-count + reporter set) so the same artifact reported by several banks is one entry whose
        ``banks_seen`` grows — the secure-aggregated "seen at ≥N banks" signal."""
        tokens = dict(entity_tokens or {})
        if salted_phash is not None:
            for e in self._entries:
                if e.salted_phash == salted_phash:
                    e.seen_count += 1
                    e.banks.add(bank_id)
                    e.entity_tokens.update(tokens)
                    return e
        entry = FraudRegistryEntry(
            label=label, threat_class=threat_class, salted_phash=salted_phash,
            entity_tokens=tokens, banks={bank_id}, seen_count=1, first_seen=timestamp,
        )
        self._entries.append(entry)
        return entry

    def query(
        self,
        *,
        salted_phashes: list[str] | None = None,
        entity_tokens: dict[str, str] | None = None,
        hamming_threshold: int,
    ) -> RegistryQueryResult:
        """PSI-style membership query. Returns ONLY the entries that intersect the candidates.

        A stored entry matches if any candidate salted pHash is within ``hamming_threshold`` bits of
        its hash, OR it shares at least one entity token. The querier learns nothing about
        non-matching entries (they are never returned).
        """
        candidates = salted_phashes or []
        q_tokens = entity_tokens or {}
        q_token_set = set(q_tokens.values())
        result = RegistryQueryResult()

        for e in self._entries:
            phash_distance: int | None = None
            if e.salted_phash is not None and candidates:
                best = min(hamming_hex(e.salted_phash, c) for c in candidates)
                if best <= hamming_threshold:
                    phash_distance = best

            matched_kinds = tuple(
                sorted(kind for kind, tok in e.entity_tokens.items() if tok in q_token_set)
            )

            if phash_distance is None and not matched_kinds:
                continue  # no intersection -> not revealed (PSI semantics)

            result.matches.append(RegistryMatch(
                label=e.label,
                threat_class=e.threat_class,
                phash_distance=phash_distance,
                matched_token_kinds=matched_kinds,
                banks_seen=len(e.banks),
                seen_count=e.seen_count,
            ))
        return result

    def size(self) -> int:
        return len(self._entries)
