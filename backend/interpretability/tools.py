import json
from typing import Any


def get_signal_detail(pack: dict[str, Any], signal_name: str) -> dict[str, Any]:
    """Retrieve the full details and reason for a specific signal."""
    signals = pack.get("signals", [])
    for s in signals:
        if s.get("name") == signal_name:
            return s
    return {"error": f"Signal '{signal_name}' not found in this document's evidence pack."}

def get_evidence_regions(pack: dict[str, Any]) -> list[dict[str, Any]]:
    """Retrieve all bounding boxes and regions that indicate tampering."""
    return pack.get("tamper_evidence_regions", [])

def get_provenance_detail(pack: dict[str, Any]) -> dict[str, Any]:
    """Retrieve details about the cryptographic signature and source verification."""
    return pack.get("provenance", {})

def get_overall_verdict(pack: dict[str, Any]) -> dict[str, Any]:
    """Retrieve the overall verdict, score, and summary reasons."""
    return {
        "verdict": pack.get("verdict"),
        "trust_score": pack.get("trust_score"),
        "tier_reached": pack.get("tier_reached"),
        "reasons": pack.get("reasons"),
    }

def get_network_intelligence(pack: dict[str, Any]) -> list[dict[str, Any]]:
    """Retrieve any cross-session fraud ring or anomaly findings."""
    return pack.get("network_intelligence", [])

def list_case_documents(case_documents: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Enumerate every document the copilot currently has in scope, with its verdict — the model calls
    this first when more than one document is available, then targets a specific one via the
    ``document`` argument on the other tools."""
    return [
        {"document": label, "verdict": pack.get("verdict"), "trust_score": pack.get("trust_score")}
        for label, pack in case_documents.items()
    ]

# Tool schemas for OpenAI API format. Every per-document tool carries the SAME optional "document"
# parameter: which document (by the label returned from list_case_documents) to read. Omit it when
# exactly one document is in scope (the ordinary single-document Console session) — execute_tool
# resolves that case for free; with more than one document in scope it must be given explicitly.
_DOCUMENT_PARAM = {
    "document": {
        "type": "string",
        "description": (
            "Which document to read, by the label from list_case_documents (e.g. a filename or doc "
            "type). Omit only when there is exactly one document in scope."
        ),
    }
}

COPILOT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_case_documents",
            "description": (
                "List every document in scope with its verdict. Call this first whenever more "
                "than one document might be in scope."
            ),
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
            "name": "get_signal_detail",
            "description": (
                "Retrieve the full details and reasoning for one forensic signal "
                "(e.g. arithmetic_consistency) on one document."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    **_DOCUMENT_PARAM,
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
            "description": "Retrieve all bounding boxes and regions on one document that indicate tampering.",
            "parameters": {
                "type": "object",
                "properties": {**_DOCUMENT_PARAM},
                "additionalProperties": False
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_provenance_detail",
            "description": "Retrieve the signature/source-verification detail for one document.",
            "parameters": {
                "type": "object",
                "properties": {**_DOCUMENT_PARAM},
                "additionalProperties": False
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_overall_verdict",
            "description": "Retrieve the overall verdict, trust score, and summary reasons for one document.",
            "parameters": {
                "type": "object",
                "properties": {**_DOCUMENT_PARAM},
                "additionalProperties": False
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_network_intelligence",
            "description": "Retrieve any cross-session fraud ring or anomaly findings for one document.",
            "parameters": {
                "type": "object",
                "properties": {**_DOCUMENT_PARAM},
                "additionalProperties": False
            }
        }
    }
]

def _resolve_document(
    case_documents: dict[str, dict[str, Any]], requested: str | None
) -> tuple[dict[str, Any] | None, str | None, str | None]:
    """Pick which document's evidence pack a tool call reads. Returns (pack, resolved_label, error)."""
    if requested:
        if requested in case_documents:
            return case_documents[requested], requested, None
        needle = requested.strip().lower()
        for label, pack in case_documents.items():
            if label.lower() == needle:
                return pack, label, None
        return None, None, (
            f"no document named {requested!r} in scope; call list_case_documents to see the options"
        )
    if len(case_documents) == 1:
        (label, pack), = case_documents.items()
        return pack, label, None
    if not case_documents:
        return None, None, "no document evidence available"
    return None, None, (
        "more than one document is in scope — specify which one via the 'document' argument "
        "(call list_case_documents first to see the options)"
    )

def execute_tool(name: str, arguments: dict, case_documents: dict[str, dict[str, Any]]) -> str:
    try:
        if name == "list_case_documents":
            return json.dumps(list_case_documents(case_documents))

        pack, resolved_label, error = _resolve_document(case_documents, arguments.get("document"))
        if error or pack is None:
            return json.dumps({"error": error or "no document evidence available"})

        if name == "get_signal_detail":
            res: Any = get_signal_detail(pack, arguments.get("signal_name", ""))
        elif name == "get_evidence_regions":
            res = get_evidence_regions(pack)
        elif name == "get_provenance_detail":
            res = get_provenance_detail(pack)
        elif name == "get_overall_verdict":
            res = get_overall_verdict(pack)
        elif name == "get_network_intelligence":
            res = get_network_intelligence(pack)
        else:
            return json.dumps({"error": f"Unknown tool: {name}"})

        # Tag which document this answer came from so a multi-document answer can cite it correctly.
        envelope: dict[str, Any] = {"document": resolved_label, "result": res}
        return json.dumps(envelope)
    except Exception as e:
        return json.dumps({"error": str(e)})
