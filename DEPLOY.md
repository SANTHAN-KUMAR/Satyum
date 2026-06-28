# Deploying Satyum — Frontend on Vercel, Backend on Railway

Satyum deploys as **two services**: a static React frontend (Vercel) and a Dockerised FastAPI
backend (Railway). They talk over HTTPS; the frontend calls the backend at an absolute URL configured
at build time. Both platforms issue TLS certificates automatically — which the **live camera mode
requires** (`getUserMedia` only runs on a secure context).

```
  Browser ──HTTPS──▶  Vercel (static dist/)         the evidence console (React)
     │
     └──HTTPS /api──▶  Railway (Docker, FastAPI)     the verification waterfall + cross-doc graph
        wss  /ws   ▶                                 (camera mode connects the socket directly)
```

> **Status — verified locally.** The backend image builds and runs: `docker build -f backend/Dockerfile .`
> produces a working image (897 MB) whose `/api/health` is green and which returns the correct verdicts
> for every sample (Tier-1 `genuine_signed.pdf` → APPROVED/source-verified against the bundled demo
> anchor; tampered statement → REJECTED; bundle mismatch → REJECTED; CORS preflight honoured). The
> Vercel/Railway *hosting* steps below have not been executed for you — they need your accounts.

---

## 1. Backend → Railway

The repo ships [`railway.json`](railway.json) (builds `backend/Dockerfile`, healthcheck `/api/health`)
and the [`backend/Dockerfile`](backend/Dockerfile) (Python 3.13 + the `tesseract-ocr` system binary).
**Build context is the repo root**, so the demo trust anchor is bundled into the image.

1. Push this repo to GitHub.
2. Railway → **New Project → Deploy from GitHub repo** → pick this repo. Railway reads `railway.json`
   and builds the Dockerfile (no extra config needed). It injects `$PORT`; the container binds it.
3. Set service **Variables** (Railway → service → Variables):
   - `SATYUM_CORS_ALLOW_ORIGINS` = your Vercel URL (e.g. `https://satyum.vercel.app`). You can set a
     placeholder now and update it after step 2 of the frontend.
   - *(optional)* `SATYUM_TRUST_ANCHOR_DIR` — leave unset to use the **bundled demo anchor** (verifies
     the sample signed PDF). For real documents, mount the public CCA-India root and point this at it.
4. Wait for the deploy to go green (healthcheck hits `/api/health`). Copy the public URL, e.g.
   `https://satyum-backend-production.up.railway.app`. Confirm it:
   ```bash
   curl https://<your-railway-url>/api/health
   ```

## 2. Frontend → Vercel

The repo ships [`frontend/vercel.json`](frontend/vercel.json) (Vite framework + SPA fallback).

1. Vercel → **Add New → Project** → import this repo.
2. Set **Root Directory = `frontend`** (Settings → General → Root Directory). Vercel auto-detects Vite
   (build `npm run build`, output `dist`).
3. Add an **Environment Variable**:
   - `VITE_API_BASE_URL` = your Railway backend URL from step 1.4 (no trailing slash).
4. **Deploy.** Copy the Vercel URL (e.g. `https://satyum.vercel.app`).
5. **Close the loop:** put that Vercel URL into Railway's `SATYUM_CORS_ALLOW_ORIGINS` (step 1.3) and
   redeploy the backend so cross-origin calls (and the camera WebSocket) are allowed.

That's the whole submission: the **Vercel URL** is your live system link.

---

## Order of operations (the chicken-and-egg)

Backend first → get its URL → set `VITE_API_BASE_URL` and deploy the frontend → get its URL → set
`SATYUM_CORS_ALLOW_ORIGINS` on the backend → redeploy backend. Two redeploys, done.

## Run the backend container locally (what was verified here)

```bash
# from the repo root
docker build -f backend/Dockerfile -t satyum-backend .
docker run -d -p 8080:8000 -e SATYUM_CORS_ALLOW_ORIGINS="http://localhost:5173" satyum-backend
curl http://localhost:8080/api/health
curl -X POST http://localhost:8080/api/verify -F "file=@samples/pdfs/genuine_signed.pdf"   # → APPROVED
```

Run the frontend against it: `cd frontend && VITE_API_BASE_URL=http://localhost:8080 npm run dev`
(or rely on the dev proxy in `vite.config.ts` with no env set).

## Notes & honest limits

- **Trust anchor.** The image bundles the demo CA *public* root so the sample signed PDF verifies out
  of the box. It will NOT verify real DigiLocker/bank documents — those need the public **CCA-India**
  root via `SATYUM_TRUST_ANCHOR_DIR`. No private key is ever in the image or repo (CLAUDE.md §10).
- **Camera mode.** HTTPS is mandatory (both platforms provide it). The WebSocket connects **directly**
  to the Railway backend (`wss://…/ws/verify`), derived from `VITE_API_BASE_URL` — Vercel cannot proxy
  WebSockets.
- **Persistence.** The audit ledger and sessions are **in-memory** today (they reset on restart) — the
  Postgres durable store is the designed next step (add a Railway Postgres plugin + wire the store).
- **Image size** ≈ 897 MB (OpenCV + PyMuPDF + scientific stack + Tesseract). Fine for Railway.
