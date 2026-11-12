"""Run Sebas: "Sebas" -> speech recognition -> orchestrator -> speech output.

    python run_sebas.py --ui        Desktop interface (voice and typing)
    python run_sebas.py --ui --no-voice   Desktop interface, typing only
    python run_sebas.py             Voice mode in the console: "Sebas, rise" or "Sebas, <request>"
    python run_sebas.py --text      Type instead of speaking; prints the replies
    python run_sebas.py --mic-test  Measure microphone levels and suggest a threshold
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from sebas_bootstrap import load_env

load_env()  # Must run before anything imports openjarvis.

from sebas_brain import Brain  # noqa: E402  (Gemini key 1 -> key 2 -> local model)
from sebas_events import emit  # noqa: E402

logger = logging.getLogger("sebas")

_FAILURE_REPLY = (
    "I regret to report that the request could not be completed. "
    "The details are in the console, should you wish to review them."
)


_SUMMON_REPLY = "At your service."


def handle_egg(text: str, mouth=None) -> bool:
    """An anime Easter egg: show its effect and say its line. True if one fired."""
    import sebas_eggs

    egg = sebas_eggs.check(text)
    if egg is None:
        return False
    sebas_eggs.trigger(egg)
    print(f"Sebas: {egg.line}", flush=True)
    emit("transcript", role="sebas", text=egg.line)
    if mouth is not None:
        try:
            mouth.speak(egg.line)
        except Exception:
            logger.exception("Speech output failed")
    return True


def handle_game(text: str, mouth=None) -> bool:
    """"Sebas, let's play pong": open the Games Room. True if it was a game request."""
    import sebas_games

    found = sebas_games.check(text)
    if found is None:
        return False
    name, line = found
    sebas_games.open_game(name)
    print(f"Sebas: {line}", flush=True)
    emit("transcript", role="sebas", text=line)
    if mouth is not None and name is None:  # each game greets you itself
        try:
            mouth.speak(line)
        except Exception:
            logger.exception("Speech output failed")
    return True


class SebasSleep(Exception):
    """Raised when the user sends Sebas to sleep."""


def say_farewell(mouth=None) -> str:
    """Speak and show Sebas's goodbye. Returns the line he said."""
    from sebas_scheduler import evening_greeting

    farewell = evening_greeting()
    print(f"Sebas: {farewell}", flush=True)
    emit("transcript", role="sebas", text=farewell)
    if mouth is not None:
        try:
            mouth.speak(farewell)
        except Exception:
            logger.exception("Speech output failed")
    emit("sleep")
    return farewell


def run_voice_turn(listener, ears, mouth, brain, follow_up_seconds: float = 0.0) -> None:
    """Handle one conversation, from "Sebas" until the user stops talking.

    "Sebas, rise" is answered and followed by a request; "Sebas, <request>"
    is handled directly. With ``follow_up_seconds`` above zero, Sebas keeps
    listening after each reply, so follow-ups need no "Sebas".
    """
    from voice_pipeline.name_listener import is_sleep_request, is_summon, request_text, split_address

    print('Listening for "Sebas"...', flush=True)
    emit("state", state="idle")
    pcm, remainder = listener.wait()
    if pcm is None:  # the UI's bell: go straight to listening
        mouth.chime()
        emit("state", state="listening")
        text = ears.listen(wait_seconds=max(follow_up_seconds, 6.0))
    elif is_summon(remainder):
        emit("gesture", name="bow")
        mouth.speak(_SUMMON_REPLY)
        emit("transcript", role="sebas", text=_SUMMON_REPLY)
        mouth.chime()
        emit("state", state="listening")
        text = ears.listen(wait_seconds=max(follow_up_seconds, 6.0))
    else:
        emit("state", state="thinking")
        # The quick model only decides whether Sebas was addressed; the
        # accurate model re-reads the same audio for the request itself.
        accurate = split_address(ears.transcribe(pcm))
        text = request_text(accurate if accurate else remainder)

    import sebas_calls

    while text:
        print(f"You:   {text}", flush=True)
        emit("transcript", role="user", text=text)
        def ask(question: str) -> str:  # "Krishiv or Hermit, sir?"
            emit("transcript", role="sebas", text=question)
            mouth.speak(question)
            mouth.chime()
            emit("state", state="listening")
            answer = ears.listen(wait_seconds=5)
            emit("transcript", role="user", text=answer or "(no answer)")
            return answer

        if sebas_calls.handle(text, ask):  # call commands; during a call, nothing else
            break
        if is_sleep_request(text):
            say_farewell(mouth)
            raise SebasSleep
        if not handle_egg(text, mouth) and not handle_game(text, mouth):
            emit("state", state="thinking")
            try:
                reply = brain.ask(text)
            except Exception:
                logger.exception("The request failed")
                reply = _FAILURE_REPLY
            print(f"Sebas: {reply}", flush=True)
            emit("transcript", role="sebas", text=reply)
            try:
                mouth.speak(reply)
            except Exception:
                logger.exception("Speech output failed")
        if follow_up_seconds <= 0:
            break
        mouth.chime()  # still listening
        emit("state", state="listening")
        text = ears.listen(wait_seconds=follow_up_seconds)
    emit("state", state="idle")


def start_discord(brain, ears=None, mouth=None):
    """Start the Discord bridge if it is configured in .env; returns it or None.
    ``ears`` and ``mouth`` are shared with it for voice notes and the voice channel."""
    from sebas_discord import DiscordBridge, discord_configured
    from voice_pipeline.name_listener import is_sleep_request

    if not discord_configured():
        return None
    bridge = DiscordBridge(brain, is_sleep_request)
    bridge.attach_voice(ears, mouth)
    bridge.start()
    print("Discord: connecting...", flush=True)
    return bridge


def start_calls(ears=None, mouth=None) -> None:
    """Sebas on calls: shares the speech models, finds VB-Cable, and starts Ctrl+Alt+C."""
    import sebas_calls

    try:
        sebas_calls.DESK.attach(ears, mouth)
        sebas_calls.start_hotkey()
    except Exception:
        logger.exception("Call support unavailable")


def load_voice():
    """Load the speech models. Returns (listener, ears, mouth)."""
    from voice_pipeline.ears import Ears
    from voice_pipeline.mouth import Mouth
    from voice_pipeline.name_listener import NameListener

    print("Loading voice models...", flush=True)
    threshold = int(os.environ.get("SEBAS_SILENCE_THRESHOLD") or 500)
    quick_ears = Ears(os.environ.get("SEBAS_NAME_MODEL") or "tiny.en", threshold)
    quick_ears.load()
    ears = Ears(os.environ.get("SEBAS_WHISPER_MODEL") or "small.en", threshold)
    ears.load()
    listener = NameListener(quick_ears, threshold, confirm=ears)
    mouth = Mouth(voice=os.environ.get("SEBAS_VOICE") or "bm_george")
    mouth.load()
    return listener, ears, mouth


def follow_up_seconds() -> float:
    return float(os.environ.get("SEBAS_FOLLOW_UP_SECONDS") or 8)


def run_voice(brain) -> None:
    listener, ears, mouth = load_voice()
    from custom_tools import notes

    notes.set_reader(mouth.speak)

    from custom_tools.laptop import set_announcer

    def announce(text: str) -> None:
        print(f"\nSebas: {text}", flush=True)
        mouth.speak(text)

    set_announcer(announce)

    def converse(prompt: str, expect_reply: bool) -> str:
        reply = brain.ask(prompt)
        print(f"Sebas: {reply}", flush=True)
        mouth.speak(reply)
        if expect_reply:  # listen for the answer without needing "Sebas"
            listener.push_to_talk()
        return reply

    from sebas_scheduler import Scheduler

    Scheduler(announce, converse, start_discord(brain, ears, mouth)).start()
    start_calls(ears, mouth)
    print('Ready. Say "Sebas, rise", or "Sebas" followed by a request. "Sebas, sleep" to finish.', flush=True)
    try:
        while True:
            run_voice_turn(listener, ears, mouth, brain, follow_up_seconds())
    except SebasSleep:
        return


def run_text(brain) -> None:
    from custom_tools.laptop import set_announcer

    from sebas_scheduler import Scheduler
    from voice_pipeline.name_listener import is_sleep_request

    def announce(text: str) -> None:
        print(f"\nSebas: {text}\nYou:   ", end="", flush=True)

    set_announcer(announce)
    def converse(prompt: str, _expect_reply: bool) -> str:
        reply = brain.ask(prompt)
        announce(reply)
        return reply

    Scheduler(announce, converse, start_discord(brain)).start()
    start_calls()
    while True:
        text = input("You:   ").strip()
        if not text:
            continue
        if is_sleep_request(text):
            say_farewell()
            return
        if handle_egg(text):
            continue
        try:
            print(f"Sebas: {brain.ask(text)}")
        except Exception:
            logger.exception("The request failed")
            print(f"Sebas: {_FAILURE_REPLY}")


def mic_test(seconds: int = 8) -> None:
    import numpy as np
    import sounddevice as sd

    rate = 16000
    print(f"Recording for {seconds} seconds. Stay quiet for 3, then say: \"Sebas, what is the weather today?\"", flush=True)
    audio = sd.rec(seconds * rate, samplerate=rate, channels=1, dtype="int16")
    sd.wait()
    samples = audio[:, 0].astype(np.float64)
    frames = samples[: samples.size - samples.size % 1024].reshape(-1, 1024)
    levels = np.sqrt(np.mean(frames**2, axis=1))
    noise = float(np.median(levels[: levels.size // 2]))
    speech = float(levels[levels.size // 2 :].max())
    print(f"Background level: {noise:.0f}")
    print(f"Speech peak:      {speech:.0f}")
    current = os.environ.get("SEBAS_SILENCE_THRESHOLD", "").strip()
    if speech < noise * 2:
        print("Speech is barely louder than the background. Check the microphone.")
    else:
        suggested = (noise + speech) / 2
        print(f"Suggested .env setting: SEBAS_SILENCE_THRESHOLD={suggested:.0f}"
              + (f" (currently {current})" if current else ""))

    # What Sebas would make of it: the quick model decides whether he was addressed,
    # the accurate one reads the request (the same two steps as in voice mode).
    from voice_pipeline.ears import Ears
    from voice_pipeline.name_listener import request_text, split_address

    spoken = audio[rate * 2 :, 0]
    print("Transcribing what you said...", flush=True)
    import wave
    from pathlib import Path

    from voice_pipeline.name_listener import sounds_like_name

    saved = Path.home() / ".openjarvis" / "sebas" / "logs" / "mic-test.wav"
    saved.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(saved), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate); w.writeframes(audio.tobytes())  # noqa: E702
    print(f"(Recording saved to {saved})")

    threshold = int(float(current or 500))
    quick = Ears(os.environ.get("SEBAS_NAME_MODEL") or "tiny.en", threshold)
    accurate = Ears(os.environ.get("SEBAS_WHISPER_MODEL") or "small.en", threshold)
    opening = spoken[: rate * 3]  # voice mode checks the first 3 seconds for the name
    heard = quick.transcribe(opening)
    address = split_address(heard)
    print(f"  quick model    heard {heard!r}")
    if address is None and sounds_like_name(heard):
        second = accurate.transcribe(opening)
        address = split_address(second)
        print(f"  near-miss, so the accurate model re-checked: {second!r}")
    if address is None:
        print("  -> NOT addressed to Sebas: he would not wake. Try again a little closer or clearer.")
        return
    print(f"  -> addressed to Sebas. Request (accurate model): {request_text(split_address(accurate.transcribe(spoken)) or address)!r}")


def setup_logging() -> str:
    """Warnings to the console, as before; and a rotating log file (three files of
    1 MB, in ~/.openjarvis/sebas/logs) that also keeps Sebas's own INFO lines, so a
    problem can be looked into after the window has closed. Returns its path."""
    from logging.handlers import RotatingFileHandler
    from pathlib import Path

    folder = Path.home() / ".openjarvis" / "sebas" / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "sebas.log"
    console = logging.StreamHandler()
    console.setLevel(logging.WARNING)
    handlers: list[logging.Handler] = [console]
    try:
        log_file = RotatingFileHandler(path, maxBytes=1_000_000, backupCount=3, encoding="utf-8", delay=True)
        log_file.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
        handlers.append(log_file)
    except OSError:
        pass  # a log file is a convenience, never a reason not to start
    logging.basicConfig(level=logging.WARNING, handlers=handlers, force=True)
    logging.getLogger("sebas").setLevel(logging.INFO)  # only Sebas's INFO, not every library's
    for handler in handlers:
        handler.addFilter(_known_harmless)
    return str(path)


# Warnings seen in every session that need no action (live session, 2026-11-08):
# Discord voice libraries Sebas does not use, OpenJarvis's optional Rust extension
# (Sebas keeps his own memory files), Kokoro splitting a word unusually, and the
# genai SDK noting a tool call alongside the text. Kept out of the console and log
# so that real problems stand out.
_HARMLESS = (
    ("discord.client", "voice will NOT be supported"),
    ("openjarvis.security", "openjarvis_rust"),
    ("openjarvis.system.builder", "openjarvis_rust"),
    ("phonemizer", "words count mismatch"),
    ("google_genai.types", "non-text parts in the response"),
)


def _known_harmless(record: logging.LogRecord) -> bool:
    message = record.getMessage()
    return not any(record.name == name and text in message for name, text in _HARMLESS)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Sebas voice assistant.")
    parser.add_argument("--ui", action="store_true", help="open the desktop interface")
    parser.add_argument(
        "--no-voice", action="store_true", help="with --ui: typing only, no microphone"
    )
    parser.add_argument("--text", action="store_true", help="type instead of speaking")
    parser.add_argument(
        "--mic-test", action="store_true", help="measure microphone levels and exit"
    )
    parser.add_argument(
        "--selftest", action="store_true", help="run Sebas's offline tests and exit"
    )
    args = parser.parse_args()

    if args.selftest:  # before the log file: simulated failures do not belong in it
        import unittest

        logging.basicConfig(level=logging.ERROR)
        suite = unittest.defaultTestLoader.discover(os.path.join(os.path.dirname(__file__), "sebas_tests"))
        return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1
    setup_logging()
    if args.mic_test:
        mic_test()
        return 0
    if args.ui:
        from ui_app import run_ui

        return run_ui(voice=not args.no_voice)
    try:
        brain = Brain()
    except RuntimeError as exc:
        print(f"Sebas cannot start: {exc}")
        print("Add GEMINI_API_KEY to .env, or install a local model with Ollama.")
        return 1
    print(f"Thinking with {brain.description}.", flush=True)
    try:
        run_text(brain) if args.text else run_voice(brain)
    except (KeyboardInterrupt, EOFError):
        print("\nVery good, sir. I shall retire for now.")
    finally:
        brain.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
