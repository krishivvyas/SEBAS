@echo off
setlocal
rem Starts Sebas from any location.
rem   run.bat              Voice mode: say "Sebas, rise" or "Sebas, <request>"
rem   run.bat --text       Type instead of speaking
rem   run.bat --mic-test   Measure the microphone and suggest SEBAS_SILENCE_THRESHOLD
rem Uses Claude when sebas_main\.env has ANTHROPIC_API_KEY and the internet is up;
rem otherwise a local model through Ollama.

set "REPO=%~dp0sebas_main"
set "PYTHON=%REPO%\.venv\Scripts\python.exe"

if not exist "%PYTHON%" (
    echo Virtual environment not found at "%PYTHON%".
    echo See "Installation" in README.md.
    pause
    exit /b 1
)

if not exist "%REPO%\.env" (
    echo Note: no sebas_main\.env yet, so Sebas will use a local model and tools that need keys are off.
    echo       Copy sebas_main\.env.template to sebas_main\.env to add keys.
    echo.
)

cd /d "%REPO%"
"%PYTHON%" run_sebas.py %*

set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" pause
exit /b %EXIT_CODE%
