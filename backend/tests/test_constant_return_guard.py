"""The constant-return guard (CLAUDE.md §3.2 / TESTING-STRATEGY §2).

A detector is only "real" if its output *moves* between genuine and adversarial input. This meta-test
encodes that: ``discriminates()`` is what every analyzer's discrimination test must satisfy, and we
prove here that a constant-returning fake FAILS it — so a shallow-proxy implementation can never pass
CI. As more analyzers are built, each is added to ``REAL_CASES``.
"""

from __future__ import annotations

from app.contracts import AnalysisContext, LayerSignal, Mode, SignalStatus
from forensics.arithmetic import ArithmeticConsistencyAnalyzer
from tests.builders import genuine_statement, tampered_balance_statement


def discriminates(analyzer, genuine_ctx: AnalysisContext, adversarial_ctx: AnalysisContext) -> bool:
    """True iff the analyzer's suspicion differs between a genuine and an adversarial input."""
    g = analyzer.analyze(genuine_ctx)
    a = analyzer.analyze(adversarial_ctx)
    if g.status != SignalStatus.VALID or a.status != SignalStatus.VALID:
        return False
    return g.suspicion != a.suspicion


def _file_ctx(stmt):
    ctx = AnalysisContext(session_id="t", intake_mode=Mode.FILE)
    ctx.shared["statement"] = stmt
    return ctx


# (analyzer, genuine_ctx_factory, adversarial_ctx_factory)
REAL_CASES = [
    (
        ArithmeticConsistencyAnalyzer(),
        lambda: _file_ctx(genuine_statement()),
        lambda: _file_ctx(tampered_balance_statement()),
    ),
]


def test_real_analyzers_discriminate():
    for analyzer, genuine, adversarial in REAL_CASES:
        assert discriminates(analyzer, genuine(), adversarial()), (
            f"{analyzer.name} does not discriminate genuine vs adversarial — it is a shallow proxy"
        )


class _ConstantFake:
    """A plausible-looking fake: always returns the same suspicion regardless of input."""

    name = "constant_fake"
    layer = 3
    mode = Mode.ANY

    def applicable(self, ctx):  # noqa: ANN001
        return True

    def analyze(self, ctx):  # noqa: ANN001
        return LayerSignal.valid(self.name, 3, Mode.ANY, 0.9, 0.4, "looks real, proves nothing")


def test_constant_fake_is_caught_by_the_guard():
    fake = _ConstantFake()
    genuine, adversarial = REAL_CASES[0][1], REAL_CASES[0][2]
    # The guard MUST report that the fake does not discriminate — i.e. CI would reject it.
    assert discriminates(fake, genuine(), adversarial()) is False
