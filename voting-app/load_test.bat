@echo off
cd /d "%~dp0"

REM ---- Configuration -------------------------------------------------------
REM Admin password is reset to "admin" by seed_demo (--reset-password).
REM Override only if you need to test against a live DB with a different password:
REM   set FRCA_ADMIN_PASSWORD=yourpassword
REM --------------------------------------------------------------------------

echo ================================================
echo   FRCA Mass Test
echo   Seeds demo, starts server, runs full election
echo   simulation: postal votes, display flow, 95
echo   concurrent digital voters, paper ballots
echo ================================================
echo.

REM --- Step 0: Kill any server already on port 5000 ---
echo [1/4] Stopping any existing server on port 5000...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :5000 ^| findstr LISTENING 2^>nul') do (
    taskkill /f /pid %%a >nul 2>&1
)
timeout /t 1 /nobreak >nul

REM --- Step 1: Seed demo election with 100 codes ---
echo [2/4] Seeding demo election (100 codes)...
echo YES | python scripts/seed_demo.py --codes 100
if errorlevel 1 (
    echo.
    echo   Seed failed. See error above.
    pause
    exit /b 1
)

REM --- Step 2: Start server in a new window ---
echo.
echo [3/4] Starting server...
start "FRCA Election Server" python -m waitress --host=0.0.0.0 --port=5000 app:app

REM Wait for server to be ready
echo   Waiting for server to start...
:wait_loop
timeout /t 1 /nobreak >nul
python -c "import requests; requests.get('http://localhost:5000/', timeout=2)" 2>nul
if errorlevel 1 goto wait_loop
echo   Server is up.

REM --- Step 3: Full election simulation ---
echo.
echo [4/4] Running full election simulation...
echo   Watch live: http://localhost:5000/display
echo.
start http://localhost:5000/display
python scripts/load_test.py --voters 95 --workers 8 --postal 5 --paper 8
pause
