import json
from typing import Any


def get_signal_detail(evidence_pack: dict[str, Any], signal_name: str) -> dict[str, Any]:
    """Retrieve the full details and reason for a specific signal."""
    signals = evidence_pack.get("signals", [])
    for s in signals:
        if s.get("name") == signal_name:
            return s
    return {"error": f"Signal '{signal_name}' not found in the evidence pack."}

def get_evidence_regions(evidence_pack: dict[str, Any]) -> list[dict[str, Any]]:
    """Retrieve all bounding boxes and regions that indicate tampering."""
    return evidence_pack.get("tamper_evidence_regions", [])

def get_provenance_detail(evidence_pack: dict[str, Any]) -> dict[str, Any]:
    """Retrieve details about the cryptographic signature and source verification."""
    return evidence_pack.get("provenance", {})

def get_overall_verdict(evidence_pack: dict[str, Any]) -> dict[str, Any]:
    """Retrieve the overall verdict, score, and summary reasons."""
    return {
        "verdict": evidence_pack.get("verdict"),
        "trust_score": evidence_pack.get("trust_score"),
        "tier_reached": evidence_pack.get("tier_reached"),
        "reasons": evidence_pack.get("reasons"),
    }

def get_network_intelligence(evidence_pack: dict[str, Any]) -> list[dict[str, Any]]:
    """Retrieve any cross-session fraud ring or anomaly findings."""
    return evidence_pack.get("network_intelligence", [])

# Tool schemas for OpenAI API format
COPILOT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_signal_detail",
            "description": "Retrieve the full details, suspicion score, and reasoning for a specific forensic signal (e.g. arithmetic_consistency, cross_document_consistency).",
            "parameters": {
                "type": "object",
                "properties": {
                    "signal_name": {
                        "type": "string",
                        "description": "The exact name of the signal to query."
                    }
                },
                "required": ["signal_name"],
                "additionalProperties": False
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_evidence_regions",
            "description": "Retrieve all bounding boxes and regions on the document that indicate tampering.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_provenance_detail",
            "description": "Retrieve details about the cryptographic signature and source verification of the document.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_overall_verdict",
            "description": "Retrieve the overall verdict, trust score, and summary reasons for the decision.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_network_intelligence",
            "description": "Retrieve any cross-session fraud ring or anomaly findings for this document.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False
            }
        }
    }
]

def execute_tool(name: str, arguments: dict, evidence_pack: dict[str, Any]) -> str:
    try:
        if name == "get_signal_detail":
            res = get_signal_detail(evidence_pack, arguments.get("signal_name", ""))
        elif name == "get_evidence_regions":
            res = get_evidence_regions(evidence_pack)
        elif name == "get_provenance_detail":
            res = get_provenance_detail(evidence_pack)
        elif name == "get_overall_verdict":
            res = get_overall_verdict(evidence_pack)
        elif name == "get_network_intelligence":
            res = get_network_intelligence(evidence_pack)
        else:
            return json.dumps({"error": f"Unknown tool: {name}"})
        return json.dumps(res)
    except Exception as e:
        return json.dumps({"error": str(e)})
