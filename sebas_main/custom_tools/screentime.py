"""The screen-time diary: which programs, and which websites, the user spends time in.

A background thread looks at the window in front every few seconds while the
user is at the laptop (input in the last few minutes, or a film or game in full
screen) and adds the time to that day's totals. For browsers it records the
site's NAME only ("YouTube", "GitHub"), worked out from the window title; page
and video titles are never stored. Everything stays in
~/.openjarvis/sebas/screentime/<date>.json; days older than 60 are deleted.

Limits are the user's own ("limit YouTube to an hour a day"): Sebas mentions it
once a day when one is passed, and never otherwise.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

import psutil
from openjarvis.core.paths import get_data_dir
from openjarvis.core.registry import ToolRegistry

from custom_tools._base import SebasTool, ToolError

logger = logging.getLogger("sebas.screentime")

SAMPLE_SECONDS = 5
SAVE_SECONDS = 60
AWAY_SECONDS = 300      # no input for longer than this: not at the laptop (unless a film is full screen)
KEEP_DAYS = 60

BROWSERS = {"msedge": "Edge", "chrome": "Chrome", "firefox": "Firefox", "brave": "Brave", "opera": "Opera",
            "vivaldi": "Vivaldi", "arc": "Arc"}
APP_NAMES = {
    "code": "VS Code", "antigravity ide": "Antigravity", "whatsapp.root": "WhatsApp", "whatsapp": "WhatsApp",
    "spotify": "Spotify", "explorer": "File Explorer", "windowsterminal": "Terminal", "winword": "Word",
    "excel": "Excel", "powerpnt": "PowerPoint", "notepad": "Notepad", "discord": "Discord", "steam": "Steam",
    "steamwebhelper": "Steam", "obs64": "OBS", "vlc": "VLC", "pycharm64": "PyCharm", "acrobat": "Acrobat",
    "teams": "Teams", "ms-teams": "Teams", "zoom": "Zoom", "telegram": "Telegram", "phoneexperiencehost": "Phone Link",
}
# Sites recognised anywhere in a browser's title, so "Funny cat - YouTube" counts as YouTube.
KNOWN_SITES = [
    ("youtube", "YouTube"), ("github", "GitHub"), ("gmail", "Gmail"), ("inbox", "Gmail"),
    ("whatsapp", "WhatsApp Web"), ("chatgpt", "ChatGPT"), ("gemini", "Gemini"), ("claude", "Claude"),
    ("instagram", "Instagram"), ("netflix", "Netflix"), ("prime video", "Prime Video"), ("crunchyroll", "Crunchyroll"),
    ("hotstar", "Hotstar"), ("reddit", "Reddit"), ("stack overflow", "Stack Overflow"), ("linkedin", "LinkedIn"),
    ("/ x", "X"), ("twitter", "X"), ("facebook", "Facebook"), ("google docs", "Google Docs"), ("docs.google", "Google Docs"),
    ("google sheets", "Google Sheets"), ("google drive", "Google Drive"), ("google search", "Google"),
    ("anilist", "AniList"), ("myanimelist", "MyAnimeList"), ("wikipedia", "Wikipedia"), ("amazon", "Amazon"),
    ("flipkart", "Flipkart"), ("spotify", "Spotify Web"), ("twitch", "Twitch"), ("leetcode", "LeetCode"),
    ("geeksforgeeks", "GeeksforGeeks"), ("vercel", "Vercel"), ("notion", "Notion"), ("canva", "Canva"),
    ("figma", "Figma"), ("discord", "Discord Web"), ("duckduckgo", "DuckDuckGo"),
]
_BROWSER_SUFFIX = re.compile(r"\s*(and \d+ more pages?)?\s*(-\s*(Personal|Work|Profile \d+|[^-]{1,30}))?\s*-\s*"
                             r"(Microsoft​? Edge|Google Chrome|Mozilla Firefox|Brave|Opera|Vivaldi)\s*$", re.I)

_lock = threading.Lock()
_today: dict[str, Any] | None = None
_dirty = False
_started = False
_last_save = 0.0


# --------------------------------------------------------------------------- what is in front

def app_name(process: str) -> str:
    key = (process or "").lower().removesuffix(".exe")
    if key in BROWSERS:
        return BROWSERS[key]
    return APP_NAMES.get(key, key.replace("_", " ").title() if key else "")


def site_name(title: str) -> str:
    """The website a browser window shows, by name only: never the page title."""
    clean = _BROWSER_SUFFIX.sub("", title or "").strip()
    low = clean.lower()
    if not clean or low in ("new tab", "start page", "new private tab"):
        return "New tab"
    for needle, name in KNOWN_SITES:
        if needle in low:
            return name
    # GitHub's pull request and issue pages: "Fix add by me · Pull Request #12 · owner/repo"
    # ...and its repository pages when signed in: "owner/repo: description", or just "owner/repo"
    if (re.search(r"·\s*(pull request|issue|discussion|commit)\b", low) or re.search(r"\s·\s[\w.-]+/[\w.-]+$", clean)
            or re.match(r"^[\w.-]+/[\w.-]+(:\s|$)", clean)):
        return "GitHub"
    # "Some page title - Site Name" / "| Site Name": the last short segment names the site
    parts = [p.strip() for p in re.split(r"\s[-|·—–]\s", clean) if p.strip()]
    if len(parts) >= 2 and 2 <= len(parts[-1]) <= 28 and len(parts[-1].split()) <= 4:
        return parts[-1]
    return "Other sites"


def _foreground() -> tuple[str, str] | None:
    """(app, site or '') for the window in front, or None if nothing is."""
    from custom_tools import desk

    hwnd = desk.foreground()
    if not hwnd:
        return None
    try:
        pid = desk._pid(hwnd)
        if pid == os.getpid():
            return "Sebas", ""
        process = psutil.Process(pid).name()
    except (psutil.Error, OSError):
        return None
    name = app_name(process)
    if not name or name.lower() in ("lockapp", "searchhost", "shellexperiencehost", "startmenuexperiencehost"):
        return None
    site = site_name(desk._title(hwnd)) if name in BROWSERS.values() else ""
    return name, site


def _present() -> bool:
    from custom_tools.wellbeing import fullscreen_app_running
    from sebas_scheduler import idle_seconds

    return idle_seconds() < AWAY_SECONDS or fullscreen_app_running()


# --------------------------------------------------------------------------- storage

def _folder() -> Path:
    return get_data_dir() / "sebas" / "screentime"


def _empty(day: str) -> dict[str, Any]:
    return {"date": day, "apps": {}, "sites": {}, "first": None, "last": None, "warned": []}


def load_day(day: date | str) -> dict[str, Any]:
    day = day if isinstance(day, str) else day.isoformat()
    with _lock:
        if _today is not None and _today["date"] == day:
            return json.loads(json.dumps(_today))
    try:
        data = json.loads((_folder() / f"{day}.json").read_text("utf-8"))
        return {**_empty(day), **data}
    except (OSError, json.JSONDecodeError):
        return _empty(day)


def _save_locked() -> None:
    global _dirty, _last_save
    if _today is None:
        return
    folder = _folder()
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / f"{_today['date']}.tmp"
    tmp.write_text(json.dumps(_today, ensure_ascii=False), "utf-8")
    tmp.replace(folder / f"{_today['date']}.json")
    _dirty, _last_save = False, time.monotonic()
    cutoff = (date.today() - timedelta(days=KEEP_DAYS)).isoformat()
    for old in folder.glob("*.json"):
        if old.stem < cutoff and old.stem[:4].isdigit():
            try:
                old.unlink()
            except OSError:
                pass


def record(app: str, site: str, seconds: float, now: datetime | None = None) -> None:
    """Add ``seconds`` of use. Module-level so tests can drive it without a desktop."""
    global _today, _dirty
    now = now or datetime.now()
    day = now.date().isoformat()
    with _lock:
        if _today is None or _today["date"] != day:
            if _today is not None and _dirty:
                _save_locked()
            _today = _load_file(day)
        _today["apps"][app] = round(_today["apps"].get(app, 0) + seconds, 1)
        if site:
            _today["sites"][site] = round(_today["sites"].get(site, 0) + seconds, 1)
        stamp = now.strftime("%H:%M")
        _today["first"] = _today["first"] or stamp
        _today["last"] = stamp
        _dirty = True
        if time.monotonic() - _last_save >= SAVE_SECONDS:
            _save_locked()


def _load_file(day: str) -> dict[str, Any]:
    try:
        data = json.loads((_folder() / f"{day}.json").read_text("utf-8"))
        return {**_empty(day), **data}
    except (OSError, json.JSONDecodeError):
        return _empty(day)


def flush() -> None:
    with _lock:
        if _dirty:
            _save_locked()


# --------------------------------------------------------------------------- limits

def _limits_path() -> Path:
    return _folder() / "limits.json"


def limits() -> dict[str, float]:
    try:
        data = json.loads(_limits_path().read_text("utf-8"))
        return {str(k): float(v) for k, v in data.items()}
    except (OSError, json.JSONDecodeError, ValueError, AttributeError):
        return {}


def _save_limits(data: dict[str, float]) -> None:
    _limits_path().parent.mkdir(parents=True, exist_ok=True)
    _limits_path().write_text(json.dumps(data, indent=1), "utf-8")


def _match(target: str, names: dict[str, float]) -> tuple[str, float]:
    """The app or site a limit refers to, case-insensitively, and its seconds today."""
    want = target.strip().lower()
    for name, seconds in names.items():
        if name.lower() == want:
            return name, seconds
    for name, seconds in names.items():
        if want in name.lower() or name.lower() in want:
            return name, seconds
    return target, 0.0


def usage_of(target: str, day: dict[str, Any] | None = None) -> float:
    """Seconds today in an app or on a site (whichever the name matches; sites first)."""
    day = day or load_day(date.today())
    name, seconds = _match(target, day["sites"])
    if seconds:
        return seconds
    return _match(target, day["apps"])[1]


def check_limits(now: datetime | None = None) -> list[str]:
    """Sentences for limits passed today, each said once a day."""
    global _dirty
    now = now or datetime.now()
    found = limits()
    if not found:
        return []
    messages = []
    with _lock:
        if _today is None or _today["date"] != now.date().isoformat():
            return []
        day = _today
        for target, minutes in found.items():
            if target.lower() in day["warned"]:
                continue
            used = usage_of(target, day) / 60
            if used >= minutes:
                day["warned"].append(target.lower())
                _dirty = True
                messages.append(f"Sir, you have spent {describe(used * 60)} on {target} today, past the "
                                f"{describe(minutes * 60)} you set. I mention it only because you asked me to.")
    return messages


# --------------------------------------------------------------------------- the sampler

def _loop(on_limit: Callable[[str], None] | None) -> None:
    last = time.monotonic()
    while True:
        time.sleep(SAMPLE_SECONDS)
        now = time.monotonic()
        gap, last = min(now - last, SAMPLE_SECONDS * 3), now  # a sleeping laptop does not count
        try:
            if _present():
                front = _foreground()
                if front:
                    record(front[0], front[1], gap)
            for message in check_limits():
                if on_limit:
                    on_limit(message)
        except Exception:
            logger.debug("Screen-time sample failed", exc_info=True)


def start(on_limit: Callable[[str], None] | None = None) -> None:
    """Start the sampler once (from run_sebas). ``on_limit`` speaks a passed limit."""
    global _started
    if _started or os.environ.get("SEBAS_SCREENTIME", "on").strip().lower() in ("off", "0", "false", "no"):
        return
    _started = True
    threading.Thread(target=_loop, args=(on_limit,), name="sebas-screentime", daemon=True).start()


# --------------------------------------------------------------------------- reporting

def describe(seconds: float) -> str:
    minutes = int(round(seconds / 60))
    if minutes < 1:
        return "under a minute"
    if minutes < 60:
        return f"{minutes} min"
    return f"{minutes // 60} h {minutes % 60:02d} min" if minutes % 60 else f"{minutes // 60} h"


def top(names: dict[str, float], n: int = 5, skip: tuple[str, ...] = ()) -> list[tuple[str, float]]:
    return sorted(((k, v) for k, v in names.items() if k not in skip and v >= 60), key=lambda kv: -kv[1])[:n]


def summary(day: date | None = None) -> str:
    data = load_day(day or date.today())
    total = sum(data["apps"].values())
    if total < 60:
        return "No screen time recorded" + (" today." if not day or day == date.today() else f" on {data['date']}.")
    apps = ", ".join(f"{k} {describe(v)}" for k, v in top(data["apps"], 6))
    sites = ", ".join(f"{k} {describe(v)}" for k, v in top(data["sites"], 5, ("New tab", "Other sites")))
    text = f"{describe(total)} at the screen ({data['first']} to {data['last']}). Apps: {apps}."
    return text + (f" Websites: {sites}." if sites else "")


def week_summary() -> str:
    apps: dict[str, float] = {}
    sites: dict[str, float] = {}
    days = 0
    for back in range(7):
        data = load_day(date.today() - timedelta(days=back))
        if sum(data["apps"].values()) >= 60:
            days += 1
        for k, v in data["apps"].items():
            apps[k] = apps.get(k, 0) + v
        for k, v in data["sites"].items():
            sites[k] = sites.get(k, 0) + v
    total = sum(apps.values())
    if total < 60:
        return "No screen time recorded in the last seven days."
    return (f"Last 7 days: {describe(total)} at the screen over {days} days (about {describe(total / max(days, 1))} a day). "
            f"Apps: {', '.join(f'{k} {describe(v)}' for k, v in top(apps, 6))}. "
            f"Websites: {', '.join(f'{k} {describe(v)}' for k, v in top(sites, 5, ('New tab', 'Other sites'))) or 'none'}.")


@ToolRegistry.register("screen_time")
class ScreenTimeTool(SebasTool):
    name = "screen_time"
    description = (
        "The user's screen-time diary (programs, and websites by name). action 'report': today, yesterday or the "
        "week; with 'target' (an app or site such as YouTube) just that one. 'set_limit': a daily limit in "
        "minutes for an app or site, mentioned once when passed. 'remove_limit', 'limits': manage them."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["report", "set_limit", "remove_limit", "limits"]},
            "period": {"type": "string", "enum": ["today", "yesterday", "week"]},
            "target": {"type": "string", "description": "An app or website name, e.g. YouTube, VS Code."},
            "minutes": {"type": "number", "description": "For set_limit: minutes per day."},
        },
        "required": ["action"],
    }

    def run(self, action: str, period: str = "today", target: str = "", minutes: float | None = None) -> str:
        flush()
        if action == "report":
            if target:
                if period == "week":
                    total = sum(usage_of(target, load_day(date.today() - timedelta(days=b))) for b in range(7))
                    return f"{target}: {describe(total)} over the last seven days."
                day = date.today() - timedelta(days=1 if period == "yesterday" else 0)
                return f"{target}: {describe(usage_of(target, load_day(day)))} {period}."
            if period == "week":
                return week_summary()
            return summary(date.today() - timedelta(days=1)) if period == "yesterday" else summary()
        if action == "limits":
            found = limits()
            if not found:
                return "No screen-time limits are set."
            return "\n".join(f"- {k}: {describe(v * 60)} a day (today: {describe(usage_of(k))})" for k, v in found.items())
        target = " ".join((target or "").split())
        if not target:
            raise ToolError("Which app or website?")
        found = limits()
        if action == "set_limit":
            if not minutes or minutes <= 0 or minutes > 24 * 60:
                raise ToolError("Give the limit in minutes per day.")
            found = {k: v for k, v in found.items() if k.lower() != target.lower()}
            found[target] = float(minutes)
            _save_limits(found)
            return f"Limit set: {target}, {describe(minutes * 60)} a day. Today so far: {describe(usage_of(target))}."
        if action == "remove_limit":
            kept = {k: v for k, v in found.items() if k.lower() != target.lower()}
            if len(kept) == len(found):
                raise ToolError(f"There is no limit for {target}.")
            _save_limits(kept)
            return f"The limit on {target} is removed."
        raise ToolError("Action must be report, set_limit, remove_limit or limits.")
