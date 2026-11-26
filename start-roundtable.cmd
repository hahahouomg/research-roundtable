@echo off
setlocal
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
    py -3 -X utf8 -B roundtable.py web %*
) else (
    python -X utf8 -B roundtable.py web %*
)
if errorlevel 1 pause
