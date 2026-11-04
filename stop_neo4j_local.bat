@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "PIDFILE=%CD%\EnterpriseKG\.runtime\neo4j.pid"

if not exist "%PIDFILE%" (
  echo [INFO] No local Neo4j PID file found.
  exit /b 0
)

set "NEO4J_PID="
set /p NEO4J_PID=<"%PIDFILE%"
if not defined NEO4J_PID (
  echo [WARN] PID file is empty.
  del /q "%PIDFILE%" >nul 2>nul
  exit /b 1
)

echo [INFO] Stopping local Neo4j PID %NEO4J_PID% ...
taskkill /PID %NEO4J_PID% /T /F >nul 2>nul
if errorlevel 1 (
  echo [WARN] Could not stop PID %NEO4J_PID%. It may already be stopped.
) else (
  echo [OK] Local Neo4j stopped.
)
del /q "%PIDFILE%" >nul 2>nul
exit /b 0
