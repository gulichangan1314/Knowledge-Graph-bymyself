@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "ROOT=%~dp0"
set "PROJECT=%ROOT%EnterpriseKG"

echo ============================================================
echo  EnterpriseKG - Neo4j startup (Docker-free first)
echo ============================================================

if exist "%PROJECT%\local_neo4j\target\classes\com\enterprisekg\localneo4j\EmbeddedNeo4jServer.class" (
  if exist "%PROJECT%\.runtime\lib" (
    echo [INFO] Workspace-local Neo4j runtime found. Docker is not required.
    call "%ROOT%start_neo4j_local.bat"
    exit /b %errorlevel%
  )
)

where docker >nul 2>nul
if errorlevel 1 goto :no_local_and_no_docker

docker info >nul 2>nul
if errorlevel 1 goto :engine_down

set "COMPOSE=docker compose"
docker compose version >nul 2>nul
if errorlevel 1 (
  where docker-compose >nul 2>nul
  if errorlevel 1 goto :no_compose
  set "COMPOSE=docker-compose"
)

echo [INFO] Docker fallback selected.
%COMPOSE% up -d
if errorlevel 1 goto :compose_failed

echo [INFO] Waiting for Neo4j HTTP endpoint (up to 3 minutes) ...
powershell -NoProfile -Command "$deadline=(Get-Date).AddMinutes(3); while((Get-Date) -lt $deadline){ try { $r=Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:7474' -TimeoutSec 3; if($r.StatusCode -eq 200){ exit 0 } } catch {}; Start-Sleep -Seconds 3 }; exit 1"
if errorlevel 1 (
  echo [WARN] Neo4j is still starting. Check: docker compose logs -f neo4j
  pause
  exit /b 1
)

echo [OK] Neo4j is reachable.
echo [OK] Browser UI: http://localhost:7474
echo [OK] Bolt URL : bolt://127.0.0.1:7687
echo [NEXT] Run: run_pipeline.bat
start "" "http://localhost:7474"
pause
exit /b 0

:no_local_and_no_docker
echo [ERROR] Neither workspace-local Neo4j nor Docker is available.
echo.
echo  Rebuild local runtime: EnterpriseKG\local_neo4j\README.md
echo  Or install Docker Desktop: https://www.docker.com/products/docker-desktop/
pause
exit /b 2

:engine_down
echo [ERROR] Docker is installed but its engine is not running.
echo         Start Docker Desktop, wait for "Engine running", then retry.
pause
exit /b 3

:no_compose
echo [ERROR] Docker Compose v2 was not found.
echo         Update Docker Desktop, then retry.
pause
exit /b 4

:compose_failed
echo [ERROR] docker compose up failed. Inspect the output above.
pause
exit /b 5
