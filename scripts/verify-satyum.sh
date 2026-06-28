#!/usr/bin/env bash
#
# verify-satyum.sh — one command to prove Satyum to a judge or reviewer.
#
# Runs the full backend test suite (including the must-fail fraud fixtures and the adversarial
# robustness battery), then regenerates the synthetic sample corpus so the drag-and-drop kit under
# samples/ is fresh. Exits non-zero if anything fails. No network, no real data.
#
# Usage:   ./scripts/verify-satyum.sh
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$REPO/backend"

# Prefer the project venv's interpreter; fall back to python3 on PATH.
if [[ -x "$BACKEND/.venv/bin/python" ]]; then
  PY="$BACKEND/.venv/bin/python"
else
  PY="$(command -v python3 || true)"
fi
if [[ -z "${PY:-}" ]]; then
  echo "ERROR: no Python interpreter found. Create backend/.venv and install requirements.txt." >&2
  exit 1
fi

bar() { printf '\n\033[1m%s\033[0m\n' "── $* ──────────────────────────────────────────" ; }

bar "1/3  Backend test suite  (discrimination + must-fail fraud fixtures + fail-closed)"
( cd "$BACKEND" && "$PY" -m pytest -q )

bar "2/3  Adversarial robustness battery  (edit-at-scale + degradation never-false-clears)"
( cd "$BACKEND" && "$PY" -m pytest -q tests/test_adversarial_battery.py )

bar "3/3  Regenerate the synthetic sample corpus  (samples/ is reproducible, not hand-tuned)"
"$PY" "$REPO/samples/generate.py"

printf '\n\033[32m\033[1m✓ Satyum verified.\033[0m  Test the live system by dragging files from samples/ into the console.\n'
printf '  • File upload tab: pdfs/* and statements/*\n'
printf '  • Document bundle tab: both files in bundle_consistent/ (or bundle_mismatch/)\n'
printf '  • For Tier-1 to PASS, start the backend with:\n'
printf '      SATYUM_TRUST_ANCHOR_DIR="%s/samples/trust" uvicorn app.main:app\n' "$REPO"
