"""Satyum domain ontology: the JSON rulebooks + the loader that makes them authoritative.

The rulebooks (``_shared.json`` + ``financial.json`` / ``land_title.json`` / ``legal_contract.json``)
are the single source of truth for value types, check kinds, and domain rules (ADR-004 Layer 4).
``loader.py`` parses them for the deterministic pipeline. See ``README.md`` for the format.
"""
