@echo off
echo ============================================
echo   Trading Bot Dashboard
echo   http://localhost:8501
echo ============================================
echo.
cd /d "%~dp0"
pip install -r requirements.txt -q 2>nul
python server.py
pause
