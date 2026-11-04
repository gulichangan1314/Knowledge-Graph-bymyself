@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "ROOT=%~dp0"
set "LOCAL_PY=%ROOT%.runtime\Python313\python.exe"

echo ============================================================
echo  EnterpriseKG - Python setup / repair
echo  This script only writes inside the project workspace.
echo ============================================================

if exist "%LOCAL_PY%" (
  echo [OK] Workspace-local Python found: %LOCAL_PY%
  goto :bootstrap
)

where py >nul 2>nul
if not errorlevel 1 (
  py -3.13 --version >nul 2>nul
  if not errorlevel 1 (
    echo [OK] Python 3.13 detected through the py launcher.
    goto :bootstrap
  )
)

if exist "%ROOT%.runtime\Python313\python.exe" goto :bootstrap

echo [INFO] No suitable Python 3.13 found.
echo [INFO] Downloading the official Python 3.13.15 installer into .downloads ...
if not exist "%ROOT%.downloads" mkdir "%ROOT%.downloads"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.13.15/python-3.13.15-amd64.exe' -OutFile '%ROOT%.downloads\python-3.13.15-amd64.exe'"
if errorlevel 1 goto :download_failed

echo [INFO] Installing Python silently into .runtime\Python313 ...
start /wait "" "%ROOT%.downloads\python-3.13.15-amd64.exe" /quiet InstallAllUsers=0 TargetDir="%ROOT%.runtime\Python313" Include_pip=1 Include_test=0 Include_launcher=0 PrependPath=0 Shortcuts=0
if not exist "%LOCAL_PY%" goto :install_failed
echo [OK] Workspace-local Python installed.

:bootstrap
call "%ROOT%bootstrap.bat"
exit /b %errorlevel%

:download_failed
echo [ERROR] Python installer download failed.
echo         Check your network, then download manually from:
echo         https://www.python.org/downloads/windows/
echo         Place it anywhere and run it, then double-click this file again.
pause
exit /b 1

:install_failed
echo [ERROR] Silent Python installation did not complete.
echo         Run the downloaded installer manually:
echo         %ROOT%.downloads\python-3.13.15-amd64.exe
pause
exit /b 1
