@echo off
setlocal
rem Starts Sebas from any location.
rem   run.bat              Desktop interface (voice and typing)
rem   run.bat --no-voice   Desktop interface, typing only
rem   run.bat --console    Voice mode in this console window, no interface
rem   run.bat --text       Typing in this console window, no interface
rem   run.bat --mic-test   Measure the microphone and suggest SEBAS_SILENCE_THRESHOLD
rem   run.bat --selftest   Offline tests (no keys, microphone or quota needed)
rem Log file: %USERPROFILE%\.openjarvis\sebas\logs\sebas.log
rem Say "Sebas, sleep" (or type it) and he says goodbye and closes.
rem Say "Sebas, let's play pong" (or press Games) for the built-in games: no AI, no quota.
rem Study mode: "Sebas, start a pomodoro on DBMS", "make flashcards for DBMS", "quiz me on DBMS".
rem Wellbeing: stretch, water and 20-20-20 eye nudges; "pause the reminders for an hour".
rem Standing orders: "Sebas, tell me when the deploy finishes" / "...when the download finishes" / "watch Elden Ring on Steam";
rem   "every weekday at 9, open my workspace"; "what are you watching for?"; "cancel the Steam watch".
rem Errands: "Sebas, set up my week: add these tasks, log this expense, then read me my agenda" (a background checklist);
rem   "save that as my evening wrap-up"; "run my evening wrap-up". Big errands late in the day think on the local model.
rem Your day: "what did I do today?"; "how long was I on YouTube?"; "limit YouTube to an hour a day"; bedtime at SEBAS_BEDTIME (23:30).
rem Search: "what did I note about normalisation?" (notes, Documents, journal, flashcards). Reviews: "have Claude review my open PR in sebas".
rem Messages: "Sebas, tell Rahul on WhatsApp I'll be late"; "email Professor Mehta that..."; "post ... in #general".
rem   He reads back the recipient and the words and sends only on your yes. Names come from [contacts] in laptop.toml.
rem Browser: "Sebas, go to the college portal and tell me if the timetable is out" (works in a new tab of your own Edge).
rem   Once: edge://extensions, Developer mode, Load unpacked, pick sebas_main\browser_extension. Submitting anything asks first.
rem Coding: "Sebas, have Claude fix the failing test in the sebas project" (a new branch, never committed; needs Claude Code);
rem   "how is Claude getting on?"; "stop Claude"; "discard Claude's changes".
rem Files: "find my DBMS assignment"; "move the PDFs from Downloads to Documents/College"; "undo that"; deleting asks first (Recycle Bin).
rem Desk: "type this: ..."; "put Chrome on the left and Code on the right"; "close everything except Spotify" (asks first); "press Ctrl+S".
rem If DISCORD_BOT_TOKEN is set, the Discord bot starts too (and stops when Sebas closes).
rem   On Discord: send a voice note in #sebas for a spoken reply; join "Sebas Voice" and he speaks there.
rem On a call (WhatsApp, Instagram, Meet...): answer it, then "Sebas, take this call" or Ctrl+Alt+C; "step back" to return.
rem   So callers hear him: install VB-Cable once, choose "CABLE Output" as the call app's mic, and say "Sebas, test call audio".
rem Thinks with Gemini (GEMINI_API_KEY, then GEMINI_API_KEY_2 in sebas_main\.env): Flash
rem first, then the lighter Flash-Lite models; when those are spent too, or offline,
rem with a local model through Ollama.

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
if "%~1"=="" (
    "%PYTHON%" run_sebas.py --ui
) else if /i "%~1"=="--no-voice" (
    "%PYTHON%" run_sebas.py --ui --no-voice
) else if /i "%~1"=="--console" (
    "%PYTHON%" run_sebas.py
) else (
    "%PYTHON%" run_sebas.py %*
)

set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" pause
exit /b %EXIT_CODE%
