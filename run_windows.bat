@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto START
where py >nul 2>&1
if %errorlevel%==0 (
    py -m venv .venv
) else (
    python -m venv .venv
)
if errorlevel 1 (
    echo Failed to create Python virtual environment. Install Python 3.10+.
    pause
    exit /b 1
)
:START
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo Failed to install dependencies. Check your internet connection.
    pause
    exit /b 1
)
echo.
echo Tin's Takoyaki is starting...
echo On this PC: http://127.0.0.1:5000
echo Press Ctrl+C to stop the server.
echo.
".venv\Scripts\python.exe" app.py
pause
