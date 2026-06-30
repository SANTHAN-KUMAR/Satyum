import logging
from typing import Any
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from interpretability import (
    NarrativeReport,
    CopilotResponse,
    CopilotMessage,
    generate_narrative,
    ask_copilot
)

router = APIRouter(prefix="/api/interpret", tags=["interpretability"])
logger = logging.getLogger(__name__)

class NarrativeRequest(BaseModel):
    evidence_pack: dict[str, Any]

class CopilotRequest(BaseModel):
    evidence_pack: dict[str, Any]
    question: str
    history: list[CopilotMessage] = []

@router.post("/narrative", response_model=NarrativeReport)
async def get_narrative(request: NarrativeRequest):
    """Generates the plain-English summary for a completed session based on the provided evidence pack."""
    report = await generate_narrative(request.evidence_pack)
    return report

@router.post("/ask", response_model=CopilotResponse)
async def ask_question(request: CopilotRequest):
    """Interactive Q&A Copilot for the underwriter."""
    response = await ask_copilot(
        question=request.question,
        evidence_pack=request.evidence_pack,
        chat_history=request.history
    )
    return response
