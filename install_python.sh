#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PY=""
for candidate in python3.13 python3.12 python3.11 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then
    if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
      PY="$(command -v "$candidate")"
      break
    fi
  fi
done

if [[ -z "$PY" ]]; then
  cat <<'EOF'
[ERROR] Python 3.11+ was not found.

This script cannot silently install a system-wide interpreter without admin rights.
Install Python from the official source, then run this file again:

  macOS:
    https://www.python.org/downloads/macos/
    Download "Python 3.13.15 macOS installer" and install it.

  Ubuntu / Debian (requires admin, run yourself):
    sudo apt update
    sudo apt install -y python3 python3-venv python3-pip

  Other Linux:
    https://www.python.org/downloads/source/

No system files were modified by this script.
EOF
  exit 2
fi

echo "[OK] Python found: $PY ($($PY --version 2>&1))"
echo "[INFO] Creating an isolated virtual environment inside EnterpriseKG/venv ..."
exec bash "$ROOT/bootstrap.sh"
