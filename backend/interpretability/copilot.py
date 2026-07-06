import json
import logging
from typing import Any

from .contracts import CopilotMessage, CopilotResponse
from .mcp_client import generate_completion
from .prompts import COPILOT_SYSTEM_PROMPT
from .tools import COPILOT_TOOLS, execute_tool

logger = logging.getLogger(__name__)

async def ask_copilot(
    question: str,
    case_documents: dict[str, dict[str, Any]],
    chat_history: list[CopilotMessage] | None = None
) -> CopilotResponse:
    """Handles an interactive Q&A turn with the copilot, executing any required tools.

    ``case_documents`` maps a human-readable label (a filename, or a doc type like "bank_statement")
    to that document's full evidence pack. A single-document Console session passes a one-entry map;
    the case-accumulation page passes every document verified so far in that case — so the SAME copilot
    can answer "what was on the bank statement" while the underwriter is looking at the PAN, without
    forgetting anything as documents are added (CLAUDE.md §4 — one stable contract, not a special case
    per page).
    """
    history = chat_history or []

    # We initialize the system context. We don't inject the full evidence pack(s) into the context
    # window directly; instead we let the model use tools to fetch what it needs, ensuring a true MCP
    # flow. We do give it an upfront map of what's in scope so it knows whether to specify a document.
    if len(case_documents) == 1:
        ((_, only_pack),) = case_documents.items()
        initial_context = (
            f"Current Session ID: {only_pack.get('session_id', 'Unknown')}\n"
            f"Overall Verdict: {only_pack.get('verdict', 'Unknown')}\n"
        )
    else:
        lines = "\n".join(
            f"- {label}: verdict={pack.get('verdict')}, trust_score={pack.get('trust_score')}"
            for label, pack in case_documents.items()
        )
        initial_context = (
            f"This case has {len(case_documents)} documents in scope:\n{lines}\n"
            "Every tool takes an optional 'document' argument naming which one to read — use it "
            "whenever the question is about a specific document; call list_case_documents if unsure.\n"
        )

    messages = [
        {"role": "system", "content": COPILOT_SYSTEM_PROMPT + "\n\n" + initial_context}
    ]
    
    for msg in history:
        messages.append({"role": msg.role, "content": msg.content})
        
    messages.append({"role": "user", "content": question})
    
    tool_calls_made = []
    
    # Loop to handle up to 3 sequential tool calls
    for _ in range(3):
        response = await generate_completion(messages=messages, tools=COPILOT_TOOLS)
        
        # If the model called a tool
        if response.tool_calls:
            # Add the model's message with the tool call to history
            messages.append(response.model_dump(include={"role", "content", "tool_calls"}))
            
            for tool_call in response.tool_calls:
                function_name = tool_call.function.name
                arguments = json.loads(tool_call.function.arguments)
                
                logger.info(f"Copilot invoked tool: {function_name}")
                tool_calls_made.append({"tool": function_name, "arguments": arguments})
                
                # Execute tool against the frozen, per-document evidence packs in scope
                tool_result = execute_tool(function_name, arguments, case_documents)
                
                # Append tool response
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": tool_result
                })
        else:
            # We got a final text answer
            return CopilotResponse(
                response=response.content or "",
                tool_calls_made=tool_calls_made
            )
            
    # If we exceeded the loop limit, force a final generation without tools
    final_response = await generate_completion(messages=messages)
    return CopilotResponse(
        response=final_response.content or "I needed too many steps to answer that. Please rephrase.",
        tool_calls_made=tool_calls_made
    )
