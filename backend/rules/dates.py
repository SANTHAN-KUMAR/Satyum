"""Shared Indian/Western date parsing for the rule packs and anomaly backbone (single source).

The value-type ``Date`` (``_shared.json``) lists the accepted input formats; this parser tries each and
returns ``None`` (never a guess) for anything it cannot read deterministically, so a rule comparing
dates simply treats an unparseable date as missing rather than inventing an order.
"""

from __future__ import annotations

from datetime import date, datetime

# Mirrors _shared.json value_types.Date.input_formats (+ full month name).
DATE_FORMATS: tuple[str, ...] = (
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%Y-%m-%d",
    "%d %b %Y",
    "%d %B %Y",
    "%d.%m.%Y",
)


def parse_date(value: str | None) -> date | None:
    """Parse a printed date string to a ``date`` using the accepted formats, or ``None``."""
    if not value:
        return None
    text = value.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except (ValueError, TypeError):
            continue
    return None
