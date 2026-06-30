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
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.registry_assembly import build_registry
from app.routes.interpret import router as interpret_router
from app.routes.registry import router as registry_router
from app.routes.ring import router as ring_router
from app.routes.rules import router as rules_router
from app.routes.sources import router as sources_router
from app.routes.verify import router as verify_router
from app.session import SessionManager
from federation.graph import EntityGraph
from federation.registry import FraudRegistry
from providers.registry import build_provider_registry
from risk.audit import AuditLedger, SqlAlchemyLedgerStore
from rule_mining.store import RuleStore


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


def _build_ledger(log: structlog.stdlib.BoundLogger) -> tuple[AuditLedger, str]:
    """Build the audit ledger. Durable (Postgres) when SATYUM_DATABASE_ENABLED and the DB is reachable;
    otherwise the in-memory store. If a durable store is requested but unreachable we FAIL SAFE to
    in-memory and surface it honestly via /api/health — never crash startup, never silently pretend the
    audit trail is durable when it is not (§3.5/§4)."""
    if not settings.database_enabled:
        return AuditLedger(), "in-memory"
    if SqlAlchemyLedgerStore is None:
        log.error("app.audit.sqlalchemy_missing_failsafe_to_memory")
        return AuditLedger(), "in-memory (sqlalchemy not installed)"
    try:
        store = SqlAlchemyLedgerStore(settings.database_url)
        store.count()  # force a real connection now so failure is caught at startup, not first write
        log.info("app.audit.durable", backend="postgres")
        return AuditLedger(store=store), "postgres"
    except Exception as exc:  # noqa: BLE001 — any DB failure must degrade safe, not crash the service
        log.error("app.audit.db_unreachable_failsafe_to_memory", error=repr(exc))
        return AuditLedger(), "in-memory (database unreachable)"


def create_app() -> FastAPI:
    """Application factory — builds the shared singletons and mounts routes."""
    _configure_logging()
    log = structlog.get_logger("app.main")

    app = FastAPI(
        title="Satyum — Document Integrity Verification",
        version="0.1.0",
        description="Provenance-first document-integrity verification for bank underwriting.",
    )

    # --- CORS (only when explicitly configured for a split-origin deploy) --------------------
    origins = settings.cors_origin_list
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,          # exact allow-list, never "*" (credentials-safe, §10)
            allow_methods=["GET", "POST"],  # the only verbs the API serves
            allow_headers=["Content-Type", "Accept"],
        )
        log.info("app.cors.enabled", origins=origins)

    # --- shared singletons (created once; read off app.state by the routes) -----------------
    app.state.ledger, app.state.audit_backend = _build_ledger(log)  # tamper-evident audit ledger
    app.state.rule_store = RuleStore()            # shared promoted-rule store (§6.3.1), live for the analyzer
    app.state.registry = build_registry(rule_store=app.state.rule_store)  # analyzers, wired in order
    app.state.sessions = SessionManager()         # ephemeral, in-memory; frames never persisted (§10)
    app.state.providers = build_provider_registry()  # source-pull adapters (DigiLocker / AA / PAN)
    app.state.fraud_registry = FraudRegistry()    # Layer-3 shared fraud registry (advisory, fail-open)
    app.state.entity_graph = EntityGraph()        # Layer-3 cross-bank ring-detection graph

    app.include_router(verify_router)
    app.include_router(sources_router)     # Tier-1 source-of-truth pulls (PAN / Aadhaar / DigiLocker / AA)
    app.include_router(interpret_router)
    app.include_router(registry_router)    # cross-bank fraud-hash registry (consortium)
    app.include_router(ring_router)        # cross-bank entity-graph ring evidence
    app.include_router(rules_router)       # FL-discovered rule mining + analyst promotion

    @app.get("/api/health")
    async def health() -> dict[str, object]:
        ok, broken = app.state.ledger.verify_chain()
        return {
            "status": "ok",
            "analyzers": len(app.state.registry.all()),
            "active_sessions": app.state.sessions.active_count(),
            "audit_backend": app.state.audit_backend,   # "postgres" | "in-memory[ …]" — honest, not assumed
            "audit_chain_intact": ok,
            "audit_first_broken_seq": broken,
        }

    log.info("app.startup", analyzers=len(app.state.registry.all()))
    return app


app = create_app()
