"""Satyum FastAPI application — the verification waterfall API (ADR-002, CLAUDE.md §1/§4).

Composition root: builds the single shared :class:`AuditLedger` (tamper-evident, hash-chained),
the fully-wired :class:`AnalyzerRegistry`, and the ephemeral :class:`SessionManager`, then mounts the
verify routes. structlog is configured with ISO timestamps and a correlation-id-friendly renderer so
every log line can be tied to a session — and customer document bytes / PII are NEVER logged (§10).

Run (from ``backend/``):

    uvicorn app.main:app --reload
"""

from __future__ import annotations

import logging

import structlog
from fastapi import FastAPI

from app.registry_assembly import build_registry
from app.routes.verify import router as verify_router
from app.session import SessionManager
from risk.audit import AuditLedger


def _configure_logging() -> None:
    """Structured JSON logs with a timestamp and level; correlation ids bound per-request (§4)."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def create_app() -> FastAPI:
    """Application factory — builds the shared singletons and mounts routes."""
    _configure_logging()
    log = structlog.get_logger("app.main")

    app = FastAPI(
        title="Satyum — Document Integrity Verification",
        version="0.1.0",
        description="Provenance-first document-integrity verification for bank underwriting.",
    )

    # --- shared singletons (created once; read off app.state by the routes) -----------------
    app.state.ledger = AuditLedger()              # ONE tamper-evident audit ledger for the process
    app.state.registry = build_registry()         # every analyzer, wired in dependency order
    app.state.sessions = SessionManager()         # ephemeral, in-memory; frames never persisted (§10)

    app.include_router(verify_router)

    @app.get("/api/health")
    async def health() -> dict[str, object]:
        ok, broken = app.state.ledger.verify_chain()
        return {
            "status": "ok",
            "analyzers": len(app.state.registry.all()),
            "active_sessions": app.state.sessions.active_count(),
            "audit_chain_intact": ok,
            "audit_first_broken_seq": broken,
        }

    log.info("app.startup", analyzers=len(app.state.registry.all()))
    return app


app = create_app()
