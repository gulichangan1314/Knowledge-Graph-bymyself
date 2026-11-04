@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "PROJECT=%CD%\EnterpriseKG"
set "VPY=%PROJECT%\venv\Scripts\python.exe"
if not exist "%VPY%" (
  echo [ERROR] Virtual environment not found. Run bootstrap.bat first.
  pause
  exit /b 2
)
set "PYTHONUTF8=1"
cd /d "%PROJECT%"
echo Starting Streamlit at http://127.0.0.1:8501 ...
"%VPY%" -m streamlit run app\main.py --server.address 127.0.0.1 --server.port 8501
pause
