"""Layer 6 — cross-source corroboration over the claim graph (ADR-004 §6, financial.json X_INCOME).

The cross-document IDENTITY graph (``forensics/cross_document.py``) asks "is it the same person across
the bundle?". This module asks the complementary, figure-level question the identity graph cannot:
**do the *numbers* agree across independent sources?** A forger can fabricate one salary slip showing
₹1.2L net, but making the bank statement's salary credits, the slip's net pay, and the Form-16/ITR
income all tell the *same* income story is much harder — and a disagreement is strong, explainable
fraud evidence ("the slip claims ₹1.2L net but the account only ever receives ₹40k").

It operates on the canonical claim graph (ADR-004 Layer 3), so it is template-independent and consumes
**only trusted claims** (``Claim.is_trusted`` — cross-read-verified, above the confidence gate); a
laundered or low-confidence figure is simply absent, never silently corroborated (the §5.2→§6 handoff,
mirroring the Layer-4 rule packs).

What it checks (real relationships, not naive equality — CLAUDE.md §3.1/§5):
  * **monthly take-home agreement** — bank salary credit ≈ salary-slip net pay. These are the *same*
    quantity (post-deduction monthly pay), so they must match within a relative tolerance.
  * **annual income floor** — annualised take-home must not *exceed* annual gross income (you cannot
    take home more than you gross). A hard logical floor, not a soft heuristic; gross legitimately
    exceeding net is normal (tax/PF) and is NOT flagged.
  * **employer agreement** — salary-slip employer ≈ Form-16/ITR employer (fuzzy OrgName).

Honest bounds: gross-vs-net is directional (only the floor is a contradiction), and acronym/expansion
employer pairs ("TCS" vs "Tata Consultancy") fall below the fuzzy ratio — a known limit, surfaced as a
soft REVIEW, never an auto-reject. Income corroboration is capped at the REVIEW band: a single
cross-source disagreement routes a human, it never single-handedly rejects a genuine applicant.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from statistics import median

from app.claims import Claim, ClaimGraph
from app.config import settings
from app.contracts import EvidenceRegion, LayerSignal, Mode
from forensics.cross_document import _edit_distance
from ontology.loader import severity_value

# Document-type families (mirror rules/financial.py so the two stay in lockstep).
BANK_STATEMENT_TYPES = frozenset({"BANK_STATEMENT"})
SALARY_TYPES = frozenset({"SALARY_SLIP"})
INCOME_TYPES = frozenset({"FORM16", "ITR"})

# A transaction is a salary credit if its narration carries one of these tokens (word-boundary matched
# so "sal" in "NEFT/SAL/..." hits but "wholesale" does not). DEFAULT — extend from a real narration
# corpus; deliberately conservative (a missed salary credit yields NOT_EVALUATED, never a false pass).
_SALARY_TOKENS = ("salary", "sal", "payroll", "wages", "stipend", "remuneration", "emolument")
_SALARY_RE = re.compile(r"\b(" + "|".join(_SALARY_TOKENS) + r")\b", re.IGNORECASE)

# Legal-suffix noise stripped before an OrgName comparison.
_ORG_SUFFIXES = re.compile(
    r"\b(pvt|private|ltd|limited|llp|inc|co|company|corp|corporation|"
    r"industries|enterprises|technologies|services|solutions|systems)\b",
    re.IGNORECASE,
)

# Residual suspicion when every present cross-source relationship AGREES — corroboration is positive
# evidence but not proof (a coherent forgery can still corroborate). Mirrors cross_document.
_AGREEMENT_SUSPICION = 0.05
# REVIEW-band ceiling: income corroboration is a soft, figure-level signal — a disagreement routes to
# REVIEW (a human reconciles the sources), never an auto-reject on its own (fail-safe, ADR-004 §6).
_REVIEW_CAP = round(1.0 - settings.review_at / 100.0, 2)

MONTHLY_TAKE_HOME = "monthly_take_home"
ANNUAL_GROSS = "annual_gross"


@dataclass(frozen=True)
class IncomeObservation:
    """One income figure read from one document, normalised to a comparable kind."""

    doc_label: str
    doc_type: str
    kind: str  # MONTHLY_TAKE_HOME | ANNUAL_GROSS
    amount: Decimal
    source_field: str  # "salary_credit" | "net_pay" | "gross_income"
    claim: Claim | None = None  # representative claim, for bbox localization


@dataclass(frozen=True)
class CorroborationCheck:
    """The outcome of one cross-source relationship check (agree or a localised disagreement)."""

    name: str
    agree: bool
    severity: float  # effective suspicion contribution (0.0 when agree)
    detail: str
    left: IncomeObservation | None = None
    right: IncomeObservation | None = None


@dataclass
class CorroborationResult:
    observations: list[IncomeObservation] = field(default_factory=list)
    checks: list[CorroborationCheck] = field(default_factory=list)
    employer_checked: bool = False

    @property
    def disagreements(self) -> list[CorroborationCheck]:
        return [c for c in self.checks if not c.agree]

    @property
    def comparisons_made(self) -> int:
        return len(self.checks)


# --- claim-graph accessors (trust-gated) ----------------------------------------------------------


def _gate() -> float:
    return settings.vlm_min_confidence


def _trusted_decimal(claim: Claim | None) -> Decimal | None:
    if claim is None or not claim.is_trusted(_gate()):
        return None
    return claim.as_decimal()


def _scalar(graph: ClaimGraph, predicate: str) -> tuple[Decimal | None, Claim | None]:
    claim = graph.first(predicate)
    return _trusted_decimal(claim), claim


def _trusted_text(claim: Claim | None) -> str | None:
    if claim is None or not claim.is_trusted(_gate()):
        return None
    return claim.value or None


def _salary_credits(graph: ClaimGraph) -> list[tuple[Decimal, Claim]]:
    """Trusted credit amounts whose row narration looks like a salary payment, in document order."""
    rows: dict[int, dict[str, Claim]] = {}
    for c in graph.claims:
        if c.subject.startswith("transaction_") and c.index is not None:
            rows.setdefault(c.index, {})[c.predicate] = c
    out: list[tuple[Decimal, Claim]] = []
    for _seq, cells in sorted(rows.items()):
        credit = cells.get("credit")
        desc = _trusted_text(cells.get("description")) or ""
        amount = _trusted_decimal(credit)
        if amount is not None and amount > 0 and _SALARY_RE.search(desc):
            out.append((amount, credit))  # type: ignore[arg-type]
    return out


# --- income observation extraction ----------------------------------------------------------------


def extract_income_observations(graphs_by_doc: dict[str, ClaimGraph]) -> list[IncomeObservation]:
    """Read every comparable income figure across the bundle's claim graphs (trusted claims only)."""
    obs: list[IncomeObservation] = []
    for label, graph in graphs_by_doc.items():
        dt = (graph.doc_type or "").upper()
        if dt in BANK_STATEMENT_TYPES:
            credits = _salary_credits(graph)
            if credits:
                # The representative monthly salary is the median credit — robust to a one-off bonus
                # or arrears spike that would skew a mean.
                rep = median(amount for amount, _ in credits)
                rep_claim = min(credits, key=lambda ac: abs(ac[0] - rep))[1]
                obs.append(IncomeObservation(label, dt, MONTHLY_TAKE_HOME, rep, "salary_credit", rep_claim))
        elif dt in SALARY_TYPES:
            net, claim = _scalar(graph, "net_pay")
            if net is not None and net > 0:
                obs.append(IncomeObservation(label, dt, MONTHLY_TAKE_HOME, net, "net_pay", claim))
        elif dt in INCOME_TYPES:
            gross, claim = _scalar(graph, "gross_income")
            if gross is not None and gross > 0:
                obs.append(IncomeObservation(label, dt, ANNUAL_GROSS, gross, "gross_income", claim))
    return obs


# --- OrgName fuzzy match (no rapidfuzz dependency — deterministic Levenshtein ratio) --------------


def _normalise_org(name: str) -> str:
    s = _ORG_SUFFIXES.sub(" ", name.lower())
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _org_ratio(a: str, b: str) -> float:
    """Normalised Levenshtein similarity in [0,1] after stripping legal suffixes/punctuation."""
    na, nb = _normalise_org(a), _normalise_org(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    longest = max(len(na), len(nb))
    return 1.0 - _edit_distance(na, nb) / longest


# --- the corroboration checks ---------------------------------------------------------------------


def _check_monthly_pairs(monthly: list[IncomeObservation]) -> list[CorroborationCheck]:
    """Every pair of monthly take-home figures must match within the relative tolerance."""
    checks: list[CorroborationCheck] = []
    tol = settings.income_rel_tolerance
    for i in range(len(monthly)):
        for j in range(i + 1, len(monthly)):
            a, b = monthly[i], monthly[j]
            hi = max(a.amount, b.amount)
            rel = float(abs(a.amount - b.amount) / hi) if hi > 0 else 0.0
            agree = rel <= tol
            detail = (
                f"{a.source_field} {a.amount} ({a.doc_label}) vs {b.source_field} {b.amount} "
                f"({b.doc_label}): {rel:.0%} apart"
            )
            checks.append(
                CorroborationCheck(
                    "monthly_take_home_agreement", agree,
                    0.0 if agree else min(severity_value("soft"), _REVIEW_CAP),
                    detail, a, b,
                )
            )
    return checks


def _check_annual_floor(
    monthly: list[IncomeObservation], annual: list[IncomeObservation]
) -> list[CorroborationCheck]:
    """Annualised take-home must not exceed annual gross (a hard logical floor: net <= gross)."""
    checks: list[CorroborationCheck] = []
    slack = Decimal(str(1.0 + settings.income_annual_slack))
    for m in monthly:
        annualised = m.amount * 12
        for g in annual:
            agree = annualised <= g.amount * slack
            detail = (
                f"annualised take-home {annualised} ({m.doc_label}) vs gross income "
                f"{g.amount} ({g.doc_label})"
            )
            checks.append(
                CorroborationCheck(
                    "annual_income_floor", agree,
                    0.0 if agree else min(severity_value("structural"), _REVIEW_CAP),
                    detail if agree else detail + " — take-home exceeds gross (impossible)",
                    m, g,
                )
            )
    return checks


def _check_employer(graphs_by_doc: dict[str, ClaimGraph]) -> tuple[list[CorroborationCheck], bool]:
    """Salary-slip employer ≈ Form-16/ITR employer (fuzzy OrgName). Returns (checks, was_checked)."""
    employers: list[tuple[str, str]] = []  # (doc_label, employer_name)
    for label, graph in graphs_by_doc.items():
        dt = (graph.doc_type or "").upper()
        if dt in SALARY_TYPES or dt in INCOME_TYPES:
            emp = _trusted_text(graph.first("employer"))
            if emp:
                employers.append((label, emp))
    if len(employers) < 2:
        return [], False
    checks: list[CorroborationCheck] = []
    min_ratio = settings.income_employer_min_ratio
    for i in range(len(employers)):
        for j in range(i + 1, len(employers)):
            (la, ea), (lb, eb) = employers[i], employers[j]
            ratio = _org_ratio(ea, eb)
            agree = ratio >= min_ratio
            checks.append(
                CorroborationCheck(
                    "employer_agreement", agree,
                    0.0 if agree else min(severity_value("soft"), _REVIEW_CAP),
                    f"employer {ea!r} ({la}) vs {eb!r} ({lb}): {ratio:.0%} similar",
                )
            )
    return checks, True


def corroborate(graphs_by_doc: dict[str, ClaimGraph]) -> CorroborationResult:
    """Build the cross-source corroboration over a bundle of claim graphs. Pure + deterministic."""
    observations = extract_income_observations(graphs_by_doc)
    monthly = [o for o in observations if o.kind == MONTHLY_TAKE_HOME]
    annual = [o for o in observations if o.kind == ANNUAL_GROSS]

    checks: list[CorroborationCheck] = []
    checks.extend(_check_monthly_pairs(monthly))
    checks.extend(_check_annual_floor(monthly, annual))
    employer_checks, employer_checked = _check_employer(graphs_by_doc)
    checks.extend(employer_checks)

    return CorroborationResult(observations=observations, checks=checks, employer_checked=employer_checked)


def cross_source_signal(graphs_by_doc: dict[str, ClaimGraph]) -> LayerSignal:
    """Produce the bundle-level cross-source corroboration :class:`LayerSignal`.

    NOT_EVALUATED when no cross-source relationship could be formed (fewer than two comparable income
    sources, none of them employer-comparable) — never a fabricated pass. VALID otherwise: near-zero
    suspicion when every relationship agrees (positive corroboration), or a REVIEW-band suspicion driven
    by the worst disagreement (a human reconciles the sources; income never single-handedly rejects).
    """
    name, layer, mode = "cross_source_corroboration", 2, Mode.FILE
    result = corroborate(graphs_by_doc)

    if not result.checks:
        return LayerSignal.not_evaluated(
            name, layer, mode,
            "fewer than two comparable income sources in the bundle — nothing to cross-corroborate",
            income_sources=len(result.observations),
        )

    disagreements = result.disagreements
    measurements = {
        "comparisons": result.comparisons_made,
        "income_sources": len(result.observations),
        "observations": [
            {"doc": o.doc_label, "doc_type": o.doc_type, "kind": o.kind,
             "amount": str(o.amount), "field": o.source_field}
            for o in result.observations
        ],
        "checks": [
            {"name": c.name, "agree": c.agree, "detail": c.detail} for c in result.checks
        ],
        "disagreeing_checks": [c.name for c in disagreements],
        "employer_checked": result.employer_checked,
    }

    if not disagreements:
        return LayerSignal.valid(
            name, layer, mode,
            suspicion=_AGREEMENT_SUSPICION,
            weight=settings.weight_cross_source_income,
            reason=(f"income corroborates across {len(result.observations)} source(s) over "
                    f"{result.comparisons_made} cross-check(s) — sources agree"),
            measurements=measurements,
        )

    worst = max(disagreements, key=lambda c: c.severity)
    regions = [
        EvidenceRegion(bbox=o.claim.provenance.bbox, label=f"{worst.name}: {worst.detail}", source=name)
        for o in (worst.left, worst.right)
        if o is not None and o.claim is not None and o.claim.provenance.bbox is not None
    ]
    return LayerSignal.valid(
        name, layer, mode,
        suspicion=worst.severity,
        weight=settings.weight_cross_source_income,
        reason=(f"cross-source income DISAGREEMENT — {worst.detail}. "
                f"{len(disagreements)} of {result.comparisons_made} cross-check(s) failed; "
                "reconcile the sources before lending"),
        evidence_regions=regions,
        measurements=measurements,
    )
