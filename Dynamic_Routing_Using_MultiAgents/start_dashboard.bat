@echo off
cd /d "%~dp0"
title Dynamic Routing Using MultiAgents - Step 8 Mission Control
where py >nul 2>&1
if %errorlevel%==0 (
  py server.py
) else (
  python server.py
)
if errorlevel 1 (
  echo.
  echo Unable to start. Check Python installation or stop an older dashboard using port 8765.
  pause
)
