import logging
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from interpretability import CopilotMessage, CopilotResponse, NarrativeReport, ask_copilot, generate_narrative

router = APIRouter(prefix="/api/interpret", tags=["interpretability"])
logger = logging.getLogger(__name__)

class NarrativeRequest(BaseModel):
    evidence_pack: dict[str, Any]

class CopilotRequest(BaseModel):
    # label -> that document's full evidence pack. A single-document Console session sends a one-entry
    # map (e.g. {"dad_canara_statement.pdf": {...}}); the case-accumulation page sends every document
    # verified so far in that case, so the SAME copilot can answer a question about any of them
    # (interpretability/copilot.py — one contract, not a special case per page).
    case_documents: dict[str, dict[str, Any]]
    question: str
    history: list[CopilotMessage] = []

@router.post("/narrative", response_model=NarrativeReport)
async def get_narrative(request: NarrativeRequest):
    """Generates the plain-English summary for a completed session based on the provided evidence pack."""
    report = await generate_narrative(request.evidence_pack)
    return report

@router.post("/ask", response_model=CopilotResponse)
async def ask_question(request: CopilotRequest):
    """Interactive Q&A Copilot, scoped to whichever document(s) are in request.case_documents."""
    response = await ask_copilot(
        question=request.question,
        case_documents=request.case_documents,
        chat_history=request.history
    )
    return response
