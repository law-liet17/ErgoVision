@echo off
REM Double-click to start ErgoVision. Keep this window open while you use the site.
cd /d "%~dp0"
title ErgoVision server

set PY=python
where python >nul 2>nul || set PY=py

echo Checking Python packages...
%PY% -c "import flask, flask_cors, cv2, mediapipe, numpy" >nul 2>nul || (
  echo Installing packages, first run only - this takes a few minutes...
  %PY% -m pip install -r requirements.txt
)

echo.
echo ErgoVision is starting. The browser opens in a few seconds.
echo Keep this window open. Close it to stop the server.
echo Server messages are saved to server.log in this folder.
echo.
start "" cmd /c "timeout /t 8 >nul & start http://127.0.0.1:5000/#/lab"
%PY% -u -m flask --app app run --host 127.0.0.1 --port 5000 > server.log 2>&1
echo.
echo The server stopped. Last lines of server.log:
powershell -NoProfile -Command "Get-Content server.log -Tail 25"
pause
