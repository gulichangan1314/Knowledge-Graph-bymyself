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
echo "[1/3] Building graph (Neo4j if available, otherwise offline seed) ..."
"$PY" -m src.graph_builder --reset
echo "[2/3] Quality check ..."
"$PY" -m src.quality_check
echo "[3/3] Unit tests ..."
"$PY" -m unittest discover -s tests -v
echo
echo "[SUCCESS] Graph seed, quality gate, and tests passed."
echo "[NEXT] If Neo4j was online, the graph has been written. Otherwise start Neo4j first."
