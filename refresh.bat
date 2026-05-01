@echo off
REM refresh.bat — rebuild screenshots, PDF previews, and PPTX decks
REM
REM Steps:
REM   1. Capture 23 screenshots via Playwright (uses its own DB backup).
REM   2. Seed a fresh demo, start waitress, capture the two PDF previews,
REM      stop the server, restore the original DB.
REM   3. Rebuild the two PPTX decks from the captured PNGs.

setlocal EnableDelayedExpansion
cd /d "%~dp0"

set DB=voting-app\data\frca_election.db
set SECRET=voting-app\data\.secret_key
set BACKUP=voting-app\data\frca_election.db.refresh_backup
set SERVER_TITLE=FRCA-REFRESH-SERVER

REM ----------------------------------------------------------------------
echo.
echo === Step 1/3: capture screenshots ===
python capture_screenshots.py
if errorlevel 1 (
    echo ABORT: screenshot capture failed.
    exit /b 1
)

REM ----------------------------------------------------------------------
echo.
echo === Step 2/3: capture PDF previews ===

if exist "%DB%" (
    copy /y "%DB%" "%BACKUP%" >nul
    del "%DB%"
    echo   Backed up DB to %BACKUP%
)
if exist "%SECRET%" del "%SECRET%"

echo   Seeding demo election...
pushd voting-app
python scripts\seed_demo.py
if errorlevel 1 (
    echo ABORT: seed_demo failed.
    popd
    goto :restore
)

REM Set admin password the PDF scripts expect (council2026)
python -c "import os, sys; sys.path.insert(0, '.'); from app import app, set_setting; ctx=app.app_context(); ctx.push(); set_setting('admin_password', 'council2026'); ctx.pop(); print('  Admin password set to council2026')"
popd

echo   Starting server in background window (%SERVER_TITLE%)...
start "%SERVER_TITLE%" /MIN cmd /c "cd voting-app && python -m waitress --host=127.0.0.1 --port=5000 app:app"

REM Give waitress a moment to bind
timeout /t 4 /nobreak >nul

echo   Capturing PDFs...
python capture_pdfs.py
python capture_code_slips.py

echo   Stopping server...
taskkill /fi "WINDOWTITLE eq %SERVER_TITLE%*" /f >nul 2>&1
REM Fallback: kill anything listening on :5000
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5000.*LISTENING" 2^>nul') do (
    taskkill /pid %%a /f >nul 2>&1
)

:restore
echo   Restoring original DB...
if exist "%DB%" del "%DB%"
if exist "%SECRET%" del "%SECRET%"
if exist "%BACKUP%" (
    move /y "%BACKUP%" "%DB%" >nul
    echo   Restored.
)

REM ----------------------------------------------------------------------
echo.
echo === Step 3/3: rebuild PowerPoint decks ===
where node >nul 2>nul
if errorlevel 1 (
    echo   node is not on PATH; skipping PPTX rebuild.
) else (
    node create_pptx.js
    node create_proposal_pptx.js
)

echo.
echo === Done ===
echo Outputs:
echo   screenshots\*.png ^(and 23_code_slips.png, 24_paper_ballot.png^)
echo   voting-app\docs\FRCA_Election_App_Training.pptx
echo   voting-app\docs\FRCA_Election_App_Proposal.pptx
endlocal
