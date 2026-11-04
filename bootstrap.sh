#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT="$ROOT/EnterpriseKG"
VENV="$PROJECT/venv"
PY="$VENV/bin/python"

if [[ ! -f "$PROJECT/requirements.txt" ]]; then
  echo "[ERROR] $PROJECT/requirements.txt not found."
  exit 1
fi

PYTHON=""
for candidate in python3.13 python3.12 python3.11 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then
    if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
      PYTHON="$(command -v "$candidate")"
      break
    fi
  fi
done

if [[ -z "$PYTHON" ]]; then
  echo "[ERROR] Python 3.11+ not found. Run ./install_python.sh first."
  exit 2
fi

export TMPDIR="$ROOT/.tmp"
export PIP_CACHE_DIR="$ROOT/.pip-cache"
export PYTHONUTF8=1
export PIP_DISABLE_PIP_VERSION_CHECK=1
mkdir -p "$TMPDIR" "$PIP_CACHE_DIR"

if [[ ! -x "$PY" ]]; then
  echo "[1/3] Creating virtual environment: $VENV"
  "$PYTHON" -m venv "$VENV"
fi

echo "[2/3] Installing project dependencies ..."
"$PY" -m pip install --upgrade pip --disable-pip-version-check
"$PY" -m pip install -r "$PROJECT/requirements.txt"

echo "[3/3] Running offline pipeline and quality check ..."
cd "$PROJECT"
"$PY" -m src.quality_check --offline

cat <<'EOF'

[SUCCESS] Python environment is ready.
[NEXT]    Install/start Docker, then run ./start_neo4j.sh
[NEXT]    Run ./start_app.sh to open the Streamlit UI.
EOF
