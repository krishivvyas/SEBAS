"""The user's day, and the end of it.

my_day      "What did I do today?": one account of a day, gathered by code from
            what Sebas already keeps (no extra Gemini request): time at the
            screen and the top apps and sites, focus time per subject, tasks
            done and added, spending, water, journal entries, and what Sebas
            did (the action log). The evening check-in opens with it.
Bedtime     at the user's bedtime (SEBAS_BEDTIME, default 23:30; "bedtime at
            midnight", "no bedtime reminder"), if he is at the laptop: the music
            is paused and Sebas says, in one breath, what tomorrow holds. Once
            more half an hour later if he is still there. Nothing else.
"""

from __future__ import annotations

import os
from datetime import date, datetime, time as dtime, timedelta
from typing import Any

from openjarvis.core.registry import ToolRegistry

import sebas_actions
from custom_tools import household, screentime
from custom_tools._base import SebasTool, ToolError

_NOT_WORTH_TELLING = {"watch", "routine", "errand", "browse"}  # told in their own words elsewhere
_ACTION_WORDS = {
    "send_message": "sent a message", "delete_files": "cleared files away", "close_apps": "closed programs",
    "delegate_coding": "a coding job", "review_pr": "a pull request review", "type_text": "took dictation",
    "files.move": "moved files", "files.rename": "renamed a file", "files.zip": "zipped files",
    "add_routine": "set a standing order", "watch_for": "set a watch",
}


# --------------------------------------------------------------------------- my day

def _day_of(stamp: Any) -> str:
    return str(stamp or "")[:10]


def gather(day: date) -> dict[str, Any]:
    """Everything known about a day, as data."""
    iso = day.isoformat()
    from custom_tools import study, wellbeing

    try:
        agenda = household.load("agenda")
    except ToolError:
        agenda = []
    try:
        journal = [e for e in household.load("journal") if e.get("date") == iso]
    except ToolError:
        journal = []
    try:
        expenses = [e for e in household.load("expenses") if e.get("date") == iso]
    except ToolError:
        expenses = []
    focus = study._focus_log().get(iso, {})
    water = int(wellbeing._settings_store().get("water", {}).get(iso, 0))
    return {
        "date": iso,
        "screen": screentime.load_day(day),
        "focus": focus,
        "done": [t["task"] for t in agenda if isinstance(t.get("done"), str) and _day_of(t["done"]) == iso],
        "added": [t["task"] for t in agenda if _day_of(t.get("added")) == iso],
        "spent": sum(e.get("amount", 0) for e in expenses),
        "spent_on": sorted({e.get("category", "other") for e in expenses}),
        "water": water,
        "journal": journal,
        "actions": [a for a in sebas_actions.on_day(iso) if a.get("ok", True)],
    }


def describe_day(day: date) -> str:
    d = gather(day)
    when = "today" if day == date.today() else "yesterday" if day == date.today() - timedelta(days=1) else day.strftime("%A %d %B")
    lines = [f"Your day ({when}):"]
    screen = d["screen"]
    total = sum(screen["apps"].values())
    if total >= 60:
        apps = ", ".join(f"{k} {screentime.describe(v)}" for k, v in screentime.top(screen["apps"], 4))
        sites = ", ".join(f"{k} {screentime.describe(v)}" for k, v in screentime.top(screen["sites"], 3, ("New tab", "Other sites")))
        lines.append(f"- At the screen {screentime.describe(total)}, {screen['first']} to {screen['last']}; most in {apps}"
                     + (f"; websites: {sites}" if sites else "") + ".")
    if d["focus"]:
        minutes = sum(d["focus"].values())
        lines.append(f"- Focused study {screentime.describe(minutes * 60)}: "
                     + ", ".join(f"{s} {screentime.describe(m * 60)}" for s, m in sorted(d["focus"].items(), key=lambda kv: -kv[1])) + ".")
    if d["done"]:
        lines.append(f"- Done ({len(d['done'])}): {'; '.join(d['done'][:6])}.")
    if d["added"]:
        lines.append(f"- Added to the agenda: {'; '.join(d['added'][:5])}.")
    if d["spent"]:
        lines.append(f"- Spent ₹{d['spent']:,.0f} ({', '.join(d['spent_on'])}).")
    if d["water"]:
        lines.append(f"- Water: {d['water']} glass{'es' if d['water'] != 1 else ''}.")
    if d["journal"]:
        lines.append(f"- Journal: {len(d['journal'])} entr{'ies' if len(d['journal']) != 1 else 'y'}.")
    done_for_you: dict[str, int] = {}
    for a in d["actions"]:
        key = a.get("action", "")
        if key in _NOT_WORTH_TELLING or key.startswith("files.undo"):
            continue
        word = _ACTION_WORDS.get(key)
        if word:
            done_for_you[word] = done_for_you.get(word, 0) + 1
    if done_for_you:
        lines.append("- I " + ", ".join(f"{w}" + (f" ({n})" if n > 1 else "") for w, n in done_for_you.items()) + ".")
    if len(lines) == 1:
        return f"I have nothing recorded for {when} yet."
    return "\n".join(lines)


@ToolRegistry.register("my_day")
class MyDayTool(SebasTool):
    name = "my_day"
    description = (
        "What the user did on a day: time at the screen and top apps and websites, focused study per subject, "
        "tasks done and added, spending, water, journal entries, and what you did for him. For 'what did I do "
        "today?', 'how was my day?', 'what did I do yesterday?'. Summarise it in two or three spoken sentences."
    )
    parameters = {
        "type": "object",
        "properties": {"day": {"type": "string", "description": "today, yesterday, or YYYY-MM-DD. Default today."}},
    }

    def run(self, day: str = "today") -> str:
        screentime.flush()
        text = (day or "today").strip().lower()
        if text in ("", "today"):
            when = date.today()
        elif text == "yesterday":
            when = date.today() - timedelta(days=1)
        else:
            try:
                when = date.fromisoformat(text[:10])
            except ValueError as exc:
                raise ToolError("Give the day as today, yesterday or YYYY-MM-DD.") from exc
        return describe_day(when)


# --------------------------------------------------------------------------- bedtime

def _bedtime_store() -> dict[str, Any]:
    try:
        data = household.load("bedtime")
    except ToolError:
        data = {}
    return data if isinstance(data, dict) else {}


def bedtime() -> dtime | None:
    """The user's bedtime, or None if the reminder is off."""
    stored = _bedtime_store()
    if stored.get("off"):
        return None
    text = stored.get("time") or os.environ.get("SEBAS_BEDTIME", "").strip() or "23:30"
    if text.lower() in ("off", "no", "none"):
        return None
    try:
        return datetime.strptime(text, "%H:%M").time()
    except ValueError:
        return dtime(23, 30)


def night_of(now: datetime) -> str:
    """The evening a moment belongs to: 01:00 on Tuesday is still Monday night."""
    return (now - timedelta(hours=6)).date().isoformat()


def is_past_bedtime(now: datetime, at: dtime) -> bool:
    """From bedtime until 05:00 the next morning (bedtimes after midnight work too)."""
    shifted = (now - timedelta(hours=6)).time()          # 06:00 becomes 00:00, so the night is one span
    start = (datetime.combine(date.today(), at) - timedelta(hours=6)).time()
    return start <= shifted < dtime(23, 0)               # i.e. bedtime .. 05:00


def tomorrow_line(now: datetime) -> str:
    """One sentence on what the next day holds, built by code."""
    from custom_tools import study

    tomorrow = now.date() if now.hour < 6 else now.date() + timedelta(days=1)  # after midnight, "tomorrow" is today
    parts = []
    due = [t for t in household.open_tasks() if t.get("due") and datetime.fromisoformat(t["due"]).date() == tomorrow]
    if due:
        first = min(due, key=lambda t: t["due"])
        when = datetime.fromisoformat(first["due"])
        at = " at " + when.strftime("%I:%M %p").lstrip("0") if when.time() != dtime(0, 0) else ""
        parts.append(f"{first['task']} is due{at}" + (f", and {len(due) - 1} more" if len(due) > 1 else ""))
    for exam in study.upcoming_exams():
        days = (datetime.fromisoformat(exam["date"]).date() - tomorrow).days
        if days == 0:
            parts.append(f"your {exam['subject']} exam")
        elif 0 < days <= 2:
            parts.append(f"your {exam['subject']} exam is {days} day{'s' if days > 1 else ''} later")
    if not parts:
        return "Tomorrow's agenda is clear."
    return "Tomorrow: " + "; ".join(parts[:3]) + "."


@ToolRegistry.register("bedtime_settings")
class BedtimeSettingsTool(SebasTool):
    name = "bedtime_settings"
    description = (
        "The bedtime wind-down: at bedtime Sebas pauses the music and says what tomorrow holds, once more half an "
        "hour later if the user is still up. Set the time ('bedtime at midnight' = 00:00), switch it off or on, "
        "or report it."
    )
    parameters = {
        "type": "object",
        "properties": {
            "time": {"type": "string", "description": "24-hour HH:MM."},
            "enabled": {"type": "boolean", "description": "false to switch the reminder off, true to switch it on."},
        },
    }

    def run(self, time: str = "", enabled: bool | None = None) -> str:  # noqa: A002
        stored = _bedtime_store()
        if time:
            try:
                stored["time"] = datetime.strptime(time.strip(), "%H:%M").strftime("%H:%M")
            except ValueError as exc:
                raise ToolError("Give the bedtime as HH:MM, 24-hour.") from exc
            stored["off"] = False
        if enabled is not None:
            stored["off"] = not enabled
        if time or enabled is not None:
            household.save("bedtime", stored)
        at = bedtime()
        return f"The bedtime reminder is at {at.strftime('%H:%M')}." if at else "The bedtime reminder is off."
