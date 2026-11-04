#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
[[ -f .env ]] || cp .env.example .env

if ! command -v docker >/dev/null 2>&1; then
  cat <<'EOF'
[ERROR] Docker was not found.

Install Docker Desktop / Docker Engine:
  https://docs.docker.com/get-docker/

Windows/macOS: install Docker Desktop, start it, and wait for "Engine running".
Linux: install Docker Engine + Compose plugin (requires admin).
Offline mode is still available: ./run_pipeline.sh
EOF
  exit 2
fi

if ! docker info >/dev/null 2>&1; then
  echo "[ERROR] Docker is installed but the engine is not running."
  echo "        Start Docker Desktop / dockerd, then retry."
  exit 3
fi

if docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE=(docker-compose)
else
  echo "[ERROR] Docker Compose v2 not found."
  exit 4
fi

echo "[1/3] Starting Neo4j container ..."
"${COMPOSE[@]}" up -d

echo "[2/3] Waiting for Neo4j HTTP endpoint ..."
for _ in $(seq 1 60); do
  if command -v curl >/dev/null 2>&1 && curl -fsS http://127.0.0.1:7474 >/dev/null 2>&1; then
    echo "[3/3] Neo4j is reachable."
    echo "[OK] Browser UI: http://localhost:7474"
    echo "[OK] Bolt URL : bolt://127.0.0.1:7687"
    echo "[NEXT] Run: ./run_pipeline.sh"
    exit 0
  fi
  sleep 3
done

echo "[WARN] Neo4j is still starting. Check: ${COMPOSE[*]} logs -f neo4j"
echo "       Browser: http://localhost:7474"
exit 1
