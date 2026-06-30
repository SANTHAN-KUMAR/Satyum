"""Deterministic tests for the digital-PDF text-layer cross-read + multi-page merge (ADR-004 §5.2/§3).

These exercise the controls that make the VLM safe on a digital-native PDF WITHOUT any model call: the
exact embedded text layer is the independent decode. Every test would FAIL against a constant return
(CLAUDE.md §3.2):
  * a faithfully-read figure that IS printed at the cell → trusted;
  * a *different* figure printed at the cell (the model laundered/misread it) → held pending;
  * a figure printed NOWHERE (the model invented it to reconcile) → held pending;
  * a reader that emits no box (e.g. Groq) still gets a page-level presence check;
  * a multi-page statement's running-balance chain is continuous across the page break.
"""

from __future__ import annotations

from decimal import Decimal

from app.config import settings
from forensics.extraction.builder import ClaimGraphBuilder
from forensics.extraction.cross_read import CrossReadEnsemble, default_ensemble, numbers_in_region
from forensics.extraction.interface import (
    ExtractedField,
    ExtractedTransaction,
    ExtractedValue,
    PageImage,
    RawExtraction,
)
from rules import engine

# A tiny synthetic digital page: three printed numbers at known normalized boxes (x, y, w, h).
# Column geometry mimics a statement: debit ~x0.70, credit ~x0.80, balance ~x0.90; one row band.
TEXT_WORDS = (
    ((0.70, 0.50, 0.05, 0.02), "295.00"),
    ((0.80, 0.50, 0.06, 0.02), "5,80,000.00"),
    ((0.90, 0.50, 0.06, 0.02), "584,115.00"),
    ((0.40, 0.10, 0.05, 0.02), "0.00"),  # opening, header band
)


def _page(text_words=TEXT_WORDS) -> PageImage:
    # 1x1 PNG header is enough; the text-layer path never decodes pixels.
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
    )
    return PageImage(png_bytes=png, width=1000, height=1000, text_layer="x", text_words=text_words)


def _ensemble() -> CrossReadEnsemble:
    return default_ensemble()


# --- numbers_in_region: the geometry primitive --------------------------------------------------

def test_region_match_localizes_to_the_cell():
    # A box over the balance column returns the balance, not the debit/credit in other columns.
    nums = numbers_in_region(TEXT_WORDS, (0.90, 0.50, 0.06, 0.02))
    assert Decimal("584115.00") in nums
    assert Decimal("295.00") not in nums


def test_no_box_returns_all_page_numbers():
    nums = numbers_in_region(TEXT_WORDS, None)
    assert Decimal("295.00") in nums and Decimal("580000.00") in nums and Decimal("584115.00") in nums


# --- the cross-read verdicts --------------------------------------------------------------------

def test_textlayer_confirms_value_at_its_cell():
    out = _ensemble().verify(None, (0.90, 0.50, 0.06, 0.02), Decimal("584115.00"), 1.0, text_words=TEXT_WORDS)
    assert out.agree is True


def test_textlayer_catches_laundered_figure_at_the_cell():
    # The cell prints 584115; the model claims a reconciling 884115 → independent decode disagrees.
    out = _ensemble().verify(None, (0.90, 0.50, 0.06, 0.02), Decimal("884115.00"), 1.0, text_words=TEXT_WORDS)
    assert out.agree is False


def test_ungrounded_claim_is_never_trusted():
    # The charter requires box-grounding: a claim with no box cannot be trusted even if its value is
    # printed on the page (a reader that does not ground a figure never earns trust for it).
    out = _ensemble().verify(None, None, Decimal("295.00"), 1.0, text_words=TEXT_WORDS)
    assert out.agree is False


def test_imprecise_box_recovers_via_page_level_presence():
    # Box was PROVIDED but landed on an empty region (VLM box off); the value is printed elsewhere →
    # recovered via page-level presence (the reader did attempt grounding). Not a wholly ungrounded claim.
    out = _ensemble().verify(None, (0.05, 0.95, 0.02, 0.02), Decimal("295.00"), 1.0, text_words=TEXT_WORDS)
    assert out.agree is True


def test_imprecise_box_recovery_rejects_value_printed_nowhere():
    # Box provided but empty region, AND the value is printed nowhere (invented to reconcile) → held.
    out = _ensemble().verify(None, (0.05, 0.95, 0.02, 0.02), Decimal("999999.00"), 1.0, text_words=TEXT_WORDS)
    assert out.agree is False


# --- builder integration: faithful figures become trusted, arithmetic runs ----------------------

def _cell(v, bbox=None):
    return ExtractedValue(value=v, bbox=bbox, confidence=0.95)


def test_faithful_digital_extraction_is_trusted_and_arithmetic_runs():
    # opening 0; +5000 →5000; −295 →4705. All printed → trusted → F1 evaluates and PASSES.
    words = (
        ((0.40, 0.10, 0.05, 0.02), "0.00"),
        ((0.80, 0.50, 0.05, 0.02), "5,000.00"),
        ((0.90, 0.50, 0.05, 0.02), "5,000.00"),
        ((0.70, 0.55, 0.05, 0.02), "295.00"),
        ((0.90, 0.55, 0.05, 0.02), "4,705.00"),
    )
    page = _page(words)
    # Each figure is grounded to the box of its printed word (a capable VLM grounds every value).
    raw = RawExtraction(
        doc_type="BANK_STATEMENT",
        fields=[ExtractedField(predicate="opening_balance", value="0.00", confidence=0.95,
                               bbox=(0.40, 0.10, 0.05, 0.02))],
        transactions=[
            ExtractedTransaction(seq=0, credit=_cell("5000.00", (0.80, 0.50, 0.05, 0.02)),
                                 running_balance=_cell("5000.00", (0.90, 0.50, 0.05, 0.02))),
            ExtractedTransaction(seq=1, debit=_cell("295.00", (0.70, 0.55, 0.05, 0.02)),
                                 running_balance=_cell("4705.00", (0.90, 0.55, 0.05, 0.02))),
        ],
        model_id="probe", prompt_hash="p",
    )
    builder = ClaimGraphBuilder(_ensemble(), arithmetic_abs_tolerance=settings.arithmetic_abs_tolerance)
    graph = builder.build(raw, page, doc_id="d", source="probe")
    numeric = graph.numeric_claims()
    assert numeric and all(c.provenance.cross_read_agree for c in numeric)
    domain, results = engine.run(graph, min_confidence=0.5, tolerance=1.0)
    f1 = next(r for r in results if r.rule_id == "F1")
    assert f1.status.value == "PASS"


def test_tampered_running_balance_breaks_f1_on_digital_extraction():
    # Two rows (F1 needs >=2 printed balances). The forger inflated row-1's debit on the page but left
    # its printed balance unchanged, so the chain no longer carries forward. Every figure is genuinely
    # printed on the tampered page → trusted → F1 can judge them and FAILS at the broken row.
    words = (
        ((0.40, 0.10, 0.05, 0.02), "0.00"),
        ((0.90, 0.50, 0.05, 0.02), "5,000.00"),
        ((0.80, 0.50, 0.05, 0.02), "5,000.00"),
        ((0.70, 0.55, 0.05, 0.02), "1,000.00"),
        ((0.90, 0.55, 0.05, 0.02), "9,000.00"),
    )
    page = _page(words)
    raw = RawExtraction(
        doc_type="BANK_STATEMENT",
        fields=[ExtractedField(predicate="opening_balance", value="0.00", confidence=0.95,
                               bbox=(0.40, 0.10, 0.05, 0.02))],
        transactions=[
            ExtractedTransaction(seq=0, credit=_cell("5000.00", (0.80, 0.50, 0.05, 0.02)),
                                 running_balance=_cell("5000.00", (0.90, 0.50, 0.05, 0.02))),
            ExtractedTransaction(seq=1, debit=_cell("1000.00", (0.70, 0.55, 0.05, 0.02)),
                                 running_balance=_cell("9000.00", (0.90, 0.55, 0.05, 0.02))),
        ],
        model_id="probe", prompt_hash="p",
    )
    builder = ClaimGraphBuilder(_ensemble(), arithmetic_abs_tolerance=settings.arithmetic_abs_tolerance)
    graph = builder.build(raw, page, doc_id="d", source="probe")
    # every figure is genuinely printed on the (tampered) page → trusted → F1 can judge them
    assert all(c.provenance.cross_read_agree for c in graph.numeric_claims())
    domain, results = engine.run(graph, min_confidence=0.5, tolerance=1.0)
    f1 = next(r for r in results if r.rule_id == "F1")
    assert f1.status.value == "FAIL"  # row1: 5000 - 1000 = 4000 != printed 9000


# --- multi-page merge: continuous chain across the page break -----------------------------------

def test_build_multi_renumbers_transactions_and_chains_across_pages():
    p1_words = (((0.40, 0.10, 0.05, 0.02), "0.00"),
                ((0.90, 0.50, 0.05, 0.02), "5,000.00"),
                ((0.80, 0.50, 0.05, 0.02), "5,000.00"))
    p2_words = (((0.70, 0.50, 0.05, 0.02), "1,000.00"),
                ((0.90, 0.50, 0.05, 0.02), "4,000.00"))
    raw1 = RawExtraction(
        doc_type="BANK_STATEMENT",
        fields=[ExtractedField(predicate="opening_balance", value="0.00", confidence=0.95,
                               bbox=(0.40, 0.10, 0.05, 0.02))],
        transactions=[ExtractedTransaction(seq=0, credit=_cell("5000.00", (0.80, 0.50, 0.05, 0.02)),
                                            running_balance=_cell("5000.00", (0.90, 0.50, 0.05, 0.02)))],
        model_id="m", prompt_hash="p",
    )
    raw2 = RawExtraction(
        doc_type="BANK_STATEMENT",
        transactions=[ExtractedTransaction(seq=0, debit=_cell("1000.00", (0.70, 0.50, 0.05, 0.02)),
                                            running_balance=_cell("4000.00", (0.90, 0.50, 0.05, 0.02)))],
        model_id="m", prompt_hash="p",
    )
    builder = ClaimGraphBuilder(_ensemble(), arithmetic_abs_tolerance=settings.arithmetic_abs_tolerance)
    graph = builder.build_multi([(raw1, _page(p1_words)), (raw2, _page(p2_words))], doc_id="d", source="m")
    # page-2's transaction must be renumbered to seq 1 (continues the chain), not collide at seq 0
    seqs = sorted({c.index for c in graph.claims
                   if c.subject.startswith("transaction_") and c.index is not None})
    assert seqs == [0, 1]
    domain, results = engine.run(graph, min_confidence=0.5, tolerance=1.0)
    f1 = next(r for r in results if r.rule_id == "F1")
    assert f1.status.value == "PASS"  # 0 +5000 →5000; 5000 −1000 →4000 across the page break


def test_build_multi_dedupes_repeated_header_field():
    words = (((0.40, 0.10, 0.05, 0.02), "0.00"),)
    raw1 = RawExtraction(doc_type="BANK_STATEMENT",
                         fields=[ExtractedField(predicate="opening_balance", value="0.00",
                                                confidence=0.95, bbox=None)],
                         model_id="m", prompt_hash="p")
    raw2 = RawExtraction(doc_type="BANK_STATEMENT",
                         fields=[ExtractedField(predicate="opening_balance", value="9999.00",
                                                confidence=0.95, bbox=None)],
                         model_id="m", prompt_hash="p")
    builder = ClaimGraphBuilder(_ensemble(), arithmetic_abs_tolerance=settings.arithmetic_abs_tolerance)
    graph = builder.build_multi([(raw1, _page(words)), (raw2, _page(words))], doc_id="d", source="m")
    openings = [c for c in graph.claims if c.predicate == "opening_balance"]
    assert len(openings) == 1 and openings[0].value == "0.00"  # first occurrence kept
