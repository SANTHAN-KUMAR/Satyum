"""Load the JSON rulebooks (``_shared.json`` + per-domain files) as the single source of truth.

ADR-004 makes the ontology authoritative: "the model reads, deterministic rules decide" — and the
deterministic side must read its vocabulary from one place, not duplicate it in code. This module
loads ``_shared.json`` once (cached) and exposes the value-type metadata the rest of the pipeline
needs *today*:

  * which value types are ``cross_read_critical`` — the numbers a forger edits, whose VLM read MUST
    be confirmed by the deterministic OCR cross-read (ADR-004 §5.2);
  * each value type's numeric match tolerance — so the cross-read and the Layer-4 rules agree on what
    "equal within rounding" means.

Layer 4 (rule packs) will extend this loader to read ``check_kinds`` and the per-domain rules; for
Layer 2 we only need the value-type semantics, so that is all this exposes now (YAGNI, CLAUDE.md §5).
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

# The ontology lives next to this module: backend/ontology/_shared.json
_ONTOLOGY_DIR = Path(__file__).resolve().parent
_SHARED_FILE = _ONTOLOGY_DIR / "_shared.json"

# Domain rulebooks the Layer-4 engine loads (one file per domain, sharing _shared.json's vocabulary).
_DOMAIN_FILES: dict[str, str] = {
    "financial": "financial.json",
    "land_title": "land_title.json",
    "legal_contract": "legal_contract.json",
}

# extraction_class values that mean "a deterministic reader must independently confirm this value".
# Sourced from _shared.json::extraction_classes; the only critical class is cross_read_critical.
_CROSS_READ_CLASS = "cross_read_critical"


@lru_cache(maxsize=1)
def load_shared_ontology() -> dict[str, Any]:
    """Parse and cache ``_shared.json``. Raises if the file is missing/malformed (fail-closed:

    a verification pipeline must never run on a half-loaded rulebook — better to refuse to start).
    """
    with _SHARED_FILE.open(encoding="utf-8") as fh:
        data = json.load(fh)
    if "value_types" not in data:
        raise ValueError(f"{_SHARED_FILE} is missing the required 'value_types' section")
    return data


def value_type_meta(value_type: str) -> dict[str, Any] | None:
    """Return the raw metadata dict for a value type (``Money``, ``Date``, …), or ``None``.

    ``None`` means the engine does not recognise the type — the caller treats it as a plain,
    non-cross-read string (never silently coerces it into a trusted number).
    """
    return load_shared_ontology()["value_types"].get(value_type)


def known_value_types() -> frozenset[str]:
    """The set of value-type names the ontology defines (used to validate VLM-reported types)."""
    return frozenset(load_shared_ontology()["value_types"].keys())


def is_cross_read_critical(value_type: str) -> bool:
    """True iff a value of this type must be confirmed by the deterministic OCR cross-read.

    Unknown types default to ``False`` (they are not numbers we re-read); the cross-read control
    only governs the ``cross_read_critical`` numeric types (Money, Count, Integer, Percentage, …).
    """
    meta = value_type_meta(value_type)
    return bool(meta and meta.get("extraction_class") == _CROSS_READ_CLASS)


def cross_read_critical_types() -> frozenset[str]:
    """All value types flagged ``cross_read_critical`` in the ontology."""
    vt = load_shared_ontology()["value_types"]
    return frozenset(name for name, meta in vt.items() if meta.get("extraction_class") == _CROSS_READ_CLASS)


def numeric_tolerance(value_type: str, *, arithmetic_abs_tolerance: float) -> float:
    """The absolute tolerance for comparing two reads of a numeric value type.

    ``Money`` (and anything referencing ``arithmetic_abs_tolerance``) uses the engine-wide rupee
    rounding tolerance passed in from ``settings``; a type with its own literal ``tolerance`` (e.g.
    ``Percentage``: 0.01) uses that. A type with no numeric match falls back to the engine tolerance
    so the cross-read never compares with an undefined slack.
    """
    meta = value_type_meta(value_type)
    if not meta:
        return float(arithmetic_abs_tolerance)
    match = meta.get("match", {})
    if match.get("tolerance_ref") == "arithmetic_abs_tolerance":
        return float(arithmetic_abs_tolerance)
    if "tolerance" in match:
        return float(match["tolerance"])
    return float(arithmetic_abs_tolerance)


@lru_cache(maxsize=8)
def load_domain(domain: str) -> dict[str, Any]:
    """Parse and cache a domain rulebook (``financial`` / ``land_title`` / ``legal_contract``).

    Raises on an unknown domain or a malformed/absent file — a rule pack must never run on a
    half-loaded rulebook (fail-closed at startup, like :func:`load_shared_ontology`).
    """
    if domain not in _DOMAIN_FILES:
        raise ValueError(f"unknown ontology domain {domain!r}; known: {sorted(_DOMAIN_FILES)}")
    path = _ONTOLOGY_DIR / _DOMAIN_FILES[domain]
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    if "rules" not in data:
        raise ValueError(f"{path} is missing the required 'rules' section")
    return data


@lru_cache(maxsize=8)
def rule_table(domain: str) -> dict[str, dict[str, Any]]:
    """Map ``rule_id -> rule definition`` for a domain (so a pack reads its metadata by id)."""
    return {rule["id"]: rule for rule in load_domain(domain).get("rules", [])}


def severity_value(severity_ref: str) -> float:
    """Resolve a ``severity_ref`` (``hard_tamper``, ``soft`` …) to its calibrated suspicion in [0,1].

    Sourced from ``_shared.json::severity_bands`` so every rule pack scores from the SAME calibrated
    table (no per-rule magic numbers, CLAUDE.md §5). An unknown ref fails closed to the highest band.
    """
    bands = load_shared_ontology().get("severity_bands", {})
    if severity_ref in bands:
        return float(bands[severity_ref])
    # Unknown severity ⇒ treat as the hardest (never silently down-weight a violation we can't classify).
    return float(max((v for v in bands.values() if isinstance(v, (int, float))), default=0.9))
