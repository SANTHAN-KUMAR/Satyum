#!/usr/bin/env bash
# Satyum Layer-2 replay-cache control — save/replay real VLM extractions with no live API call.
#
# The cache stores ONLY genuine model output (never fabricated/edited); a replay re-runs the
# deterministic cross-read live and logs the hit as a replay. See forensics/extraction/cache.py.
#
# One-time setup (so runs get staged):
#   1) add to backend/.env:   SATYUM_VLM_CACHE_MODE=curated
#   2) restart the backend    (the extractor is built once at startup)
#
# Per-document flow, entirely from the terminal — nothing shows on the demo UI:
#   run the document in the app  ->  it stages the REAL extraction
#   ./cache.sh save              ->  keep it (replays on every future re-upload)
#   ./cache.sh skip              ->  discard it (buffer reset, keeps nothing)
#
# On a later re-upload of a saved document the app replays instantly, offline — even with the
# API rate-limited. A document you never saved still reads live (or fails closed if offline).

set -euo pipefail

API="${SATYUM_API:-http://127.0.0.1:8000}/api/vlm-cache"

case "${1:-help}" in
  save)   # keep everything staged (the document you just ran), then reset the buffer
    curl -fsS -X POST "$API/promote-all-staged"; echo
    curl -fsS -X POST "$API/clear-staged" >/dev/null; echo "saved ✓ (replays on re-upload)"
    ;;
  skip)   # discard the staged read(s) — keep nothing
    curl -fsS -X POST "$API/clear-staged" >/dev/null; echo "skipped (nothing saved)"
    ;;
  list)   # what is staged (just-run) vs saved (will replay)
    curl -fsS "$API"; echo
    ;;
  forget-all)  # forget every saved doc, so they read live again
    keys=$(curl -fsS "$API" | python3 -c 'import sys,json;print(json.dumps([e["key"] for e in json.load(sys.stdin)["saved"]]))')
    curl -fsS -X DELETE "$API/saved" -H 'Content-Type: application/json' -d "{\"keys\":$keys}"; echo
    ;;
  *)
    echo "usage: ./cache.sh {save|skip|list|forget-all}"
    echo "  save        keep the document you just ran (replays on re-upload)"
    echo "  skip        discard the just-run read"
    echo "  list        show staged (just-run) and saved (will-replay) entries"
    echo "  forget-all  drop every saved doc (they read live again)"
    ;;
esac
