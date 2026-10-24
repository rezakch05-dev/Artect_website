@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ========================================================
echo       Artect - Local Functional Test Launcher
echo ========================================================
echo.
echo This launcher is for LOCAL TESTING ONLY.
echo Do not expose this development server to the public internet.
echo.

set "PY_CMD=python"
where py >nul 2>&1
if not errorlevel 1 set "PY_CMD=py -3"

%PY_CMD% --version >nul 2>&1
if errorlevel 1 (
    echo Python 3 was not found.
    echo Install Python 3.10 or newer from https://www.python.org/downloads/windows/
    echo During installation, enable the option to add Python to PATH.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo [1/3] Creating an isolated Python environment...
    %PY_CMD% -m venv .venv
    if errorlevel 1 goto :fail
) else (
    echo [1/3] Using the existing virtual environment.
)

set "VENV_PY=%~dp0.venv\Scripts\python.exe"

echo.
echo [2/3] Installing / checking project dependencies...
"%VENV_PY%" -m pip install -r requirements.txt
if errorlevel 1 goto :fail

echo.
echo [3/3] Preparing local settings and starting Artect...
"%VENV_PY%" local_test_launcher.py
set "RUN_RESULT=%ERRORLEVEL%"
if not "%RUN_RESULT%"=="0" (
    echo.
    echo Artect exited with an error. Check the messages above.
)
echo.
echo The Artect local test server has stopped.
pause
exit /b %RUN_RESULT%

:fail
echo.
echo Setup failed. Check the error above and verify that Python and internet access are available for package installation.
pause
exit /b 1
