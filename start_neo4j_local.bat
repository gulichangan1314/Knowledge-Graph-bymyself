@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "ROOT=%~dp0"
set "PROJECT=%ROOT%EnterpriseKG"
set "RUNTIME=%PROJECT%\.runtime"
set "PIDFILE=%RUNTIME%\neo4j.pid"
title EnterpriseKG Local Neo4j

if not exist "%PROJECT%\local_neo4j\target\classes\com\enterprisekg\localneo4j\EmbeddedNeo4jServer.class" goto :not_built
if not exist "%RUNTIME%\lib" goto :not_built

set "JAVA_HOME=%RUNTIME%\jre"
if not exist "%JAVA_HOME%\bin\java.exe" (
  for /d %%D in ("%RUNTIME%\jre\*") do (
    if exist "%%D\bin\java.exe" set "JAVA_HOME=%%D"
  )
)
if not exist "%JAVA_HOME%\bin\java.exe" (
  set "JAVA_HOME=%RUNTIME%\jdk"
  for /d %%D in ("%RUNTIME%\jdk\*") do (
    if exist "%%D\bin\java.exe" set "JAVA_HOME=%%D"
  )
)
if not exist "%JAVA_HOME%\bin\java.exe" goto :no_java

powershell -NoProfile -Command "$c=New-Object Net.Sockets.TcpClient; try { $c.Connect('127.0.0.1',7687); exit 0 } catch { exit 1 } finally { $c.Dispose() }"
if not errorlevel 1 (
  echo [OK] Local Neo4j is already listening on bolt://127.0.0.1:7687
  exit /b 0
)

if not exist "%RUNTIME%\neo4j-home" mkdir "%RUNTIME%\neo4j-home"
if exist "%PIDFILE%" del /q "%PIDFILE%" >nul 2>nul

echo ============================================================
echo  Starting workspace-local Neo4j 5.26 (no Docker, no service)
echo  Data: %RUNTIME%\neo4j-home
echo  Bolt: bolt://127.0.0.1:7687
echo  UI:   Streamlit workbench (local mode has no Neo4j Browser)
echo  First startup can take 30-60 seconds.
echo ============================================================

"%JAVA_HOME%\bin\java.exe" -Xms256m -Xmx1g -Djava.awt.headless=true "-Denterprisekg.data=%RUNTIME%\neo4j-home" "-Denterprisekg.pid=%PIDFILE%" "-Denterprisekg.bolt=7687" -cp "%PROJECT%\local_neo4j\target\classes;%RUNTIME%\lib\*" com.enterprisekg.localneo4j.EmbeddedNeo4jServer

echo.
echo [STOPPED] Local Neo4j process ended.
pause
exit /b 0

:not_built
echo [ERROR] Local Neo4j runtime is missing.
echo         Expected: EnterpriseKG\.runtime\lib and local_neo4j\target\classes
echo         Rebuild instructions: EnterpriseKG\local_neo4j\README.md
pause
exit /b 2

:no_java
echo [ERROR] Workspace JRE not found.
echo         Expected: EnterpriseKG\.runtime\jre\...\bin\java.exe
echo         Rebuild instructions: EnterpriseKG\local_neo4j\README.md
pause
exit /b 3
