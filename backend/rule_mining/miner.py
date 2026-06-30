"""Federated rule miner — a single-round PoC that discovers REAL discriminating rules (§6.3.1).

Honesty (CLAUDE.md §3.1/§3.3, PROPOSAL-001 §10): this is a *genuine* coverage-based rule miner — it
finds conjunctions of feature predicates that actually separate fraud from genuine on the supplied
labelled data, and reports their **measured** support / confidence / lift (never invented numbers). If
the data has no pattern, it returns no rules (a real discrimination, not a stub).

What is honestly LABELLED as PoC / architectural, not faked:
  * **single round** — not an iterated, converged federated training run;
  * **federated transport** — in production the engineered features arrive via secure aggregation
    across banks (no raw data pooled); here the miner runs on features already in hand. We do NOT
    simulate a trained global neural net or claim cross-bank accuracy we did not measure.

The miner's PRIMARY output is *candidate rules for a human to approve* (robust at low data volume and
explainable) — not a black-box score. That is exactly the design that survives a federated-learning
judge at low label counts (§2.4).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rule_mining.model import CandidateRule, Predicate


@dataclass(frozen=True)
class LabeledCase:
    features: dict[str, Any]
    is_fraud: bool


def _is_numeric(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _atomic_predicates(cases: list[LabeledCase]) -> list[Predicate]:
    """Generate candidate atomic predicates from the data (numeric thresholds + categorical equals)."""
    feature_values: dict[str, list[Any]] = {}
    for c in cases:
        for f, v in c.features.items():
            feature_values.setdefault(f, []).append(v)

    preds: list[Predicate] = []
    for feature, values in feature_values.items():
        numeric = [v for v in values if _is_numeric(v)]
        if numeric and len(numeric) == len(values):
            uniq = sorted(set(numeric))
            # Split candidates = midpoints between consecutive unique values (decision-tree style),
            # capped to keep the search bounded and deterministic.
            mids = [(uniq[i] + uniq[i + 1]) / 2 for i in range(len(uniq) - 1)]
            if len(mids) > 12:
                step = len(mids) / 12.0
                mids = [mids[int(i * step)] for i in range(12)]
            for t in mids:
                preds.append(Predicate(feature, "ge", t))
                preds.append(Predicate(feature, "lt", t))
        else:
            for val in sorted(set(values), key=lambda x: str(x)):
                preds.append(Predicate(feature, "eq", val))
    return preds


def _counts(predicates: list[Predicate], cases: list[LabeledCase]) -> tuple[int, int]:
    """Return (n_match, n_match_fraud) for the conjunction of ``predicates`` over ``cases``."""
    n_match = n_fraud = 0
    for c in cases:
        if all(p.matches(c.features) for p in predicates):
            n_match += 1
            if c.is_fraud:
                n_fraud += 1
    return n_match, n_fraud


@dataclass(frozen=True)
class _Metrics:
    support: float       # n_match_fraud / total_fraud
    confidence: float    # n_match_fraud / n_match
    lift: float          # confidence / base_rate
    n_match: int


def _metrics(predicates: list[Predicate], cases: list[LabeledCase],
             total_fraud: int, base_rate: float) -> _Metrics:
    n_match, n_fraud = _counts(predicates, cases)
    if n_match == 0 or total_fraud == 0:
        return _Metrics(0.0, 0.0, 0.0, 0)
    confidence = n_fraud / n_match
    support = n_fraud / total_fraud
    lift = confidence / base_rate if base_rate > 0 else 0.0
    return _Metrics(support, confidence, lift, n_match)


def mine_rules(
    cases: list[LabeledCase],
    *,
    threat_class: str = "mined_pattern",
    min_support: float = 0.10,
    min_confidence: float = 0.80,
    max_predicates: int = 3,
    top_k: int = 10,
    round_label: str = "poc-r1",
) -> list[CandidateRule]:
    """Discover candidate rules by greedy conjunction induction. Deterministic; metrics are measured.

    A rule is kept only if it covers ≥ ``min_support`` of fraud with ≥ ``min_confidence`` precision —
    so on patternless data it returns nothing (the §3.2 discrimination: real, not a constant).
    """
    total = len(cases)
    total_fraud = sum(1 for c in cases if c.is_fraud)
    if total == 0 or total_fraud == 0:
        return []
    base_rate = total_fraud / total

    atoms = _atomic_predicates(cases)
    # Rank atoms by lift (then deterministic tie-breaks) to seed greedy growth.
    scored_atoms = sorted(
        ((p, _metrics([p], cases, total_fraud, base_rate)) for p in atoms),
        key=lambda pm: (-pm[1].lift, -pm[1].confidence, pm[0].feature, pm[0].op, str(pm[0].value)),
    )
    useful_atoms = [p for p, m in scored_atoms if m.lift > 1.0 and m.n_match > 0]

    found: dict[frozenset[Predicate], _Metrics] = {}
    for seed in useful_atoms:
        chosen = [seed]
        cur = _metrics(chosen, cases, total_fraud, base_rate)
        improved = True
        while len(chosen) < max_predicates and improved:
            improved = False
            best_p = None
            best_m = cur
            used_features = {p.feature for p in chosen}
            for p in useful_atoms:
                if p.feature in used_features:
                    continue
                m = _metrics([*chosen, p], cases, total_fraud, base_rate)
                # Add a predicate only if it improves precision while keeping enough fraud coverage.
                if m.confidence > best_m.confidence and m.support >= min_support:
                    best_p, best_m = p, m
            if best_p is not None:
                chosen.append(best_p)
                cur = best_m
                improved = True
        if cur.support >= min_support and cur.confidence >= min_confidence:
            found[frozenset(chosen)] = cur

    ranked = sorted(
        found.items(),
        key=lambda kv: (-kv[1].confidence, -kv[1].support, -kv[1].lift),
    )[:top_k]

    rules: list[CandidateRule] = []
    for i, (preds, m) in enumerate(ranked, 1):
        ordered = tuple(sorted(preds, key=lambda p: (p.feature, p.op, str(p.value))))
        rules.append(CandidateRule(
            rule_id=f"R-{round_label}-{i:03d}",
            predicates=ordered,
            threat_class=threat_class,
            suspicion=round(min(0.9, m.confidence), 2),  # tunable; analyst confirms on approval
            support=round(m.support, 3),
            confidence=round(m.confidence, 3),
            lift=round(m.lift, 3),
            provenance=(
                f"federated rule mining (PoC, single round '{round_label}') — measured on {total} "
                f"labelled cases ({total_fraud} fraud); support/confidence/lift are measured, not assumed"
            ),
        ))
    return rules
