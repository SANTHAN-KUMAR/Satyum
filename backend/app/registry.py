"""Mode-keyed analyzer registry — structurally enforces the mode-tagging invariant (CLAUDE.md §1).

The orchestrator asks the registry for the analyzers valid in the current intake mode; a ``FILE``
analyzer can therefore never be handed a ``CAMERA`` frame (and vice-versa). ``ANY`` analyzers run in
both. Registration order is preserved and combined with an optional ``order`` attribute so Tier-1
ordering (signature before the PDF-only red flag) is deterministic.
"""

from __future__ import annotations

from app.contracts import Analyzer, Mode


class AnalyzerRegistry:
    def __init__(self) -> None:
        self._analyzers: list[Analyzer] = []

    def register(self, analyzer: Analyzer) -> Analyzer:
        if analyzer.mode not in (Mode.FILE, Mode.CAMERA, Mode.ANY):
            raise ValueError(f"analyzer '{analyzer.name}' has invalid mode {analyzer.mode!r}")
        self._analyzers.append(analyzer)
        return analyzer

    def for_mode(self, mode: Mode) -> list[Analyzer]:
        """Analyzers valid for ``mode``: those tagged exactly ``mode`` plus ``ANY``.

        Sorted by (layer, order, registration-index) so the waterfall runs Tier 1 -> 5 and, within
        a layer, dependencies first (e.g. signature before the red flag).
        """
        eligible = [
            (i, a) for i, a in enumerate(self._analyzers)
            if a.mode == mode or a.mode == Mode.ANY
        ]
        eligible.sort(key=lambda t: (t[1].layer, getattr(t[1], "order", 100), t[0]))
        return [a for _, a in eligible]

    def all(self) -> list[Analyzer]:
        return list(self._analyzers)
