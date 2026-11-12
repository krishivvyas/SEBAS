"""The proactive butler: things Sebas does without being asked.

- Morning briefing, the first time you are at the laptop after SEBAS_BRIEFING_TIME.
- Evening check-in after SEBAS_EVENING_TIME: a short wrap-up, then he asks how
  your day went and saves your answer to the journal. On Sundays, a weekly recap.
- Deadline alerts for agenda items due within the hour.
- Calendar heads-up ten minutes before each Google Calendar event.
- System guardian: low battery, memory nearly exhausted, disk nearly full.
- Exam countdown: a word a week, three days and one day before each exam, and on the day.
- Wellbeing: break and posture nudges, water reminders, and 20-20-20 eye cues
  (custom_tools/wellbeing.py); spoken at the laptop only, never sent to Discord.
- Quiet butler: during a Pomodoro focus block, non-urgent alerts and the
  briefings wait; they are delivered together at the break.

Briefings and check-ins only start while you are actually at the laptop (input
in the last two minutes), and each happens at most once a day. SEBAS_PROACTIVE=off
disables all of it.
"""

from __future__ import annotations

import ctypes
import json
import logging
import os
import threading
import time
from datetime import datetime, time as dtime, timedelta
from typing import Callable

import psutil
from openjarvis.core.paths import get_data_dir

from sebas_events import emit

logger = logging.getLogger("sebas.scheduler")

_TICK_SECONDS = 30
_PRESENT_IDLE_SECONDS = 120
_CALENDAR_POLL_SECONDS = 300
_HEADS_UP_MINUTES = 10
_ANIME_POLL_SECONDS = 30 * 60
_EXAM_WARNINGS = {
    7: "Sir, your {s} exam is a week away. A pomodoro or two each day would serve you well.",
    3: "Sir, three days until your {s} exam. Shall we review the flashcards?",
    1: "Sir, your {s} exam is tomorrow. A light review, and an early night, I would suggest.",
    0: "Good luck in your {s} exam today, sir. You have prepared; trust the training arc.",
}

BRIEFING_PROMPT = (
    "[Scheduled morning briefing] Good morning. Please give me my morning briefing: "
    "use the morning_briefing tool, and include what is due on my agenda today."
)
EVENING_PROMPT = (
    "[Scheduled evening check-in] Give me a brief wrap-up of today: agenda items done "
    "and due tomorrow, and today's spending. Then ask me, in one sentence, how my day "
    "went. When I answer, save my answer with journal_add."
)
RECAP_PROMPT = (
    "[Scheduled weekly recap] It is Sunday evening. Recap my week in a few sentences: "
    "read my journal for the last 7 days, this week's spending, and what I completed. "
    "Then ask me how today went, and save my answer with journal_add."
)


def idle_seconds() -> float:
    """Seconds since the last keyboard or mouse input (Windows)."""

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

    info = LASTINPUTINFO(ctypes.sizeof(LASTINPUTINFO), 0)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        return 0.0
    return (ctypes.windll.kernel32.GetTickCount() - info.dwTime) / 1000.0


def _clock(name: str, default: str) -> dtime:
    try:
        return datetime.strptime(os.environ.get(name, "").strip() or default, "%H:%M").time()
    except ValueError:
        return datetime.strptime(default, "%H:%M").time()


class Scheduler:
    """Runs on its own thread. ``say`` speaks a ready-made line; ``converse``
    sends a prompt through Sebas's brain, speaks the reply (returning it) and,
    when ``expect_reply`` is set, listens for an answer without needing "Sebas".

    ``remote`` (the Discord bridge, optional) receives a copy of every alert and
    briefing; when the user is away from the laptop, alerts are not spoken and
    the evening check-in is held on Discord instead."""

    def __init__(self, say: Callable[[str], None], converse: Callable[[str, bool], str | None], remote=None) -> None:
        self._raw_say = say
        self._converse_local = converse
        self._remote = remote
        self._path = get_data_dir() / "sebas" / "scheduler.json"
        self._state = self._load()
        self._last_calendar_poll = 0.0
        self._last_anime_poll = 0.0
        self._ram_high_ticks = 0
        self._held: list[str] = []  # non-urgent alerts waiting for the end of a focus block
        self._held_lock = threading.Lock()
        from custom_tools import study

        study._held_releaser[:] = [self.release_held]

    # --- state ---------------------------------------------------------------
    def _load(self) -> dict:
        try:
            return json.loads(self._path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._state, indent=1), "utf-8")

    def _once(self, key: str, value: str) -> bool:
        """True the first time ``key`` is set to ``value``; records it."""
        if self._state.get(key) == value:
            return False
        self._state[key] = value
        self._save()
        return True

    def _seen(self, bucket: str, item: str, keep: int = 200) -> bool:
        items = self._state.setdefault(bucket, [])
        if item in items:
            return True
        items.append(item)
        del items[:-keep]
        self._save()
        return False

    # --- delivery -------------------------------------------------------------
    def _say(self, text: str, urgent: bool = False) -> None:
        from custom_tools.study import focus_active

        if not urgent and focus_active():
            with self._held_lock:
                if text not in self._held:
                    self._held.append(text)
            return
        sent = self._remote is not None and self._remote.alert(text)
        if not (sent and self._remote.user_away()):
            import sebas_calls  # mid-call it would be spoken into the call: it waits

            sebas_calls.DESK.hold_or_say(self._raw_say, text)

    def release_held(self) -> None:
        """At the break: everything that waited during focus, in one go."""
        with self._held_lock:
            held, self._held = self._held, []
        if held:
            self._say("While you were focusing, sir: " + " ".join(held), urgent=True)

    def _converse(self, prompt: str, expect_reply: bool, title: str = "Briefing") -> None:
        reply = self._converse_local(prompt, expect_reply)
        if reply and self._remote is not None:
            self._remote.briefing(title, reply)

    def _remote_ready(self) -> bool:
        return self._remote is not None and self._remote.ready.is_set()

    # --- loop ----------------------------------------------------------------
    def start(self) -> None:
        if os.environ.get("SEBAS_PROACTIVE", "on").strip().lower() in ("off", "0", "false", "no"):
            logger.info("Proactive features are off (SEBAS_PROACTIVE).")
            return
        threading.Thread(target=self._run, name="sebas-scheduler", daemon=True).start()

    def _run(self) -> None:
        time.sleep(20)  # let Sebas finish starting up first
        while True:
            for job in (self._deadlines, self._calendar, self._guardian, self._routines, self._anime, self._exams, self._wellbeing):
                try:
                    job(datetime.now())
                except Exception:
                    logger.exception("Scheduled job %s failed", job.__name__)
            time.sleep(_TICK_SECONDS)

    # --- jobs ------------------------------------------------------------------
    def _routines(self, now: datetime) -> None:
        from custom_tools.study import focus_active

        import sebas_calls

        if focus_active() or sebas_calls.DESK.active():  # the briefing keeps until the break
            return
        today = now.date().isoformat()
        present = idle_seconds() <= _PRESENT_IDLE_SECONDS
        evening_due = now.time() >= _clock("SEBAS_EVENING_TIME", "21:30")
        if not present:
            # Away: the evening check-in can still happen on Discord. The morning
            # briefing waits until the user sits down at the laptop.
            if evening_due and self._remote_ready() and self._once("evening", today):
                prompt = RECAP_PROMPT if now.weekday() == 6 else EVENING_PROMPT
                self._remote.converse_remote(prompt, "Weekly recap" if now.weekday() == 6 else "Evening check-in")
            return
        if now.time() >= _clock("SEBAS_BRIEFING_TIME", "07:00") and now.hour < 12 and self._once("briefing", today):
            self._converse(BRIEFING_PROMPT, False, "Morning briefing")
        elif evening_due and self._once("evening", today):
            weekly = now.weekday() == 6
            self._converse(RECAP_PROMPT if weekly else EVENING_PROMPT, True, "Weekly recap" if weekly else "Evening check-in")

    def _deadlines(self, now: datetime) -> None:
        from custom_tools.household import describe_due, open_tasks

        for task in open_tasks():
            due = task.get("due")
            if not due:
                continue
            when = datetime.fromisoformat(due)
            if when.time() == dtime(0, 0):  # a date without a time: mention it that morning
                if when.date() == now.date() and now.hour >= 9 and not self._seen("deadline_alerts", task["id"]):
                    self._say(f"A gentle reminder, sir: {task['task']} is due today.")
            elif now <= when <= now + timedelta(hours=1) and not self._seen("deadline_alerts", task["id"]):
                minutes = max(1, round((when - now).total_seconds() / 60))
                self._say(f"Sir, {task['task']} is due in {minutes} minutes.", urgent=True)

    def _calendar(self, now: datetime) -> None:
        if time.monotonic() - self._last_calendar_poll < _CALENDAR_POLL_SECONDS:
            return
        self._last_calendar_poll = time.monotonic()
        from custom_tools.morning_briefing import events_between

        local_now = now.astimezone()
        for event_id, start, title in events_between(local_now, local_now + timedelta(minutes=_HEADS_UP_MINUTES + 6)):
            minutes = round((start - local_now).total_seconds() / 60)
            if 0 <= minutes <= _HEADS_UP_MINUTES + 5 and not self._seen("calendar_alerts", f"{event_id}@{start.isoformat()}"):
                self._say(f"Sir, {title} begins in {minutes} minutes." if minutes else f"Sir, {title} is beginning now.", urgent=True)

    def _anime(self, now: datetime) -> None:
        """New episodes, chapters and volumes on the user's AniList, every 30 minutes."""
        if not (os.environ.get("ANILIST_TOKEN") or os.environ.get("ANILIST_USER")):
            return
        if time.monotonic() - self._last_anime_poll < _ANIME_POLL_SECONDS:
            return
        self._last_anime_poll = time.monotonic()
        from custom_tools.anime import radar_changes

        news = [n for n in radar_changes() if not n.startswith("(first check")]
        if news:
            self._say("Sir, a little news from your watchlist: " + "; ".join(news[:4]) + ".")

    def _wellbeing(self, now: datetime) -> None:
        from custom_tools.wellbeing import WELLBEING

        for nudge in WELLBEING.tick():
            emit("wellbeing", nudge=nudge.kind, line=nudge.line)  # the card on the interface
            if nudge.spoken:
                self._raw_say(nudge.line)  # at the laptop only: no Discord, nothing held for later

    def _exams(self, now: datetime) -> None:
        """A word a week, three days and one day before each exam, and on the day."""
        if now.hour < 8:
            return
        from custom_tools.study import days_until, upcoming_exams

        for exam in upcoming_exams():
            days = days_until(exam)
            if days in _EXAM_WARNINGS and not self._seen("exam_alerts", f"{exam['id']}@{days}"):
                self._say(_EXAM_WARNINGS[days].format(s=exam["subject"]))

    def _guardian(self, now: datetime) -> None:
        battery = psutil.sensors_battery()
        if battery is not None:
            if battery.power_plugged:
                self._state.pop("battery_warned", None)
            else:
                for level in (10, 20):
                    if battery.percent <= level and self._state.get("battery_warned", 101) > level:
                        self._state["battery_warned"] = level
                        self._save()
                        self._say(f"Sir, the battery has fallen to {battery.percent:.0f} percent. "
                                  + ("Please connect the charger soon." if level == 20 else "The laptop will shut down shortly without power."),
                                  urgent=True)
                        break
        ram = psutil.virtual_memory().percent
        self._ram_high_ticks = self._ram_high_ticks + 1 if ram >= 92 else 0
        if self._ram_high_ticks >= 4 and self._once("ram_warned", now.strftime("%Y-%m-%d %H") + str(now.minute // 30)):
            heavy = sorted(psutil.process_iter(["name", "memory_info"]),
                           key=lambda p: p.info["memory_info"].rss if p.info["memory_info"] else 0, reverse=True)
            top = next((p.info["name"].removesuffix(".exe") for p in heavy if p.info["name"]), "an application")
            self._say(f"Sir, memory is nearly exhausted at {ram:.0f} percent; {top} is using the most. "
                      "Closing something heavy would keep things running smoothly.")
        disk = psutil.disk_usage(os.environ.get("SystemDrive", "C:") + "\\")
        if disk.free < 10 * 2**30 and self._once("disk_warned", now.date().isoformat()):
            self._say(f"Sir, only {disk.free / 2**30:.0f} gigabytes remain free on the system drive.")


def evening_greeting(now: datetime | None = None) -> str:
    """A time-appropriate farewell for when Sebas is sent to sleep."""
    hour = (now or datetime.now()).hour
    if hour >= 21 or hour < 4:
        return "Good night, sir. I shall retire for now. Rest well."
    if hour < 12:
        return "Very good, sir. I shall withdraw for now. Do call upon me should you need anything."
    return "As you wish, sir. I shall take my leave. Ring whenever you have need of me."
