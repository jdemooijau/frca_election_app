@echo off
cd /d "%~dp0"
echo ================================================
echo   FRCA Load Test
echo   Seeds demo, starts server, casts 95 votes
echo ================================================
echo.

REM --- Step 1: Seed demo election with 100 codes ---
echo [1/3] Seeding demo election (100 codes)...
echo YES | python scripts/seed_demo.py --codes 100
if errorlevel 1 (
    echo.
    echo   Seed failed. See error above.
    pause
    exit /b 1
)

REM --- Step 2: Start server in a new window ---
echo.
echo [2/3] Starting server...
start "FRCA Election Server" python -m waitress --host=0.0.0.0 --port=5000 app:app

REM Wait for server to be ready
echo   Waiting for server to start...
:wait_loop
timeout /t 1 /nobreak >nul
python -c "import requests; requests.get('http://localhost:5000/', timeout=2)" 2>nul
if errorlevel 1 goto wait_loop
echo   Server is up.

REM --- Step 3: Open display + run load test ---
echo.
echo [3/3] Casting 95 votes (0.2s delay)...
echo   Watch live: http://localhost:5000/display
echo.
start http://localhost:5000/display
python scripts/load_test.py --voters 95 --delay 0.2
pause
