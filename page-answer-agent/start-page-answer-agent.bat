@echo off
setlocal

cd /d "%~dp0"

set "START_URL=%~1"
if "%START_URL%"=="" set "START_URL=https://www.google.com"

start "Page Answer Server" cmd /k python page_capture_server.py
start "Chrome Debug" powershell -ExecutionPolicy Bypass -File "%~dp0start-chrome-debug.ps1" "%START_URL%"
start "Page Answer Hotkey" cmd /k python page_capture_hotkey.py

echo.
echo Page Answer Agent started.
echo Browser URL: %START_URL%
echo Hotkey: Ctrl+Shift+Y
echo Capture output: page-answer-agent\captured_pages\latest-page-capture.json
echo Session state: page-answer-agent\agent_runs\sessions\latest.json
echo Run files: page-answer-agent\agent_runs\*.json
echo Agent logs: page-answer-agent\agent_logs\latest-direct.json and latest-detail.json
echo Mobile latest direct page: http://127.0.0.1:8010/mobile/latest
echo.
echo After the Chrome debug window opens, navigate to a problem page and press Ctrl+Shift+Y.
