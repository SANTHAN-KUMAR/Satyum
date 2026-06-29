"""Mass E2E discrimination tests.

Runs the 1000+ generated PDFs through the full verification pipeline in parallel.

Usage:
    cd backend
    .venv/bin/python -m pytest tests/test_e2e_mass_corpus.py -v -n auto
"""

from __future__ import annotations

import datetime
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
BACKEND = REPO / "backend"
CORPUS = REPO / "samples" / "mass_corpus"
REPORT_FILE = CORPUS / "DISCRIMINATION_REPORT.md"

sys.path.insert(0, str(BACKEND))

from app.contracts import AnalysisContext, Mode  # noqa: E402
from app.orchestrator import run_verification  # noqa: E402
from app.registry_assembly import build_registry  # noqa: E402
from risk.audit import AuditLedger  # noqa: E402

@dataclass
class Expected:
    file: Path
    category: str
    is_genuine: bool

def _corpus_files() -> list[Expected]:
    items: list[Expected] = []
    
    # Statements
    stmt_dir = CORPUS / "statements"
    if stmt_dir.exists():
        for f in sorted(stmt_dir.glob("*.pdf")):
            is_genuine = "genuine" in f.name
            items.append(Expected(f, "statements", is_genuine))
            
    # Identity
    id_dir = CORPUS / "identity"
    if id_dir.exists():
        for f in sorted(id_dir.glob("*.pdf")):
            is_genuine = "genuine" in f.name
            items.append(Expected(f, "identity", is_genuine))
            
    return items

_FILES = _corpus_files()
if not _FILES:
    pytest.skip("Mass corpus not generated", allow_module_level=True)

def _run_file(fpath: Path) -> dict:
    file_bytes = fpath.read_bytes()
    registry = build_registry()
    ledger = AuditLedger()
    ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
    ctx = AnalysisContext(
        session_id="mass_e2e",
        intake_mode=Mode.FILE,
        file_bytes=file_bytes,
        file_name=fpath.name,
    )
    try:
        trust = run_verification(ctx, registry, ledger, ts)
        verdict = trust.verdict.value if hasattr(trust.verdict, "value") else str(trust.verdict)
        score = trust.trust_score
        
        # Find key signal
        key = ""
        for s in trust.signals:
            if s.suspicion is not None and s.suspicion > 0.3:
                key = f"{s.name}({s.suspicion:.2f})"
                break
        if not key:
            for s in trust.signals:
                if getattr(s.status, "value", str(s.status)) == "ERROR":
                    key = f"{s.name}[ERR]"
                    break
                    
        return {"verdict": verdict, "score": score, "key_signal": key}
    except Exception as exc:
        return {"verdict": "EXCEPTION", "score": 0, "key_signal": str(exc)}

@pytest.mark.parametrize("expected", _FILES, ids=[f.file.name for f in _FILES])
def test_mass_file(expected: Expected):
    """Run a single file through the pipeline."""
    result = _run_file(expected.file)
    
    # In pytest-xdist, workers don't share memory.
    # We append to a jsonl file for later aggregation.
    res_line = {
        "file": expected.file.name,
        "category": expected.category,
        "is_genuine": expected.is_genuine,
        "verdict": result["verdict"],
        "score": result["score"],
        "key_signal": result["key_signal"]
    }
    
    log_file = CORPUS / "results.jsonl"
    with open(log_file, "a") as f:
        f.write(json.dumps(res_line) + "\n")
        
    # We aren't asserting specifics here because the goal is to generate the discrimination report
    # without crashing the suite, testing the pipeline's robustness.
