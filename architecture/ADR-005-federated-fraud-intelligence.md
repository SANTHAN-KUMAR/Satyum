# ADR-005 — Federated Fraud Intelligence (consortium roadmap)

> **Status:** Proposed · 2026-06-29 · **roadmap, NOT implemented.** This is a design commitment and a
> pitch artifact, not a claim of working code. No federated training runs in the POC; this records
> *where* it plugs in, *why* it is safe, and *what* a real build would require — so "ready to implement"
> is an honest statement about existing seams, not vaporware ([CLAUDE.md §2/§3.4](../CLAUDE.md)).
> **Builds on:** [ADR-004](ADR-004-v2-progressive-evidence-architecture.md) (the determinism boundary it
> must never cross) and ADR-004 §Layer-5 (`AnomalyDetector` interface) / §Layer-6 (pHash fraud memory).

---

## 1. Context — why a consortium, and why centralized training fails

Fraud is a moving target and no single bank sees all of it: a forged salary slip or a GenAI-fabricated
statement that hits Canara this week hits HDFC next week. The obvious answer — pool everyone's data to
train one model — is a non-starter:

- **DPDP / privacy:** customer financial data cannot leave the bank's perimeter to a shared server.
- **Competitive trust:** banks will not hand confidential customer records to a vendor or a rival.

So the value (industry-wide fraud intelligence) and the constraint (data never moves) appear to
conflict. **Federated Learning (FL) resolves it: send the model to the data, never the data to the
model.** Each bank trains locally on its own private data; only model *updates* (weights/gradients) —
never records — return to a coordinator, which averages them into a stronger shared model and
redistributes it. The network gets smarter; no customer row ever leaves a bank.

This is the natural extension of Satyum's existing sovereignty spine: ADR-004 already self-hosts the VLM
in-perimeter (Qwen2.5-VL via vLLM) so *reading* a document never sends pixels out. FL makes the same
promise for *learning*.

---

## 2. The decision — FL is scoped to the SOFT layers, never the decision path

This is the load-bearing constraint and the reason FL does not contradict Satyum's thesis.

> **Satyum's verdict is deterministic: cryptographic rules + claim-graph logic, no black-box model in
> the decision path ([ADR-004 §2](ADR-004-v2-progressive-evidence-architecture.md)).** FL trains shared
> *models*. Therefore FL may only touch the two places where a learned model already lives — both of
> which are **soft, separable, and structurally incapable of moving a verdict to APPROVE or REJECT.**

**Home 1 — the anomaly ML lane (Layer 5).** ADR-004 §Layer-5 specifies a flag-gated, **REVIEW-only**
learned anomaly detector behind the `AnomalyDetector` interface: additive, never approves/rejects,
explicitly excluded from the determinism guarantee. A `FederatedAnomalyDetector` is one more
implementation of that interface — the seam already exists.

**Home 2 — federated fraud-ring memory (Layer 6).** The resubmission store already fingerprints
known-forged documents with perceptual hashes (pHash). A forged document reused *across institutions* is
a real cross-bank attack. Banks share the **hashes, not the documents** — a pHash is a one-way
perceptual fingerprint that carries no PII. This is "federated fraud intelligence" without gradient
training, and it is the most concrete, nearest-term form of the idea: the local pHash store is one node
of a consortium hash network; the sharing/sync protocol is the roadmap.

**Explicitly out of scope:** the deterministic rule packs, provenance/PKI, and the decision brain. FL
never makes the *verdict* "smarter" — it makes the *soft signals* and the *fraud memory* smarter.

---

## 3. Why this is safe — the bounded blast radius (the cyber-grade argument)

Because FL is confined to REVIEW-only signals, **its worst-case failure is bounded by the
architecture**, not by trust in the federation:

| Threat | Effect in Satyum |
|---|---|
| A compromised/malicious bank poisons the shared model | At worst, a case is mis-routed to **human REVIEW**. It can **never** auto-approve a fraud or auto-reject a genuine applicant — those require deterministic Layer-1/4/6 evidence the model cannot fabricate. |
| The federated model is simply wrong (drift, non-IID) | A spurious REVIEW (cost: an analyst's time), never a wrongful financial decision. |
| The model is removed entirely | The APPROVE/REJECT verdict is **identical**; only REVIEW routing changes (ADR-004 §Layer-5 honest bound). |

Most FL pitches cannot make this claim. Satyum can, *structurally* — turning the "no ML in the decision
path" constraint into the property that makes FL safe to adopt in a regulated lender.

---

## 4. Security & privacy engineering (what a real build commits to)

FL is not "averaging weights" — in a *cyber* context the threat model is the point:

- **Secure aggregation:** the coordinator combines updates it cannot individually invert (so it never
  reconstructs one bank's gradient). Standard: pairwise-masked aggregation / MPC.
- **Model-poisoning defense:** robust aggregation (Krum / trimmed-mean / median) + anomaly screening on
  submitted updates, so one bad participant cannot steer the global model. *This is itself a security
  feature, on-theme.*
- **Differential privacy:** calibrated noise on shared updates bounds what any update leaks about a
  record.
- **Non-IID reality:** banks' distributions differ (regional, product mix); the aggregation and
  personalization strategy must account for it (e.g. FedProx / per-bank fine-tuning heads).
- **Auditability preserved:** every global-model version is pinned and logged in the hash-chained audit
  (ADR-004 §5.6) exactly as the VLM model id is — so "which model version produced this REVIEW routing"
  is reconstructable.

---

## 5. Existing seams — why "ready to implement" is honest

This is a roadmap, but it is not a blank slate. The architecture already accommodates it:

- **`AnomalyDetector` interface** (ADR-004 §Layer-5, `SATYUM_ANOMALY_ML_ENABLED`) — the literal plug
  point; a federated trainer is a drop-in implementation.
- **pHash resubmission store + hash-chained audit ledger** ([`forensics/phash.py`](../backend/forensics/phash.py),
  [`risk/audit.py`](../backend/risk/audit.py)) — the substrate for a federated fraud-hash network.
- **Self-hosted VLM / DPDP sovereignty** (ADR-004 §Layer-2) — the in-perimeter deployment FL assumes.

A POC of the federated anomaly lane would need: a coordinator service, a per-bank local trainer behind
`AnomalyDetector`, secure aggregation, and a robust-aggregation rule — none of which require changing
the decision path.

---

## 6. Honest status & relationship to ADR-004

- **Status:** roadmap. Nothing here runs in the POC. Pitch it as a **consortium / network-effects
  scalability story**, scoped to Layers 5 and 6, with the bounded-blast-radius framing (§3).
- **Does not amend ADR-004's determinism boundary** — it is defined *by* it. If a future proposal tried
  to put a federated model in the decision path, that would require superseding ADR-004 §2, and this ADR
  explicitly does not.
- **Integrity note ([CLAUDE.md §3](../CLAUDE.md)):** until built, FL must be presented as a future
  capability with named seams, never demoed as working or implied to influence a live verdict.
