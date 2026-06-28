# Deploying Satyum

Two paths. **Option A** (recommended) is a single `docker compose` stack — one origin, a durable
Postgres audit ledger, easiest to run anywhere. **Option B** is a split Vercel + Railway hosting.
Both give HTTPS in production, which the **live camera mode requires** (`getUserMedia` needs a secure
context).

> **Verified locally — not imagined.** `docker compose up --build` brings up the whole stack;
> `http://localhost:8080` serves the console, `/api/health` reports `"audit_backend": "postgres"`,
> verdicts are correct for every sample, and an audit record **survived a backend container restart**
> (the Postgres hash chain stayed intact). The backend image also runs standalone on Railway.

---

## Option A — One command: `docker compose` (recommended)

```bash
docker compose up --build        # from the repo root
# → http://localhost:8080
```

This starts three services (see [`docker-compose.yml`](docker-compose.yml)):

| Service | Role |
|---|---|
| **frontend** | nginx serving the built React app and reverse-proxying `/api` + `/ws` to the backend — **one origin**, so no CORS and the camera WebSocket works ([`deploy/nginx.conf`](deploy/nginx.conf)). |
| **backend** | FastAPI verification waterfall ([`backend/Dockerfile`](backend/Dockerfile)), `SATYUM_DATABASE_ENABLED=true` → **durable Postgres audit ledger**. |
| **db** | Postgres 16; the hash-chained audit trail persists in a named volume and survives restarts. |

**Deploy this on any cloud:** any VM with Docker (`docker compose up -d` behind a TLS-terminating
proxy / Caddy / the platform's HTTPS), or a Docker-friendly PaaS (Render, Fly.io, a cloud VM). Use a
managed Postgres by pointing `SATYUM_DATABASE_URL` at it instead of the bundled `db` service. **Change
the Postgres password** from the demo default.

## Option B — Split: Frontend on Vercel, Backend on Railway

For serverless-style hosting. The frontend calls the backend at an absolute URL baked in at build time
(`VITE_API_BASE_URL`); the backend allows that origin via CORS.

**Backend → Railway** ([`railway.json`](railway.json) builds [`backend/Dockerfile`](backend/Dockerfile)):
1. Push to GitHub → Railway **New Project → Deploy from GitHub repo** (it reads `railway.json`).
2. Add a **Postgres** plugin, then set service variables:
   - `SATYUM_DATABASE_ENABLED=true` and `SATYUM_DATABASE_URL=<the Railway Postgres URL>`
     (use the `postgresql+psycopg://…` scheme).
   - `SATYUM_CORS_ALLOW_ORIGINS=<your Vercel URL>`.
3. Deploy; healthcheck `/api/health`. Copy the public URL.

**Frontend → Vercel** ([`frontend/vercel.json`](frontend/vercel.json)):
1. Import the repo, set **Root Directory = `frontend`** (Vercel auto-detects Vite).
2. Env var `VITE_API_BASE_URL=<your Railway backend URL>` → Deploy.
3. Put the resulting Vercel URL back into Railway's `SATYUM_CORS_ALLOW_ORIGINS` → redeploy backend.

The **Vercel URL** is your live link.

---

## Solving the two caveats

### 1. Real cryptographic trust anchor (CCA-India root)

The images bundle a **demo** CA root so the sample signed PDF verifies out of the box — it will **not**
verify real DigiLocker / signed-bank-statement / signed-land-record documents. Those chain to the
public **CCA-India** root (https://www.cca.gov.in/ → repository of CA certificates). Install it with the
validate-and-install helper (it parses the cert and prints its subject/issuer/fingerprint — it does not
invent one):

```bash
python scripts/install_trust_anchor.py /path/to/cca-india-root.cer --dir deploy/trust-anchors
```

Then point the backend at it:
- **compose**: mount it and set the env in `docker-compose.yml`:
  ```yaml
  backend:
    volumes: ["./deploy/trust-anchors:/anchors:ro"]
    environment:
      SATYUM_TRUST_ANCHOR_DIR: "/anchors"
  ```
- **Railway**: set `SATYUM_TRUST_ANCHOR_DIR` to a path you provision the root into.

*Honest boundary:* installing the root makes Tier-1 *able* to verify real documents — still confirm
end-to-end against a genuine signed sample before trusting the verdict in production.

### 2. Durable audit ledger — **solved**

The tamper-evident, hash-chained audit ledger now persists to **Postgres** (`SqlAlchemyLedgerStore`),
enabled by `SATYUM_DATABASE_ENABLED=true` (compose sets this). It **survives restarts** and the chain
stays verifiable (proven above). `/api/health` reports the live backend (`"audit_backend": "postgres"`);
if the DB is ever unreachable it **fails safe** to in-memory and says so — it never pretends durability
it doesn't have. Camera **frames** are still never persisted (privacy by design, §10). *Session* state
remains in-memory by design (Redis is the documented next step; it holds no document content).

---

## Local development (no Docker)

```bash
# backend (from backend/, venv active, system tesseract-ocr installed)
pip install -r requirements.txt -r requirements-dev.txt
SATYUM_TRUST_ANCHOR_DIR="../samples/trust" uvicorn app.main:app --reload
# frontend (from frontend/)
npm install && npm run dev          # proxies /api and /ws to the backend
```
