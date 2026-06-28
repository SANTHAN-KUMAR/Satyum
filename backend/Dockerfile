# Satyum backend — production container (Railway / any Docker host).
# Build context is the REPO ROOT (so the demo trust anchor under samples/ can be bundled):
#     docker build -f backend/Dockerfile -t satyum-backend .
FROM python:3.13-slim AS base

# System deps the Python wheels need at runtime:
#   tesseract-ocr  -> the OCR engine pytesseract shells out to (Tier-2 arithmetic path)
#   libgomp1       -> OpenMP runtime for opencv-python-headless / scikit-image
#   libglib2.0-0   -> glib, pulled in by some opencv builds
# (PyMuPDF, pikepdf/qpdf and cryptography ship self-contained wheels — no extra apt needed.)
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        libgomp1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first so the layer caches across code changes.
COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Application code.
COPY backend/ /app/

# Bundle the demo CA public root so the sample genuine-signed PDF verifies out of the box. In a real
# deployment, override SATYUM_TRUST_ANCHOR_DIR with the public CCA-India root (mounted/secret), and
# SATYUM_CORS_ALLOW_ORIGINS with the frontend origin if the frontend is on a different host.
COPY samples/trust/ /app/demo-trust/
ENV SATYUM_TRUST_ANCHOR_DIR=/app/demo-trust \
    PYTHONUNBUFFERED=1

# Drop root for runtime (least privilege).
RUN useradd --create-home --uid 10001 satyum && chown -R satyum /app
USER satyum

EXPOSE 8000
# Railway/most PaaS inject $PORT; default to 8000 for a local `docker run -p 8000:8000`.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
