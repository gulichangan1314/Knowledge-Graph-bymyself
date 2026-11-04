@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "PIDFILE=%CD%\EnterpriseKG\.runtime\neo4j.pid"

if exist "%PIDFILE%" (
  call "%CD%\stop_neo4j_local.bat"
  exit /b %errorlevel%
)

where docker >nul 2>nul
if errorlevel 1 (
  echo [INFO] No local Neo4j PID file and Docker is not installed. Nothing to stop.
  exit /b 0
)
docker compose down
if errorlevel 1 docker-compose down
echo [OK] Neo4j container stopped.
pause
exit /b 0
