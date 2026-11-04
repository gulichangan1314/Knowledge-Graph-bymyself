@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "PROJECT=%CD%\EnterpriseKG"
set "VPY=%PROJECT%\venv\Scripts\python.exe"
if not exist "%VPY%" (
  echo [ERROR] Virtual environment not found.
  echo         Double-click bootstrap.bat first.
  pause
  exit /b 2
)
set "PYTHONUTF8=1"
cd /d "%PROJECT%"
echo [1/3] Building graph (Neo4j if available, otherwise offline seed) ...
"%VPY%" -m src.graph_builder --reset
if errorlevel 1 goto :failed
echo [2/3] Quality check ...
"%VPY%" -m src.quality_check
if errorlevel 1 goto :failed
echo [3/3] Unit tests ...
"%VPY%" -m unittest discover -s tests -v
if errorlevel 1 goto :failed
echo.
echo [SUCCESS] Graph seed, quality gate, and tests passed.
echo [NEXT] If Neo4j was online, the graph has been written. Otherwise use start_neo4j.bat first.
pause
exit /b 0
:failed
echo [ERROR] A pipeline step failed. Review the output above.
pause
exit /b 1
