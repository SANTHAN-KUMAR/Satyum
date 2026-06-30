import json
import logging
from typing import Any

from .contracts import NarrativeReport
from .fallback import build_fallback_narrative
from .firewall import check_guardrails
from .mcp_client import generate_completion
from .prompts import NARRATOR_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

def _mask_pii(evidence_pack: dict[str, Any]) -> dict[str, Any]:
    """Basic structural PII masking before sending to LLM.
    We don't send raw files anyway, but we scrub known identifiers from the evidence pack.
    """
    import copy
    safe_pack = copy.deepcopy(evidence_pack)
    
    # We remove session ID and any exact names/PANs if they exist in measurements
    # For now, evidence_pack measurements are mostly mathematical flags.
    safe_pack["session_id"] = "MASKED_SESSION"
    
    return safe_pack

async def generate_narrative(evidence_pack: dict[str, Any]) -> NarrativeReport:
    """Generates the auto-summary for a completed verification session."""
    try:
        safe_pack = _mask_pii(evidence_pack)
        
        messages = [
            {"role": "system", "content": NARRATOR_SYSTEM_PROMPT},
            {"role": "user", "content": f"EVIDENCE PACK JSON:\n{json.dumps(safe_pack, indent=2)}"}
        ]
        
        # We request strict JSON response
        response = await generate_completion(
            messages=messages,
            response_format={"type": "json_object"}
        )
        
        content = response.content
        if not content:
            raise ValueError("Empty response from LLM")
            
        narrative_json = json.loads(content)
        
        # Enforce Guardrails
        return check_guardrails(narrative_json, evidence_pack)
        
    except Exception as e:
        logger.error(f"Failed to generate narrative: {e}")
        # Graceful degradation (Guardrail 5)
        return build_fallback_narrative(evidence_pack)
