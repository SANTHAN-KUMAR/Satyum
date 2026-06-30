import pytest
from decimal import Decimal
from forensics.extraction.cross_read import numbers_in_region, CrossReadEnsemble, default_ensemble

def test_textlayer_exact_match():
    # Simulate a word precisely matching the VLM box
    words = [((0.5, 0.5, 0.1, 0.05), "52,562.16")]
    norm_bbox = (0.5, 0.5, 0.1, 0.05)
    nums = numbers_in_region(words, norm_bbox)
    assert nums == [Decimal("52562.16")]

def test_textlayer_drift_tolerant():
    # Simulate a drifted VLM box that still captures the word's centre within the pad
    words = [((0.5, 0.5, 0.1, 0.05), "52,562.16")]
    # VLM box is shifted left and up
    norm_bbox = (0.45, 0.45, 0.05, 0.05)
    nums = numbers_in_region(words, norm_bbox, pad=0.08)
    assert nums == [Decimal("52562.16")]

def test_ensemble_verify_with_textlayer():
    ensemble = CrossReadEnsemble(default_ensemble()._readers) 
    words = [((0.5, 0.5, 0.1, 0.05), "52,562.16")]
    norm_bbox = (0.5, 0.5, 0.1, 0.05)
    
    # Matching
    out = ensemble.verify(None, norm_bbox, Decimal("52562.16"), 0.01, text_words=words)
    assert out.agree is True
    assert "PDF text layer confirms" in out.detail
    
    # Contradicting
    out2 = ensemble.verify(None, norm_bbox, Decimal("50000.00"), 0.01, text_words=words)
    assert out2.agree is False
    assert "PDF text layer shows a different figure" in out2.detail
