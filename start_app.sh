#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT="$ROOT/EnterpriseKG"
PY="$PROJECT/venv/bin/python"
if [[ ! -x "$PY" ]]; then
  echo "[ERROR] Virtual environment not found. Run ./bootstrap.sh first."
  exit 2
fi

export PYTHONUTF8=1
cd "$PROJECT"
echo "Starting Streamlit at http://127.0.0.1:8501 ..."
exec "$PY" -m streamlit run app/main.py --server.address 127.0.0.1 --server.port 8501
