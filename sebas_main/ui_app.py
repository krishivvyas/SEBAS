"""Sebas's desktop interface: a frameless pywebview window around ui/index.html.

Python -> page: every sebas_events.emit() is forwarded to window.Sebas.receive().
Page -> Python: the page calls the methods of ``Api`` (window.pywebview.api.*).
The voice loop and typed requests run on background threads, so the window
stays responsive and "Sebas, rise" keeps working while it is open.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import threading
import time
from pathlib import Path
from typing import Any

import psutil
import webview

import sebas_events
from sebas_events import emit

logger = logging.getLogger("sebas.ui")
UI_DIR = Path(__file__).resolve().parent / "ui"
_MIC_INTERVAL = 1 / 15  # seconds between microphone level updates


class Bridge:
    """Delivers events to the page, holding them until the page is ready."""

    def __init__(self) -> None:
        self.window: Any = None
        self._ready = False
        self._pending: list[str] = []
        self._lock = threading.Lock()
        self._last_mic = 0.0

    def __call__(self, kind: str, data: dict[str, Any]) -> None:
        if kind == "mic":
            now = time.monotonic()
            if now - self._last_mic < _MIC_INTERVAL:
                return
            self._last_mic = now
        script = f"window.Sebas && window.Sebas.receive({json.dumps({'type': kind, **data})})"
        with self._lock:
            if not self._ready:
                if kind not in ("mic", "speech"):
                    self._pending = (self._pending + [script])[-100:]
                return
        self.window.evaluate_js(script)

    def mark_ready(self) -> None:
        with self._lock:
            self._ready, pending, self._pending = True, self._pending, []
        for script in pending:
            self.window.evaluate_js(script)


def vitals() -> dict[str, Any]:
    battery = psutil.sensors_battery()
    return {
        "cpu": psutil.cpu_percent(interval=None),
        "memory": psutil.virtual_memory().percent,
        "battery": battery.percent if battery else None,
        "charging": bool(battery and battery.power_plugged),
    }


class SebasApp:
    def __init__(self, voice: bool) -> None:
        self.voice = voice
        self.bridge = Bridge()
        self.brain = None
        self.listener = self.ears = self.mouth = None
        self._requests: queue.Queue[str] = queue.Queue()

    # --- started by webview.start() once the window exists -------------------
    def start(self) -> None:
        emit("state", state="thinking")
        from sebas_brain import Brain

        try:
            self.brain = Brain()
        except RuntimeError as exc:
            emit("notice", text=f"Sebas cannot think yet: {exc}")
            emit("state", state="idle")
            return
        emit("mode", mode=self.brain.mode, model=self.brain.short_description)

        try:
            if self.voice:
                import run_sebas

                self.listener, self.ears, self.mouth = run_sebas.load_voice()
            else:  # typing only: he still speaks, but needs no speech recognition
                from voice_pipeline.mouth import Mouth

                self.mouth = Mouth(voice=os.environ.get("SEBAS_VOICE") or "bm_george")
                self.mouth.load()
        except Exception as exc:
            logger.exception("Voice unavailable")
            emit("notice", text=f"Voice is unavailable ({type(exc).__name__}); typing still works.")

        from custom_tools import notes
        from custom_tools.laptop import set_announcer

        if self.mouth is not None:
            notes.set_reader(self.mouth.speak)

        def announce(text: str) -> None:
            emit("transcript", role="sebas", text=text)
            self._speak(text)

        set_announcer(announce)
        from sebas_scheduler import Scheduler

        import run_sebas as _rs

        self.discord = _rs.start_discord(self.brain, self.ears, self.mouth)
        _rs.start_calls(self.ears, self.mouth)
        Scheduler(announce, self._converse, self.discord).start()
        threading.Thread(target=self._serve_typed_requests, daemon=True).start()
        if self.voice and self.listener is not None:
            threading.Thread(target=self._voice_loop, daemon=True).start()
            emit("notice", text='Listening. Say "Sebas, rise", or ring the bell.')
        else:
            emit("notice", text="Typing mode. Ring for Sebas below.")
        emit("state", state="idle")

    def _voice_loop(self) -> None:
        import run_sebas

        while True:
            try:
                run_sebas.run_voice_turn(
                    self.listener, self.ears, self.mouth, self.brain, run_sebas.follow_up_seconds()
                )
            except run_sebas.SebasSleep:
                self._retire()
                return
            except Exception as exc:
                logger.exception("Voice loop error")
                emit("notice", text=f"The microphone stopped ({type(exc).__name__}). Retrying shortly.")
                emit("state", state="idle")
                time.sleep(3)

    def _serve_typed_requests(self) -> None:
        import run_sebas

        while True:
            text = self._requests.get()
            emit("transcript", role="user", text=text)
            import sebas_calls

            if sebas_calls.handle(text):
                continue
            from voice_pipeline.name_listener import is_sleep_request

            if is_sleep_request(text):
                run_sebas.say_farewell(self.mouth)
                self._retire()
                return
            if run_sebas.handle_egg(text, self.mouth) or run_sebas.handle_game(text, self.mouth):
                continue
            emit("state", state="thinking")
            try:
                reply = self.brain.ask(text)
            except Exception:
                logger.exception("The request failed")
                reply = run_sebas._FAILURE_REPLY
            emit("transcript", role="sebas", text=reply)
            self._speak(reply)

    def _converse(self, prompt: str, expect_reply: bool) -> str:
        """A scheduled prompt (briefing, check-in): Sebas speaks first."""
        emit("state", state="thinking")
        reply = self.brain.ask(prompt)
        emit("transcript", role="sebas", text=reply)
        self._speak(reply)
        if expect_reply and self.listener is not None and self.voice:
            self.listener.push_to_talk()  # take the answer without needing "Sebas"
        return reply

    def _retire(self) -> None:
        """After the farewell: let the page play its closing animation, then close."""
        time.sleep(2.2)
        self.bridge.window.destroy()

    def _speak(self, text: str) -> None:
        if self.mouth is None:
            emit("state", state="idle")
            return
        try:
            self.mouth.speak(text)
        except Exception:
            logger.exception("Speech output failed")
            emit("state", state="idle")

    # --- called from the page -------------------------------------------------
    def submit(self, text: str) -> None:
        text = (text or "").strip()
        if text:
            self._requests.put(text)

    def push_to_talk(self) -> bool:
        if self.listener is None or not self.voice:
            emit("notice", text="The microphone is not available in this mode.")
            return False
        self.listener.push_to_talk()
        return True

    def snapshot(self) -> dict[str, Any]:
        from custom_tools import household, laptop, memory, study, wellbeing
        from custom_tools.household import describe_due

        with laptop._reminders_lock:
            reminders = [
                {"due": due.timestamp(), "text": text}
                for due, text, _ in sorted(laptop._reminders.values(), key=lambda r: r[0])
            ]
        brain = self.brain
        return {
            "mode": brain.mode if brain else "starting",
            "model": brain.short_description if brain else "",
            "memory": memory.read_facts(),
            "reminders": reminders,
            "vitals": vitals(),
            "agenda": [{"task": t["task"], "due": describe_due(t.get("due")), "overdue": "overdue" in describe_due(t.get("due"))}
                       for t in household.open_tasks()[:6]],
            "spent_month": household.expense_totals("month")[0],
            "spent_today": household.expense_totals("today")[0],
            "voice": bool(self.voice and self.listener is not None),
            "study": study.snapshot(),
            "wellbeing": wellbeing.WELLBEING.status(),
            "call": _call_status(),
        }


def _call_status() -> dict[str, Any]:
    import sebas_calls

    desk = sebas_calls.DESK
    return {"state": desk.state, "route": desk.route, "name": sebas_calls.master_name(),
            "names": sebas_calls.master_names()}


class Api:
    """Methods the page may call. Private attributes are not exposed to it."""

    def __init__(self, app: SebasApp) -> None:
        self._app = app

    def ready(self) -> dict[str, Any]:
        self._app.bridge.mark_ready()
        return self._app.snapshot()

    def snapshot(self) -> dict[str, Any]:
        return self._app.snapshot()

    def send_text(self, text: str) -> None:
        self._app.submit(text)

    def push_to_talk(self) -> bool:
        return self._app.push_to_talk()

    def say(self, line: str) -> None:
        """A scripted game line: spoken in Sebas's voice, no Gemini involved."""
        mouth = self._app.mouth
        if mouth is None or not line:
            return

        def talk() -> None:
            try:
                mouth.speak_if_free(str(line)[:300])
            except Exception:
                logger.exception("Speech output failed")

        threading.Thread(target=talk, daemon=True).start()

    # --- study mode: flashcards and quizzes run in the page, from saved sets ---
    def study_deck(self, subject: str) -> dict[str, Any]:
        from custom_tools import study

        return study.deck_for_review(subject)

    def study_grade(self, subject: str, card_id: str, verdict: str) -> None:
        from custom_tools import study

        if verdict in ("again", "good", "easy"):
            study.grade(subject, card_id, verdict)

    def study_quiz(self, subject: str) -> dict[str, Any]:
        from custom_tools import study

        return study.quiz_for(subject)

    def study_quiz_done(self, subject: str, score: int, total: int) -> None:
        from custom_tools import study

        study.record_quiz(subject, int(score), int(total))

    # --- calls: the panel's buttons ---------------------------------------------
    def call_take(self, brief: str = "", name: str = "") -> str:
        import sebas_calls

        return sebas_calls.DESK.take(str(brief or "")[:300], str(name or "")[:40])

    def call_back(self) -> str:
        import sebas_calls

        return sebas_calls.DESK.step_back()

    def call_captions(self, on: bool) -> str:
        import sebas_calls

        return sebas_calls.DESK.captions(bool(on))

    def call_relay(self, message: str) -> str:
        import sebas_calls

        message = str(message or "").strip()[:300]
        return sebas_calls.DESK.relay(message) if message else ""

    def log_water(self) -> int:
        from custom_tools import wellbeing

        return wellbeing.log_water(1)

    def set_gaming(self, on: bool) -> None:
        from custom_tools import wellbeing

        wellbeing.set_gaming(on)  # no spoken nudges mid-game

    def study_stop(self) -> None:
        from custom_tools import study

        study.StopPomodoroTool().run_now()

    def minimize(self) -> None:
        self._app.bridge.window.minimize()

    def close(self) -> None:
        self._app.bridge.window.destroy()


def run_ui(voice: bool = True) -> int:
    app = SebasApp(voice=voice)
    sebas_events.set_sink(app.bridge)
    window = webview.create_window(
        "Sebas",
        url=str(UI_DIR / "index.html"),
        js_api=Api(app),
        width=1320,
        height=840,
        min_size=(1100, 720),
        frameless=True,
        easy_drag=False,
        background_color="#05070d",
    )
    app.bridge.window = window
    webview.start(app.start)
    sebas_events.set_sink(None)
    if app.brain is not None:
        app.brain.close()
    return 0
