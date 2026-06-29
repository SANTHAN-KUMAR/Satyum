# `backend/ontology/` — Domain rulebooks (data, not code)

The machine-readable ontologies the deterministic Layer-4/5/6 engine loads and computes from
([ADR-004](../../architecture/ADR-004-v2-progressive-evidence-architecture.md) — *the model reads; deterministic
rules decide*). Rules are **data**; the engine is a small interpreter of a **finite catalog of check kinds**.
There is no arbitrary expression evaluation — every primitive is auditable and named.

## Files
| File | Role |
|---|---|
| [`_shared.json`](_shared.json) | value-type system, unit conversions, severity bands, the **`check_kinds` catalog**, the field-ref grammar. Loaded once, merged into every domain. |
| [`financial.json`](financial.json) | bank statements, salary slips, Form-16/ITR. **Production depth** (rules F1–F4 = the built [arithmetic engine](../forensics/arithmetic.py)). |
| [`land_title.json`](land_title.json) | sale deeds, RoR, EC, mutations. Real-but-scoped (L1–L7). |
| [`legal_contract.json`](legal_contract.json) | loan/sale/lease agreements (G1–G7). |

## Anatomy of a domain file
`document_types` · `enums` · `entities` (typed fields the claim graph populates) · **`rules`** (Layer-4 axioms)
· `anomalies` (Layer-5, REVIEW-only) · `corroboration` (Layer-6 bridges) · `coverage_notes` (honest gates).

## Anatomy of a rule
```jsonc
{
  "id": "F1", "name": "running_balance_chain", "title": "...", "rationale": "...",
  "applies_when": { "document_types": [...], "requires": [...], "min": {...} },  // else NOT_APPLICABLE / NOT_EVALUATED
  "check": "linear_balance",                       // a kind from _shared.check_kinds
  "bind": { ...field refs bound to the check's params... },
  "on_fail":         { "status": "FAIL", "severity_ref": "hard_tamper", "localize": {...}, "reason": "...{index}..." },
  "on_insufficient": { "status": "NOT_EVALUATED", "reason": "..." }   // the honest pending branch — every rule has one
}
```

## Field references (`bind`)
A ref resolves against the claim graph (grammar in `_shared.field_ref_grammar`):
- single — `{ "entity": "Account", "field": "opening_balance" }`
- filtered — `{ "entity": "SummaryRow", "field": "amount", "where": { "kind": "total_debits" } }`
- series — `{ "entity": "Transaction", "field": "credit", "series": true }` (the ordered list of that field)
- reduce — add `"reduce": "sum" | "last_present"` to collapse a series
- constant — `{ "const": 0 }`

## How the engine consumes a rulebook (Layer 4)
1. **Load** `_shared.json` + the domain file; resolve `extends`.
2. For the document/bundle, **validate claims** against `entities`/`value_types` (regex, checksum, calendar). A claim with `cross_read_agree=false` or below the confidence gate is treated as **absent** (ADR-004 §5).
3. For each `rule`: evaluate `applies_when` → if the doc type doesn't match, `NOT_APPLICABLE`; if required claims are missing, `on_insufficient` (`NOT_EVALUATED`).
4. Otherwise **dispatch on `check`** to the deterministic function for that kind, binding `bind` refs. Numerics use `arithmetic_abs_tolerance` (from [`config.py`](../app/config.py)).
5. Emit the `result_contract` record → the orchestrator wraps it as a `LayerSignal` with `suspicion` from `severity_ref`, the localized `evidence` (bbox), and the templated `reason`. The **`rule_pack_version` is written to the audit ledger.**

`severity_ref` values resolve against `_shared.severity_bands` (all `# DEFAULT — needs calibration`). `anomalies` are
**REVIEW-only** (never APPROVE/REJECT on their own). `corroboration` bridges run in Layer 6 over the whole bundle.

## Integrity invariants (enforced; CLAUDE.md §3)
- Every rule has a `NOT_EVALUATED` branch — **missing data never becomes a pass**.
- Every numeric value type is `cross_read_critical` — re-read by a deterministic OCR before any rule trusts it.
- Anomalies are REVIEW-only; gated rules (state stamp tables, tax slabs, EMI inputs) return `NOT_EVALUATED` until their data is configured.
- A CI test loads these files and asserts coherence (see the validator: every `check` ∈ catalog, every `severity_ref` resolves, every field `type` is known, every rule has the pending branch).

## Extension protocol (ties to the rule-learning loop, ADR-004)
Add a predicate/axiom by: (1) declare the entity/field or rule here; (2) extend the VLM extraction schema (Layer 2) + the `Claim` contract; (3) implement the deterministic rule (a new `check_kind` only if no existing primitive fits) with a genuine-vs-adversarial fixture ([TESTING-STRATEGY](../../architecture/TESTING-STRATEGY.md)); (4) **bump the rule-pack version** (recorded in the audit). These JSON files are the single source of truth all four steps refer to.
