"""Layer 2 — VLM document understanding → canonical claim graph (ADR-004 §2, §5).

The package that turns an *arbitrary* document image into typed, box-grounded, cross-read-verified
claims. Structure (single responsibility per module):

  * ``interface``  — the ``VLMExtractor`` contract, the typed ``RawExtraction`` it returns, ``PageImage``.
  * ``schema``     — the structured tool schema + injection-hardened system prompt + prompt hash.
  * ``anthropic_extractor`` — the cloud POC extractor (Claude), built to the interface.
  * ``routing``    — deterministic script detection + the language-routed extractor (English ↔ Indic).
  * ``cross_read`` — the ensemble of independent deterministic OCR readers that re-verify every number.
  * ``builder``    — assembles the verified ``ClaimGraph`` (hostile-input validation, §5.4).
  * ``render``     — renders a document page to a ``PageImage`` (pixels + dims + text layer).
  * ``analyzer``   — the orchestrator-facing ``VLMClaimGraphAnalyzer`` (Layer 3, FILE).

The decision path never lives here: this package *reads*; Layers 4/6/7 *decide* (ADR-004 §2).
"""
