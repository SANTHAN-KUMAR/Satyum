"""End-to-end bundle verification tests (app/bundle.py): per-document waterfall + cross-document graph.

Drives the REAL path — entities are extracted by the registered EntityExtractionAnalyzer from injected
OCR words, then the bundle aggregates fail-closed. A consistent bundle is corroborated (not rejected on
cross-doc grounds); an identity mismatch across documents is REJECTED. Would FAIL against a constant.
"""

from __future__ import annotations

from app.bundle import verify_bundle
from app.contracts import AnalysisContext, Mode, SignalStatus, Verdict
from app.registry import AnalyzerRegistry
from forensics.entities import EntityExtractionAnalyzer
from risk.audit import AuditLedger

TS = "2026-06-28T12:00:00Z"


def _ocr_words(text: str) -> list[dict]:
    words: list[dict] = []
    for li, line in enumerate(text.strip().split("\n")):
        for wi, tok in enumerate(line.split()):
            words.append({
                "text": tok, "left": wi * 60, "top": li * 30, "width": 50, "height": 20,
                "conf": 0.9, "line_num": li, "block_num": 0,
            })
    return words


def _registry() -> AnalyzerRegistry:
    reg = AnalyzerRegistry()
    reg.register(EntityExtractionAnalyzer())
    return reg


def _doc(session_id: str, text: str) -> AnalysisContext:
    return AnalysisContext(
        session_id=session_id, intake_mode=Mode.FILE, file_bytes=b"%PDF-1.4",
        shared={"ocr": _ocr_words(text)},
    )


def test_bundle_consistent_identity_corroborates_not_rejected():
    docs = [
        ("doc1:stmt", _doc("s1", "Account Holder: John Smith\nPAN ABCDE1234F")),
        ("doc2:id", _doc("s2", "Name: Mr John A Smith\nPAN ABCDE1234F")),
    ]
    b = verify_bundle(docs, _registry(), AuditLedger(), TS, bundle_session_id="bundle-1")
    assert b.cross_document.status == SignalStatus.VALID
    assert b.cross_document.measurements["disagreeing_fields"] == []
    # Individual docs are REVIEW (no provenance/arithmetic), so a corroborated bundle is REVIEW —
    # corroboration is not a substitute for verification. But it is NOT rejected.
    assert b.bundle_verdict == Verdict.REVIEW


def test_bundle_pan_mismatch_is_rejected_fail_closed():
    docs = [
        ("doc1:stmt", _doc("s1", "Account Holder: John Smith\nPAN ABCDE1234F")),
        ("doc2:id", _doc("s2", "Name: John Smith\nPAN ZZZZZ9999Z")),
    ]
    b = verify_bundle(docs, _registry(), AuditLedger(), TS, bundle_session_id="bundle-2")
    assert "pan" in b.cross_document.measurements["disagreeing_fields"]
    assert b.bundle_verdict == Verdict.REJECTED
    assert b.bundle_score < 60.0
    assert b.fail_closed is True
    assert any("mismatch" in r.lower() for r in b.reasons)


def test_bundle_discriminates_consistent_from_mismatch():
    base = [("doc1", _doc("s1", "PAN ABCDE1234F\nName: Asha Rao"))]
    reg = _registry()
    consistent = verify_bundle(
        base + [("doc2", _doc("s2", "PAN ABCDE1234F\nName: Asha Rao"))],
        reg, AuditLedger(), TS, bundle_session_id="b3",
    )
    mismatch = verify_bundle(
        base + [("doc2", _doc("s3", "PAN ZZZZZ9999Z\nName: Asha Rao"))],  # hard PAN mismatch
        reg, AuditLedger(), TS, bundle_session_id="b4",
    )
    assert mismatch.bundle_score < consistent.bundle_score
    assert mismatch.bundle_verdict == Verdict.REJECTED


def test_bundle_decision_is_audited_in_the_hash_chain():
    led = AuditLedger()
    verify_bundle(
        [("d1", _doc("s1", "PAN ABCDE1234F")), ("d2", _doc("s2", "PAN ABCDE1234F"))],
        _registry(), led, TS, bundle_session_id="b5",
    )
    ok, broken = led.verify_chain()
    assert ok and broken is None
    assert any(r.payload.get("kind") == "bundle" for r in led.records())


class _BrokenRegistry:
    """A registry whose for_mode() raises — to exercise the bundle's per-document isolation (H3)."""

    def for_mode(self, _mode):  # noqa: ANN001
        raise RuntimeError("registry exploded")


def test_bundle_isolates_a_document_whose_verification_crashes():
    """H3 / §4: a hard failure inside one document's verification must NOT 500 the whole bundle —
    that document fails closed to REJECTED and the bundle still returns an audited verdict."""
    docs = [("d1", _doc("s1", "PAN ABCDE1234F")), ("d2", _doc("s2", "PAN ABCDE1234F"))]
    led = AuditLedger()
    b = verify_bundle(docs, _BrokenRegistry(), led, TS, bundle_session_id="bz")  # type: ignore[arg-type]
    assert b.document_count == 2
    assert all(d.trust.verdict == Verdict.REJECTED and d.trust.fail_closed for d in b.documents)
    assert b.fail_closed is True
    ok, broken = led.verify_chain()
    assert ok and broken is None  # the bundle decision was still audited, not lost to a crash


def test_bundle_uncomparable_documents_are_not_evaluated_not_a_fake_pass():
    # Different fields in each doc -> cross-check cannot run -> NOT_EVALUATED, and the bundle does not
    # fabricate trust (it stays at the docs' own REVIEW, never APPROVED).
    docs = [
        ("doc1", _doc("s1", "PAN ABCDE1234F")),
        ("doc2", _doc("s2", "IFSC: SBIN0001234")),
    ]
    b = verify_bundle(docs, _registry(), AuditLedger(), TS, bundle_session_id="b6")
    assert b.cross_document.status == SignalStatus.NOT_EVALUATED
    assert b.bundle_verdict != Verdict.APPROVED
