"""The wellbeing butler: break and posture nudges, water reminders, and the 20-20-20 rule.

Driven by keyboard and mouse activity, checked on the scheduler's 30-second tick:

- Break: after about an hour of continuous activity, a short spoken nudge to
  stand, stretch and sit up straight. Stepping away for five minutes counts as
  a break and resets the clock; ignored, he asks again half an hour later.
- Water: every 90 minutes at the laptop, "a glass of water, sir?". Saying
  "I drank water" (or the interface button) logs a glass, and resets the clock.
- Eyes: every 20 minutes of screen time, a quiet card on the interface (never
  spoken): look at something 20 feet away for 20 seconds.

Nothing fires while you are away, during a Pomodoro focus block, a game, or a
full-screen app (a film, a presentation, a game). "Pause the wellbeing
reminders for two hours" quiets them; intervals can be changed the same way.
Settings and the water count live in ~/.openjarvis/sebas/wellbeing.json.
"""

from __future__ import annotations

import ctypes
import random
import threading
import time
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable

from openjarvis.core.registry import ToolRegistry

from custom_tools._base import SebasTool, ToolError
from custom_tools.household import load, save

AWAY_RESETS_SECONDS = 5 * 60   # this long without input counts as a break
PRESENT_SECONDS = 2 * 60       # input within this long means you are at the laptop
DEFAULTS = {"break_minutes": 60, "water_minutes": 90, "eye_minutes": 20,
            "break": True, "water": True, "eye": True}

BREAK_LINES = [
    "Sir, you have been at it for {m} minutes. Might I suggest standing and stretching for a moment?",
    "{m} minutes without a pause, sir. Even Goku stops to eat. A short walk, perhaps?",
    "A gentle word, sir: shoulders back, and perhaps a stretch. {m} minutes is a long arc without a break.",
    "Sir, your posture has drifted into the shape of a question mark. A brief stretch would set it right.",
]
BREAK_AGAIN = [
    "Still at it, sir. I do insist on that stretch; a butler's duty extends to your spine.",
    "Sir, the break remains outstanding. Two minutes on your feet, I beg you.",
]
WATER_LINES = [
    "A glass of water, sir? Hydration is the foundation of every training arc.",
    "Sir, it has been a while since your last glass of water. Shall I note one when you have had it?",
    "Water, sir. Even the Survey Corps keep their canteens full.",
]
EYE_LINE = "Look at something about twenty feet away for twenty seconds, sir. Your eyes will thank you."


@dataclass
class Nudge:
    kind: str     # "break" | "water" | "eye"
    line: str
    spoken: bool  # eye cues are shown, never spoken


def fullscreen_app_running() -> bool:
    """A film, presentation or game in full screen (Windows' own 'busy' states)."""
    state = ctypes.c_int(0)
    try:
        if ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state)) != 0:
            return False
    except (AttributeError, OSError):
        return False
    return state.value in (2, 3, 4)  # QUNS_BUSY, QUNS_RUNNING_D3D_FULL_SCREEN, QUNS_PRESENTATION_MODE


_gaming = False


def set_gaming(on: bool) -> None:
    """The interface reports when the Games Room or a study panel is open."""
    global _gaming
    _gaming = bool(on)


def _settings_store() -> dict[str, Any]:
    try:
        data = load("wellbeing")
    except ToolError:
        data = {}
    return data if isinstance(data, dict) else {}


_lock = threading.Lock()


def settings() -> dict[str, Any]:
    return {**DEFAULTS, **_settings_store().get("settings", {})}


def water_today() -> int:
    return int(_settings_store().get("water", {}).get(date.today().isoformat(), 0))


def log_water(glasses: int = 1) -> int:
    with _lock:
        data = _settings_store()
        water = data.setdefault("water", {})
        today = date.today().isoformat()
        water[today] = max(0, int(water.get(today, 0)) + glasses)
        for old in sorted(water)[:-30]:
            del water[old]
        save("wellbeing", data)
    WELLBEING.last_water = time.monotonic()
    return water[today]


def update_settings(**changes: Any) -> dict[str, Any]:
    with _lock:
        data = _settings_store()
        data["settings"] = {**data.get("settings", {}), **changes}
        save("wellbeing", data)
    return settings()


class Wellbeing:
    """The nudge logic, separate from Windows so it can be tested with a fake clock."""

    def __init__(self, idle: Callable[[], float], busy: Callable[[], bool]) -> None:
        self._idle, self._busy = idle, busy
        self.active_since: float | None = None   # start of the current unbroken stretch
        self.last_break_nudge = 0.0
        self.last_eye = 0.0
        self.last_water = time.monotonic()
        self.paused_until = 0.0

    def tick(self, now: float | None = None, conf: dict | None = None) -> list[Nudge]:
        now = time.monotonic() if now is None else now
        conf = conf or settings()
        idle = self._idle()
        if idle >= AWAY_RESETS_SECONDS:  # a real break: everything starts afresh
            self.active_since = None
            self.last_eye = 0.0
            return []
        if self.active_since is None:
            self.active_since = now - idle
            self.last_eye = now
            self.last_water = max(self.last_water, now - conf["water_minutes"] * 60 / 2)  # not straight away
        if idle > PRESENT_SECONDS or now < self.paused_until or self._busy():
            return []
        stretch = now - self.active_since
        out: list[Nudge] = []
        if conf["break"] and stretch >= conf["break_minutes"] * 60:
            first = self.last_break_nudge < self.active_since
            if first or now - self.last_break_nudge >= 30 * 60:
                self.last_break_nudge = now
                line = random.choice(BREAK_LINES if first else BREAK_AGAIN).format(m=round(stretch / 60))
                out.append(Nudge("break", line, True))
        if conf["water"] and now - self.last_water >= conf["water_minutes"] * 60 and not out:
            self.last_water = now  # asked; asked again after another interval
            out.append(Nudge("water", random.choice(WATER_LINES), True))
        if conf["eye"] and now - self.last_eye >= conf["eye_minutes"] * 60:
            self.last_eye = now
            if not out:  # one thing at a time
                out.append(Nudge("eye", EYE_LINE, False))
        return out

    def status(self, now: float | None = None) -> dict[str, Any]:
        now = time.monotonic() if now is None else now
        return {
            "active_minutes": round((now - self.active_since) / 60) if self.active_since else 0,
            "water_today": water_today(),
            "paused_minutes": max(0, round((self.paused_until - now) / 60)),
        }


def _idle() -> float:
    from sebas_scheduler import idle_seconds

    return idle_seconds()


def _busy() -> bool:
    from custom_tools.study import focus_active

    return _gaming or focus_active() or fullscreen_app_running()


WELLBEING = Wellbeing(_idle, _busy)


# --------------------------------------------------------------------------- tools
@ToolRegistry.register("log_water")
class LogWaterTool(SebasTool):
    name = "log_water"
    description = "Log glasses of water the user drank (default one). Also resets the water reminder."
    parameters = {"type": "object", "properties": {"glasses": {"type": "integer", "description": "How many glasses (default 1)."}}}

    def run(self, glasses: int = 1) -> str:
        total = log_water(max(1, min(int(glasses or 1), 10)))
        return f"Noted, sir: {total} glass{'es' if total != 1 else ''} of water today."


@ToolRegistry.register("wellbeing_status")
class WellbeingStatusTool(SebasTool):
    name = "wellbeing_status"
    description = "How long the user has been working without a break, water today, and the wellbeing reminder settings."

    def run(self) -> str:
        s, conf = WELLBEING.status(), settings()
        on = [f"{k} every {conf[k + '_minutes']} min" for k in ("break", "water", "eye") if conf[k]]
        return (f"Working for {s['active_minutes']} minutes without a break; {s['water_today']} glasses of water today. "
                f"Reminders: {', '.join(on) or 'all off'}" + (f"; paused for {s['paused_minutes']} more minutes." if s["paused_minutes"] else "."))


@ToolRegistry.register("wellbeing_settings")
class WellbeingSettingsTool(SebasTool):
    name = "wellbeing_settings"
    description = (
        "Change the wellbeing reminders: pause them all for a while, turn a kind on or off "
        "(break/posture, water, eye 20-20-20), or change how often each comes."
    )
    parameters = {
        "type": "object",
        "properties": {
            "pause_minutes": {"type": "integer", "description": "Quiet all reminders for this many minutes (0 resumes)."},
            "kind": {"type": "string", "enum": ["break", "water", "eye"], "description": "Which reminder to change."},
            "enabled": {"type": "boolean", "description": "Turn that reminder on or off."},
            "every_minutes": {"type": "integer", "description": "New interval for that reminder."},
        },
    }

    def run(self, pause_minutes: int | None = None, kind: str = "", enabled: bool | None = None,
            every_minutes: int | None = None) -> str:
        said = []
        if pause_minutes is not None:
            WELLBEING.paused_until = time.monotonic() + max(0, int(pause_minutes)) * 60
            said.append(f"reminders paused for {int(pause_minutes)} minutes" if pause_minutes else "reminders resumed")
        if kind:
            changes: dict[str, Any] = {}
            if enabled is not None:
                changes[kind] = bool(enabled)
            if every_minutes:
                changes[f"{kind}_minutes"] = max(5, min(int(every_minutes), 240))
            if changes:
                conf = update_settings(**changes)
                said.append(f"{kind} reminder {'on' if conf[kind] else 'off'}, every {conf[kind + '_minutes']} minutes")
        if not said:
            raise ToolError("Nothing to change: give a pause, or a reminder kind with on/off or an interval.")
        return "Very good, sir: " + "; ".join(said) + "."
