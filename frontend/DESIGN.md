# Satyum Frontend — Design Audit & UX Redesign

> Scope: **frontend only**. No backend route, contract, or scoring logic changes. Every number/state
> rendered below still comes from real backend output (CLAUDE.md §9) — this document changes
> *organization and presentation*, not data.

---

## 1. What's actually wrong (audited, not assumed)

Before proposing anything, I read the real code. The onboarding flow (`OnboardingFlow.tsx`) and the
design-token system (`tailwind.config.ts`, `index.css`) are **already well-built** — deliberate spacing
scale, a genuine monochrome+gradient-highlight system, real typographic hierarchy. That is *not* where
the "raw, no spacing, AI-slop" feeling comes from. Two real, specific problems are:

### 1.1 The Underwriter Evidence Console is one long vertical dump
`components/evidence/EvidenceConsole.tsx` renders **10 sections stacked in a single column**, all at
once, no grouping, no tabs, no priority: VerdictHero → CopilotPanel → EvidenceSufficiencyBanner →
PipelineWaterfall → ProvenanceCard → ClaimGraphView → RulePackPanel → AnomalyPanel → DocumentPreview +
SignalList → ReasonsCard + PendingList → CaseMeta + PrivacyNote. Nineteen evidence components, no
information architecture above "in order." This is the literal "everything dumped in a single page"
the user is reacting to — it's real, it's not a misperception.

### 1.2 The network/ring graph is real but orphaned
The "graph kinda thing" from the mock demo is `components/network/RingGraph.tsx` — a genuine live SVG
(ring topology, gradient links, shared-identifier hub). It only renders inside `/consortium`, and only
*after* the user manually submits ≥3 simulated applications and clicks "Detect rings." It's not missing;
it's **undiscoverable** and disconnected from the main evidence flow an underwriter actually uses.

### 1.3 Minor token inconsistency
`SampleView.tsx` hardcodes `border-amber-500/60 bg-amber-500/10 text-amber-200` instead of the existing
`verdict.review` / `verdict-review-soft` tokens — a small but real crack in the "every colour comes from
the token system" discipline the rest of the app follows.

### 1.4 What is *not* wrong
Onboarding spacing/typography, the token system, `TrustGauge`, `CrossDocumentGraph` — these are solid.
The redesign below **keeps them**; it does not re-theme the app.

---

## 2. PAN vs Aadhaar — the actual architecture, and the fix

**What the code does today:** PAN is mandatory at onboarding (Step 0, gates advancement); Aadhaar
offline e-KYC is optional, tucked into a collapsed `<details>` panel. They are not alternatives — they
serve different roles:

| | PAN | Aadhaar (offline e-KYC) |
|---|---|---|
| Role | Applicant identity anchor + cross-document corroboration key + income-tax consistency anchor (Form-16/ITR cross-checks) | Supplementary demographic corroboration (name/DOB), UIDAI-signature-verified |
| Verification | Structure regex, optionally live Income-Tax DB lookup | UIDAI digital-signature verification on a **ZIP/XML offline e-KYC package** |
| Format accepted | Typed 10-char string | `.zip` / `.xml` only — **not an image** |

**Why the previous `aadhaar.jpeg` upload "got rejected":** it wasn't a PAN-vs-Aadhaar policy call — the
user uploaded a JPEG into a slot (Step 1's source-document dropzone) that expects either a signed PDF or,
for Aadhaar specifically, a UIDAI-signed offline e-KYC ZIP/XML. A photo of an Aadhaar card is neither. The
system correctly rejected an invalid format, but the UI never told the user *why* — the collapsed
`<details>` panel that actually wants an Aadhaar file is easy to miss entirely, and there's no path for
"I only have a photo of my Aadhaar card."

**Recommendation (fold into the onboarding redesign, §3.2):**
1. **Keep PAN mandatory, keep Aadhaar optional** — the roles are correct and shouldn't change; don't force
   Aadhaar collection we can't act on. This is a scope/engineering call, not a policy one.
2. **Stop hiding Aadhaar in a `<details>` collapse.** Promote it to a visible, equal-weight second card in
   Step 0 titled "Add Aadhaar for stronger corroboration (optional)" — collapsed content nobody reads is
   worse than an honest optional field.
3. **Make the format requirement explicit *before* the user picks a file**, not after a failure: "Upload
   your Aadhaar Paperless Offline e-KYC ZIP (get it free at myaadhaar.uidai.gov.in) — a photo of the card
   itself can't be cryptographically verified and won't be accepted here." This converts a silent-looking
   rejection into an explained constraint.
4. **If a non-ZIP/XML file is dropped on the Aadhaar slot, catch it client-side and say so immediately**
   ("This looks like an image, not an offline e-KYC package — see the instructions above") instead of
   sending it to the backend to fail with a raw `NOT_VERIFIED` / malformed-XML detail string.
5. Do **not** add image-based Aadhaar OCR as a PAN substitute — an Aadhaar photo has no cryptographic
   signature to verify (§3.1 of CLAUDE.md: a signal must actually analyze something), and building one
   now would be exactly the kind of fake-signal shortcut the engineering charter forbids. If Aadhaar-photo
   support is ever wanted, it's a Tier-2 VLM-extraction + rule-pack feature (backend work, out of scope
   here) — not a frontend fix.

---

## 3. Redesign

### 3.1 Underwriter console — from a scroll dump to a working surface

Split `EvidenceConsole` into a **hero + tabs** layout. The hero (verdict, trust score, recommended
action) stays always visible — it's the one thing every underwriter needs first. Everything else moves
into named tabs so the page reads as a *tool*, not a report dump.

```
┌─────────────────────────────────────────────────────────┐
│ VerdictHero  (verdict · trust score · recommended action)│
│ EvidenceSufficiencyBanner (when present)                 │
├─────────────────────────────────────────────────────────┤
│ [ Overview ] [ Claims & rules ] [ Signals & preview ] [Copilot]│
├─────────────────────────────────────────────────────────┤
│  ← active tab content only →                              │
├─────────────────────────────────────────────────────────┤
│ CaseMeta · PrivacyNote  (footer rail, always visible)     │
└─────────────────────────────────────────────────────────┘
```

- **Overview** — PipelineWaterfall + ProvenanceCard + ReasonsCard + PendingList (the "what happened, at a
  glance" tab; this is the new default tab).
- **Claims & rules** — ClaimGraphView + RulePackPanel + AnomalyPanel (the deterministic-decision detail).
- **Signals & preview** — DocumentPreview (tamper overlay) + SignalList (unchanged pairing, just demoted
  to its own tab instead of competing for scroll real estate with everything else).
- **Copilot** — CopilotPanel gets its own tab instead of sitting inline above everything else at all times
  — it's a support tool, not a headline.

Note: `CrossDocumentGraph` (multi-document corroboration) is driven by `BundleTrustScore.cross_document`,
a different wire shape than the single-document `TrustScore` this console renders — it already has a
home in `BundleConsole` for the bundle-intake path. Adding it here would mean inventing data `TrustScore`
doesn't carry, which CLAUDE.md §9 forbids; left out of this pass.

Tabs render conditionally exactly like today's sections do (`hasClaimGraph`, `hasRulePacks`, etc.) — a
tab with nothing to show doesn't appear. No fabricated states, no empty tabs.

### 3.2 Onboarding — targeted fixes, not a rebuild
The structural flow (4-step stepper, aurora sidebar, glass cards) stays as-is — it's good. Two changes:
1. Aadhaar block promoted out of `<details>` into a visible card (§2.3).
2. Explicit pre-upload format guidance + client-side format guard for the Aadhaar slot (§2.4).

### 3.3 Consortium — surface the ring graph earlier
Keep the simulator, but the ring detection panel gets a persistent empty-state that previews *what* a
detected ring looks like (a muted/ghost version of the SVG topology) rather than blank text, so the
"graph" is visible before the user manually drives 3+ submissions — discoverability, not new backend work.

### 3.4 Token hygiene
Replace `SampleView.tsx`'s hardcoded amber classes with the existing `verdict.review` / `verdict-review-soft`
tokens, matching every other "informational/pending" surface in the app.

---

## 4. Non-goals
- No new backend endpoints, no new fields on `TrustScore`/`CaseView` — this is a pure presentation-layer
  reorganization of data already returned today.
- No re-theming — the monochrome + gradient-highlight + glass system stays exactly as designed.
- No Aadhaar-photo verification path (see §2, item 5) — that would require real backend signal work and
  isn't a frontend concern.

## 5. Implementation order
1. `EvidenceConsole` → hero + tabs (highest-impact, addresses the core complaint).
2. Onboarding Aadhaar promotion + format guidance.
3. Consortium ring-graph empty-state preview.
4. `SampleView` token fix.

---

## 6. Addendum — global Copilot + case-level identity matrix

Two follow-up requests: stop burying the Copilot in a single tab, and surface the cross-document
identity comparison directly on the Case page instead of a one-line `corroboration_reason` string.

### 6.1 Global Copilot drawer
`CopilotPanel` calls `/api/interpret/narrative` and `/api/interpret/ask` with a full `EvidencePack` body
— that object only exists for a single verified document (`TrustScore.evidence_pack`). Consortium and
Master Model have no such object in the backend contract today, so a truly global chat with real content
everywhere isn't buildable frontend-only without inventing data (forbidden, CLAUDE.md §9).

What's built instead: `lib/CopilotContext.tsx` (a React context living above the router, so it survives
every route change) holds the **one** active evidence pack, plus a `GlobalCopilotDrawer` mounted once in
`AppShell` — a floating toggle + slide-in drawer on every underwriter-facing page. Whichever page most
recently produced a real evidence pack (`EvidenceConsole` on Console, or a per-document upload on the
Case page) registers it via `setCopilotContext`; the drawer keeps showing that context as you navigate to
Consortium or Master Model, rather than being torn down and losing state. Pages with nothing registered
yet show an honest "nothing to analyze yet" state — not a fake chat box.

Note: `CasePage` registers the **most recently added document's** evidence pack, not a case-wide one —
there is no case-level `EvidencePack` on the wire. A genuinely case-aware Copilot (reasoning over the
whole accumulated case, not just the latest document) needs a backend endpoint that assembles one; out of
scope for a frontend-only pass, recorded here rather than faked.

### 6.2 Case-level identity matrix
`/api/cases/{id}` (`CaseView`) originally carried only per-document `identity: Record<string,string>`
and a flat `hard_mismatch_fields: string[]` — the richer `cross_document.measurements.comparisons[]`
(agree / near-OCR-slip / disagree per field) was already computed server-side (`forensics/cross_document.py`)
but never forwarded past the flattened `hard_mismatch_fields` list, so the first pass of this matrix could
only render a coarse 2-tier view.

**Resolved**: `backend/app/routes/cases.py` now returns `comparisons: FieldComparisonView[]` on `CaseView`
(additive, non-breaking — new field only), so `CaseIdentityMatrix` renders the real 3-tier classification,
matching `CrossDocumentGraph`'s visual language and granularity exactly. The old client-side 2-tier
derivation stays in the component as a defensive fallback only (a case snapshot with no `comparisons`
data), never as the primary path. Verified: `pytest tests/test_cases_api.py tests/test_case_store.py` (8
passed), `ruff check` clean, frontend typecheck/lint/build clean.

### 6.3 Copilot: stale-context confusion + re-fetch-on-reopen (fixed)
Two real bugs surfaced in use: (1) `GlobalCopilotDrawer` conditionally rendered `CopilotPanel` only while
open, so every close/reopen unmounted it and threw away the loaded narrative + chat history, forcing a
fresh `/api/interpret/narrative` call each time (the "stuck spinner" on reopen). Fixed by keeping the
panel permanently mounted and toggling visibility with a CSS transform instead — `CopilotPanel`'s own
state (and therefore the fetched narrative) now only resets when the evidence pack itself changes, not on
open/close. (2) On Consortium/Master Model — pages with no document-evidence-pack concept at all — the
drawer silently kept discussing the last analyzed document with no indication *why*, reading as if the
copilot were confused about which page it's on. Fixed with an explicit banner naming the current page and
stating plainly that this page has no evidence pack of its own, rather than either faking page-aware
reasoning or leaving the mismatch unexplained.

**Recorded debt, NOT built here** (needs a backend change, not fakeable frontend-only per CLAUDE.md §9):
a copilot that can actually reason about Consortium ring evidence, or about a whole case's accumulated
documents rather than just the latest one, needs `/api/interpret/*` to accept a different context shape
per page (ring evidence, a case-level claims summary) instead of being hard-scoped to one document's
`EvidencePack`. The temperature is already 0.0 server-side (`interpretability/mcp_client.py:84`), so a
given evidence pack's narrative is deterministic — the "inconsistent" complaint was the re-fetch-on-reopen
bug above and this page-context gap, not model nondeterminism.
