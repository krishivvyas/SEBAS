@echo off
setlocal
rem Starts Sebas from any location.
rem   run.bat              Voice mode: say "Sebas, rise" or "Sebas, <request>"
rem   run.bat --text       Type instead of speaking
rem   run.bat --mic-test   Measure the microphone and suggest SEBAS_SILENCE_THRESHOLD

set "REPO=%~dp0sebas_main"
set "PYTHON=%REPO%\.venv\Scripts\python.exe"

if not exist "%PYTHON%" (
    echo Virtual environment not found at "%PYTHON%".
    echo See "Installation" in README.md.
    pause
    exit /b 1
)

if /i not "%~1"=="--mic-test" if not exist "%REPO%\.env" (
    echo No .env file yet. Copy sebas_main\.env.template to sebas_main\.env and add your keys.
    pause
    exit /b 1
)

cd /d "%REPO%"
"%PYTHON%" run_sebas.py %*

set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" pause
exit /b %EXIT_CODE%
