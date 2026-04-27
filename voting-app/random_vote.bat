@echo off
cd /d "%~dp0"
python scripts\random_vote.py %*
pause
