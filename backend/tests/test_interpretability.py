"""Tests for the interpretability ("MCP" insight) layer.

The layer only *explains* the immutable evidence pack; it must never be able to change a verdict. The
security-critical invariant is the **firewall** (interpretability/firewall.py): any LLM narrative that
contradicts the deterministic verdict is discarded in favour of the deterministic fallback. These tests
exercise that boundary plus the config decoupling — all pure logic, no live LLM (CLAUDE.md §3.2/§8).
"""

from __future__ import annotations

from interpretability.fallback import build_fallback_narrative
from interpretability.firewall import check_guardrails
from interpretability.mcp_client import _resolve_interpreter, interpreter_available


def _pack(verdict: str) -> dict:
    return {
        "session_id": "sess-x",
        "verdict": verdict,
        "document_type": "BANK_STATEMENT",
        "intake_mode": "FILE",
        "reasons": ["pades_signature: INVALID — chain does not reach the pinned anchor"],
    }


# --- firewall: contradiction is discarded ---------------------------------------------------------

def test_firewall_discards_approve_language_when_verdict_rejected():
    """An LLM that says 'approve/proceed' on a REJECTED case must be discarded (fall back)."""
    pack = _pack("REJECTED")
    rogue = {
        "summary_paragraph": "Looks fine.",
        "findings_paragraph": "Nothing wrong here.",
        "action_paragraph": "We recommend you approve and proceed with the loan.",
    }
    report = check_guardrails(rogue, pack)
    assert report.is_fallback is True  # discarded
    assert report.verdict == "REJECTED"  # true verdict preserved
    # the rogue 'approve' text must NOT survive into the action paragraph
    assert "approve and proceed" not in report.action_paragraph.lower()


def test_firewall_discards_reject_language_when_verdict_approved():
    pack = _pack("APPROVED")
    rogue = {
        "summary_paragraph": "Suspicious.",
        "findings_paragraph": "Something is off.",
        "action_paragraph": "We must reject and decline this application.",
    }
    report = check_guardrails(rogue, pack)
    assert report.is_fallback is True
    assert report.verdict == "APPROVED"


def test_firewall_passes_consistent_narrative_and_overrides_verdict():
    """A consistent narrative passes; the verdict is ALWAYS taken from the pack, never the LLM."""
    pack = _pack("REJECTED")
    good = {
        "verdict": "APPROVED",  # the LLM tries to assert its own verdict — must be ignored
        "summary_paragraph": "A bank statement was analysed.",
        "findings_paragraph": "The digital signature is invalid, indicating tampering.",
        "action_paragraph": "Reject and escalate to fraud operations.",
    }
    report = check_guardrails(good, pack)
    assert report.is_fallback is False
    assert report.verdict == "REJECTED"  # overridden from the pack, not the LLM's "APPROVED"
    assert "signature is invalid" in report.findings_paragraph.lower()


def test_firewall_litmus_constant_return_would_fail():
    """Guard against a no-op firewall: if check_guardrails just returned the narrative unchanged
    (never discarding), the contradiction test above would pass rogue 'approve' text through. This
    asserts the discriminating behaviour directly."""
    pack = _pack("REJECTED")
    rogue = {"summary_paragraph": "x", "findings_paragraph": "y",
             "action_paragraph": "approve this now"}
    report = check_guardrails(rogue, pack)
    assert report.is_fallback is True  # a constant 'return report' here would make this False


# --- deterministic fallback -----------------------------------------------------------------------

def test_fallback_is_deterministic_and_carries_verdict_and_reasons():
    pack = _pack("REJECTED")
    fb = build_fallback_narrative(pack)
    assert fb.is_fallback is True
    assert fb.verdict == "REJECTED"
    assert "REJECTED" in fb.summary_paragraph
    assert "pades_signature" in fb.findings_paragraph  # the structured reason is surfaced


# --- config decoupling: interpreter independent of the vision reader -------------------------------

def test_interpreter_uses_dedicated_settings_when_set(monkeypatch):
    import app.config as cfg
    monkeypatch.setattr(cfg.settings, "interpret_provider", "deepseek")
    monkeypatch.setattr(cfg.settings, "interpret_model", "deepseek-v4-pro")
    monkeypatch.setattr(cfg.settings, "interpret_api_key", "sk-test")
    monkeypatch.setattr(cfg.settings, "interpret_base_url", "")
    base, key, model = _resolve_interpreter()
    assert base == "https://api.deepseek.com"
    assert model == "deepseek-v4-pro"
    assert key == "sk-test"
    assert interpreter_available() is True


def test_interpreter_falls_back_to_vlm_reader_when_unset(monkeypatch):
    """A single-key deployment (no dedicated interpreter) still narrates via the vlm_* credential."""
    import app.config as cfg
    for attr in ("interpret_provider", "interpret_model", "interpret_api_key", "interpret_base_url"):
        monkeypatch.setattr(cfg.settings, attr, "")
    monkeypatch.setattr(cfg.settings, "vlm_provider", "groq")
    monkeypatch.setattr(cfg.settings, "vlm_api_key", "gsk-test")
    monkeypatch.setattr(cfg.settings, "vlm_model", "llama-x")
    monkeypatch.setattr(cfg.settings, "vlm_base_url", "")
    base, key, model = _resolve_interpreter()
    assert base == "https://api.groq.com/openai/v1"
    assert key == "gsk-test"
    assert model == "llama-x"


def test_interpreter_unavailable_without_any_key(monkeypatch):
    import app.config as cfg
    for attr in ("interpret_provider", "interpret_api_key", "interpret_base_url"):
        monkeypatch.setattr(cfg.settings, attr, "")
    monkeypatch.setattr(cfg.settings, "vlm_api_key", "")
    monkeypatch.setattr(cfg.settings, "vlm_provider", "none")
    assert interpreter_available() is False
