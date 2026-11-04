@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "ROOT=%~dp0"
set "PROJECT=%ROOT%EnterpriseKG"
set "VENV=%PROJECT%\venv"
set "VPY=%VENV%\Scripts\python.exe"

if not exist "%PROJECT%\requirements.txt" (
  echo [ERROR] EnterpriseKG\requirements.txt not found.
  pause
  exit /b 1
)

if not exist "%ROOT%.tmp" mkdir "%ROOT%.tmp"
if not exist "%ROOT%.pip-cache" mkdir "%ROOT%.pip-cache"
set "TEMP=%ROOT%.tmp"
set "TMP=%ROOT%.tmp"
set "PIP_CACHE_DIR=%ROOT%.pip-cache"
set "PYTHONUTF8=1"
set "PIP_DISABLE_PIP_VERSION_CHECK=1"

echo ============================================================
echo  EnterpriseKG - one-click bootstrap
echo ============================================================

if exist "%VPY%" (
  echo [1/3] Reusing existing virtual environment.
  goto :ensure_dependencies
)

echo [1/3] Creating virtual environment: %VENV%
call :find_python
if not defined BASE goto :no_python
"%BASE%" -m venv "%VENV%"
if errorlevel 1 goto :venv_failed

:ensure_dependencies
"%VPY%" -c "import pandas, neo4j, streamlit, rapidfuzz, yaml" >nul 2>nul
if not errorlevel 1 (
  echo [2/3] Dependencies already present, skipping download.
  goto :verify
)

"%VPY%" -m pip --version >nul 2>nul
if not errorlevel 1 goto :install_packages

echo [2/3] Virtual environment has no pip; repairing it inside the workspace ...
call :find_python
if not defined BASE goto :no_python
"%BASE%" -m pip --python "%VPY%" install pip
if errorlevel 1 goto :pip_failed

:install_packages
echo [2/3] Installing project dependencies ...
"%VPY%" -m pip install --upgrade pip --disable-pip-version-check
if errorlevel 1 goto :pip_failed
"%VPY%" -m pip install -r "%PROJECT%\requirements.txt"
if errorlevel 1 goto :pip_failed

:verify
echo [3/3] Running offline pipeline and quality check ...
pushd "%PROJECT%"
"%VPY%" -m src.quality_check --offline
set "QC=%ERRORLEVEL%"
popd
if not "%QC%"=="0" goto :qc_failed

echo.
echo [SUCCESS] Python environment is ready.
echo [NEXT]    If Docker is available, double-click start_neo4j.bat.
echo [NEXT]    Then double-click start_app.bat to open the UI.
echo.
pause
exit /b 0

:find_python
set "BASE="
if exist "%ROOT%.runtime\Python313\python.exe" (
  set "BASE=%ROOT%.runtime\Python313\python.exe"
  goto :eof
)
where py >nul 2>nul
if not errorlevel 1 (
  for /f "usebackq delims=" %%I in (`py -3.13 -c "import sys; print(sys.executable)" 2^>nul`) do set "BASE=%%I"
)
if defined BASE goto :eof
where python >nul 2>nul
if not errorlevel 1 (
  for /f "usebackq delims=" %%I in (`python -c "import sys; print(sys.executable)" 2^>nul`) do set "BASE=%%I"
)
goto :eof

:no_python
echo [ERROR] Python 3.11+ was not found.
echo         Double-click install_python.bat first.
pause
exit /b 2

:venv_failed
echo [ERROR] Could not create the virtual environment.
pause
exit /b 1

:pip_failed
echo [ERROR] Dependency installation failed.
echo         Check the network, then run this file again.
echo         Temporary and cache files are kept inside the workspace.
pause
exit /b 1

:qc_failed
echo [ERROR] Offline self-test failed. Review the output above.
pause
exit /b 1
