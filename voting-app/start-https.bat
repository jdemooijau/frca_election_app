@echo off
cd /d "%~dp0"
echo ================================================
echo   FRCA Election App. HTTPS for chairman scanner
echo   https://localhost:5443/scanner
echo   (Camera access only works on HTTPS.)
echo   Run start.bat in a separate window for voters.
echo ================================================
python scripts\start_https.py
pause
