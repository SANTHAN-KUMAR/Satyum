# Satyum — Underwriter Evidence Console (frontend)

React 18 + TypeScript + Vite + Tailwind. The bank-facing console: upload a document (or run a live
capture), and see the explainable, fail-closed trust verdict the backend produced — verdict, animated
trust gauge with labelled bands, provenance, per-signal status with producing-mode tags, the
tamper-evidence overlay, reasons, recommended action, the pending/not-evaluated list, and the privacy
note. **Every number on screen comes from the real backend response** (CLAUDE.md §9) — the only
fixture is a clearly-labelled offline "Sample view".

## Run it

```bash
cd frontend
npm install
cp .env.example .env.local        # then set SATYUM_BACKEND_ORIGIN if not http://127.0.0.1:8000
npm run dev                        # http://localhost:5173
```

The Vite dev server proxies `/api` and `/ws` to `SATYUM_BACKEND_ORIGIN` (mirrors the production Nginx
reverse proxy), so the browser talks same-origin. No backend URL is hardcoded in source.

Other scripts: `npm run build` · `npm run preview` · `npm run typecheck` · `npm run lint`.

> The **Sample view** tab renders the console against a hand-authored fixture and works with no
> backend running. The **File upload** and **Live capture** tabs require the backend.

## API contract it expects

### `POST /api/verify` (multipart/form-data) → `TrustScore`
- Form field **`file`** (required): the document bytes (PDF or image). Optional **`doc_type`**.
- 2xx body is a `TrustScore` JSON (see `backend/app/contracts.py`) including `.evidence_pack`
  (`backend/risk/evidence.py`). The exact shape is mirrored in `src/api/types.ts` and validated at
  the boundary in `src/api/guards.ts`.
- Errors: the client surfaces FastAPI `{ "detail": ... }` and the HTTP status honestly, with retry.

### `WS /ws/verify` — live-capture (Tier-3 active 3D challenge)
Native WebSocket. Client → server: `hello` then downscaled `frame` messages (~300 ms cadence).
Server → client (all validated): `challenge` (the time-bounded physical-challenge instruction),
`tier_status` (live per-signal status), `result` (final `TrustScore`), `notice`/`error`.
See the message types in `src/api/types.ts`.

> The WS client connects for **real** and reports its true connection state. If `/ws/verify` is not
> implemented yet, the UI shows an honest **"Backend unreachable"** state and renders **no** fabricated
> challenge or signal data (CLAUDE.md §3.1).

## Layout

```
src/
  api/        types.ts (wire contract) · guards.ts (boundary validation) · client.ts (typed client)
  components/
    evidence/ EvidenceConsole + VerdictBanner, TrustGauge, ProvenanceCard, SignalList,
              DocumentPreview (tamper overlay), ReasonsCard, PendingList, RecommendedAction,
              PrivacyNote, CaseMeta
    camera/   CameraCapture, ChallengeOverlay, LiveTierStatus, ConnectionBadge
    primitives/ Panel, StatusPill, Tag, StateMessage
    UploadIntake · SampleView · ModeTabs · AppHeader · ErrorBoundary
  hooks/      useVerifyDocument · useCamera · useVerifysocket · useFrameSampler · useCountUp
  lib/        verdict.ts (semantics + bands) · file.ts (intake guards) · cn.ts
  fixtures/   sampleTrustScore.ts (SAMPLE only — never on the live paths)
```
