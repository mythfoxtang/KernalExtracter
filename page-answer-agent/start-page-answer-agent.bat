@echo off
setlocal

cd /d "%~dp0"

set "START_URL=%~1"
if "%START_URL%"=="" set "START_URL=https://www.google.com"

start "Page Answer Server" cmd /k python page_capture_server.py
start "Chrome Debug" powershell -ExecutionPolicy Bypass -File "%~dp0start-chrome-debug.ps1" "%START_URL%"
start "Page Answer Hotkey" cmd /k python page_capture_hotkey.py
start "Speech Answer Hotkey" cmd /k python speech_capture_hotkey.py

echo.
echo Page Answer Agent started.
echo Browser URL: %START_URL%
echo Page hotkey: Ctrl+Shift+Y
echo Speech hotkey: Ctrl+Shift+U
echo Capture output: page-answer-agent\captured_pages\latest-page-capture.json
echo Audio output: page-answer-agent\audio_captures\latest-speech.wav
echo Session state: page-answer-agent\agent_runs\sessions\latest.json
echo Run files: page-answer-agent\agent_runs\*.json
echo Agent logs: page-answer-agent\agent_logs\latest-direct.json and latest-detail.json
echo Mobile latest direct page: http://127.0.0.1:8010/mobile/latest
echo.
echo After the Chrome debug window opens, navigate to a problem page and press Ctrl+Shift+Y.
echo To ask by voice, press Ctrl+Shift+U once to start recording and press it again to stop.
