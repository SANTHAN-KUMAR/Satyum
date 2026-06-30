import logging
from typing import Any

from .contracts import NarrativeReport
from .fallback import build_fallback_narrative

logger = logging.getLogger(__name__)

def check_guardrails(narrative: dict[str, Any], evidence_pack: dict[str, Any]) -> NarrativeReport:
    """Enforces the structural firewall invariants.
    
    The LLM response MUST NOT contradict the deterministic verdict. If it does,
    it is discarded and we fall back to the deterministic output.
    """
    
    true_verdict = evidence_pack.get("verdict", "REVIEW")
    session_id = evidence_pack.get("session_id", "Unknown")
    
    # 1. Ensure all keys exist
    try:
        report = NarrativeReport(
            session_id=session_id,
            verdict=true_verdict, # ALWAYS override with the true verdict (Guardrail 2)
            summary_paragraph=narrative.get("summary_paragraph", ""),
            findings_paragraph=narrative.get("findings_paragraph", ""),
            action_paragraph=narrative.get("action_paragraph", ""),
            is_fallback=False
        )
    except Exception as e:
        logger.error(f"Guardrail failed (schema mismatch): {e}")
        return build_fallback_narrative(evidence_pack)
        
    # 2. Prevent verdict contradiction (Guardrail 4)
    # Simple keyword heuristic on the action_paragraph
    action_lower = report.action_paragraph.lower()
    
    if true_verdict == "REJECTED" and ("approve" in action_lower or "proceed" in action_lower):
        logger.warning("Guardrail triggered: LLM suggested approve but verdict is REJECTED.")
        return build_fallback_narrative(evidence_pack)
        
    if true_verdict == "APPROVED" and ("reject" in action_lower or "decline" in action_lower):
        logger.warning("Guardrail triggered: LLM suggested reject but verdict is APPROVED.")
        return build_fallback_narrative(evidence_pack)
        
    return report
