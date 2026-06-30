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
    evidence_pack: dict[str, Any], 
    chat_history: list[CopilotMessage] | None = None
) -> CopilotResponse:
    """Handles an interactive Q&A turn with the copilot, executing any required tools."""
    history = chat_history or []
    
    # We initialize the system context. We don't inject the full evidence pack into the context window
    # directly for the copilot; instead, we let it use tools to fetch what it needs, ensuring a true MCP flow.
    # However, to give it initial context, we provide the overall verdict.
    
    session_id = evidence_pack.get("session_id", "Unknown")
    verdict = evidence_pack.get("verdict", "Unknown")
    
    initial_context = f"Current Session ID: {session_id}\nOverall Verdict: {verdict}\n"
    
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
                
                # Execute tool against the frozen evidence pack
                tool_result = execute_tool(function_name, arguments, evidence_pack)
                
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
