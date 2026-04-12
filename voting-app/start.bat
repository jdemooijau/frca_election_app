@echo off
cd /d "%~dp0"
echo ================================================
echo   FRCA Election App
echo   http://localhost:5000
echo   Admin: http://localhost:5000/admin
echo ================================================
start http://localhost:5000/admin
python -m waitress --host=0.0.0.0 --port=5000 app:app
pause
