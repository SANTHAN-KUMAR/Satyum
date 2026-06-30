import sys, os
from decimal import Decimal
sys.path.insert(0, os.path.abspath('.'))
from app.contracts import AnalysisContext, Mode
from app.registry_assembly import build_registry
from app.orchestrator import orchestrator
registry = build_registry()
with open('../samples/real_corpus/canara_direct/tamper_closing_balance.pdf','rb') as f: raw=f.read()
ctx = AnalysisContext(session_id='p', intake_mode=Mode.FILE, doc_type=None, file_bytes=raw, file_name='t.pdf', file_mime='application/pdf', source_was_pullable=False)

from forensics.extraction.interface import VLMExtractor, RawExtraction, ExtractedField, ExtractedTransaction, ExtractedValue
class MockExtractor(VLMExtractor):
    name = "mock-extractor"
    available = True
    def handles_script(self, f): return True
    def extract(self, page, *, doc_type_hint=None):
        return RawExtraction(
            doc_type="BANK_STATEMENT",
            fields=[
                ExtractedField(predicate="opening_balance", value="0.00", confidence=1.0, bbox=(0.697, 0.503, 0.021, 0.013)),
                ExtractedField(predicate="closing_balance", value="52562.16", confidence=1.0, bbox=(0.526, 0.503, 0.041, 0.011)),
            ],
            transactions=[]
        )

registry.extractors = [MockExtractor()]

res = orchestrator.process(ctx, registry)

print(f"VERDICT: {res.verdict.name}")
print(f"SCORE: {res.score}")
print("FINANCIAL RULES FIRED:")
for item in res.evidence:
    if getattr(item, "domain", None) == "financial":
        print(f"  {item.rule_id} -> {'PASSED' if item.passed else 'FAILED'}")

