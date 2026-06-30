from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class NarrativeReport(BaseModel):
    """The auto-generated plain-English summary of a verification session."""
    session_id: str
    verdict: str
    summary_paragraph: str
    findings_paragraph: str
    action_paragraph: str
    is_fallback: bool = False

class CopilotMessage(BaseModel):
    role: str
    content: str

class CopilotResponse(BaseModel):
    """The response from the interactive Q&A copilot."""
    response: str
    tool_calls_made: list[dict[str, Any]] = Field(default_factory=list)
