@echo off
setlocal
cd /d "%~dp0"
title StockAnalyse

echo.
echo Starting StockAnalyse web app...
echo Project dir: %cd%
echo URL: http://localhost:8501
echo.

set STREAMLIT_BROWSER_GATHER_USAGE_STATS=false
set STREAMLIT_SERVER_HEADLESS=true

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Cannot find .venv\Scripts\python.exe
  echo Please install dependencies first.
  echo.
  pause
  exit /b 1
)

if not exist "web_app.py" (
  echo [ERROR] Cannot find web_app.py
  echo Please put this launcher in the project root folder.
  echo.
  pause
  exit /b 1
)

start "" "http://localhost:8501"
".venv\Scripts\python.exe" -m streamlit run web_app.py --server.port 8501 --server.headless true --browser.gatherUsageStats false

echo.
echo App stopped. If there is an error above, send it to Codex.
pause
