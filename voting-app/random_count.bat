@echo off
cd /d "%~dp0"
python scripts\random_count.py --helpers 20 %*
pause
