#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

if command -v docker >/dev/null 2>&1; then
  if docker compose version >/dev/null 2>&1; then
    docker compose down
  elif command -v docker-compose >/dev/null 2>&1; then
    docker-compose down
  else
    echo "[ERROR] Docker Compose not found."
    exit 4
  fi
  echo "[OK] Neo4j container stopped."
else
  echo "[ERROR] Docker was not found."
  exit 2
fi
