"""Durable audit ledger (SqlAlchemyLedgerStore): the tamper-evident chain SURVIVES a restart and
still detects tampering when the records live in a real database.

Uses SQLite (a real SQLAlchemy-backed DB) so the test runs everywhere; the identical store class
drives Postgres in production. These would FAIL against an in-memory-only ledger (which loses the
chain on restart) and against a fake store (which couldn't detect a direct row edit).
"""

from __future__ import annotations

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine, text  # noqa: E402

from risk.audit import AuditLedger, SqlAlchemyLedgerStore  # noqa: E402


def _url(tmp_path) -> str:
    return f"sqlite:///{tmp_path / 'audit.db'}"


def test_durable_ledger_persists_across_a_restart(tmp_path):
    url = _url(tmp_path)
    led = AuditLedger(SqlAlchemyLedgerStore(url))
    led.record("2026-06-28T10:00:00Z", {"session_id": "a", "verdict": "APPROVED", "score": 90})
    led.record("2026-06-28T10:01:00Z", {"session_id": "b", "verdict": "REJECTED", "score": 5})
    head_before = led.head()

    # Simulate a process restart: a brand-new ledger + store over the SAME database file.
    reopened = AuditLedger(SqlAlchemyLedgerStore(url))
    assert reopened.head() == head_before                 # the chain survived the restart
    ok, broken = reopened.verify_chain()
    assert ok and broken is None
    assert [r.payload["session_id"] for r in reopened.records()] == ["a", "b"]


def test_durable_ledger_appends_continue_after_restart(tmp_path):
    url = _url(tmp_path)
    AuditLedger(SqlAlchemyLedgerStore(url)).record("2026-06-28T10:00:00Z", {"session_id": "a"})
    # A new process appends; seq/prev_hash must continue from the persisted tail, not restart at 0.
    led2 = AuditLedger(SqlAlchemyLedgerStore(url))
    rec = led2.record("2026-06-28T10:05:00Z", {"session_id": "b"})
    assert rec.seq == 1 and rec.prev_hash != "0" * 64
    ok, broken = led2.verify_chain()
    assert ok and broken is None


def test_durable_ledger_detects_direct_row_tampering(tmp_path):
    url = _url(tmp_path)
    led = AuditLedger(SqlAlchemyLedgerStore(url))
    led.record("2026-06-28T10:00:00Z", {"session_id": "a", "verdict": "REJECTED", "score": 5})
    led.record("2026-06-28T10:01:00Z", {"session_id": "b", "verdict": "APPROVED", "score": 90})

    # An attacker with DB write access flips a stored REJECTED verdict to APPROVED, bypassing the
    # ledger API entirely. The hash chain must catch it on the next verification.
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE audit_records SET payload = :p WHERE seq = 0"),
            {"p": '{"session_id": "a", "verdict": "APPROVED", "score": 95}'},
        )

    ok, broken = AuditLedger(SqlAlchemyLedgerStore(url)).verify_chain()
    assert ok is False and broken == 0                    # the forged row breaks the chain


def test_build_ledger_fails_safe_to_memory_on_unreachable_db():
    """§3.5/§4: requesting a durable store but failing to reach the DB must degrade to in-memory and
    SAY so — never crash startup, never pretend the audit trail is durable when it is not."""
    import structlog

    # _build_ledger reads the module-level `settings`; patch its fields for this check.
    from app import config as config_module
    from app.config import Settings
    from app.main import _build_ledger

    original = config_module.settings
    try:
        config_module.settings = Settings(
            database_enabled=True,
            database_url="postgresql+psycopg://x:x@127.0.0.1:1/nope",  # port 1 -> instant refuse
        )
        # main.py imported `settings` by value; patch there too.
        import app.main as main_module

        main_module.settings = config_module.settings
        ledger, backend = _build_ledger(structlog.get_logger("test"))
        assert "in-memory" in backend                     # degraded safe, did not raise
        rec = ledger.record("2026-06-28T00:00:00Z", {"x": 1})
        ok, _ = ledger.verify_chain()
        assert ok and rec.seq == 0
    finally:
        config_module.settings = original
        import app.main as main_module

        main_module.settings = original
