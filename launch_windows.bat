@echo off
title Pitwall IQ
cd /d "%~dp0"

:: Open the dashboard in the default browser after a 2-second delay (server needs time to start)
start /B cmd /c "ping 127.0.0.1 -n 3 > nul && start http://localhost:5000"

:: Try the Python Launcher first (standard on Windows), fall back to python
where py >nul 2>&1
if %errorlevel% == 0 (
    py F1_lap_tracker.py
) else (
    python F1_lap_tracker.py
)

pause
