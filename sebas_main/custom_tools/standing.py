"""Standing orders: things Sebas keeps doing or watching after the conversation ends.

Routines   "every weekday at 9, open my workspace and read me my pull requests".
           The request is kept as words and put to Sebas at that time, as if the
           user had just asked it; so a routine costs Gemini requests each run.
Watchers   "tell me when the deploy finishes". Plain code checks the condition
           (no Gemini), tells the user once when it is met, and then retires.

    deploy       a Vercel deployment finishes (ready, failed or cancelled)
    ci           the checks on a GitHub pull request, or a repo's latest workflow run, finish
    steam_price  a Steam game falls to a price, or goes on sale
    page         a web page changes, or starts to contain a phrase
    download     the downloads now in progress finish
    file         a new file appears in a folder
    battery      the battery reaches a level
    app_closed   a program closes
    cpu_quiet    the processor goes quiet (a render or build has finished)

Both are kept in ~/.openjarvis/sebas/standing.json and survive a restart. The
scheduler calls ``due_routines`` and ``poll`` every tick.
"""

from __future__ import annotations

import fnmatch
import hashlib
import html
import os
import re
import threading
import time
import uuid
from datetime import datetime, time as dtime, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable

import httpx
import psutil
from openjarvis.core.registry import ToolRegistry

import sebas_actions
from custom_tools._base import BROWSER_USER_AGENT, SebasTool, ToolError, http_get_json, require_env
from custom_tools.household import load, save

_FILE = "standing"
_lock = threading.RLock()
_ROUTINE_GRACE = timedelta(hours=3)  # a routine missed by more than this waits for its next day
_DAY_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_PARTIAL = (".crdownload", ".part", ".download", ".opdownload", ".tmp")


# --------------------------------------------------------------------------- routines

def parse_days(text: str) -> list[int]:
    """'daily', 'weekdays', 'weekends' or day names ('mon, wed and friday') -> weekday numbers."""
    low = (text or "daily").lower()
    if any(w in low for w in ("daily", "every day", "everyday", "all")):
        return list(range(7))
    days = set()
    if "weekday" in low:
        days.update(range(5))
    if "weekend" in low:
        days.update((5, 6))
    days.update(n for n, name in enumerate(_DAY_NAMES) if re.search(rf"\b{name}", low))
    if not days:
        raise ToolError(f"Could not read the days '{text}'. Use daily, weekdays, weekends, or day names.")
    return sorted(days)


def describe_days(days: list[int]) -> str:
    if len(days) == 7:
        return "every day"
    if days == [0, 1, 2, 3, 4]:
        return "weekdays"
    if days == [5, 6]:
        return "weekends"
    return ", ".join(_DAY_NAMES[d].capitalize() for d in days)


def _parse_clock(text: str) -> dtime:
    text = (text or "").strip().lower().replace(".", ":")
    for fmt in ("%H:%M", "%I:%M %p", "%I:%M%p", "%I %p", "%I%p", "%H"):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    raise ToolError(f"Could not read the time '{text}'. Use 24-hour HH:MM, such as 09:00 or 17:30.")


def due_routines(now: datetime) -> list[dict[str, Any]]:
    """Routines whose time has come today and that have not yet run today. Each is
    marked as run before it is returned, so a failing routine is not retried all day."""
    today = now.date().isoformat()
    with _lock:
        items = load(_FILE)
        due = []
        for item in items:
            if item.get("kind") != "routine" or item.get("last_run") == today or now.weekday() not in item["days"]:
                continue
            at = datetime.combine(now.date(), dtime.fromisoformat(item["time"]))
            if at <= now < at + _ROUTINE_GRACE:
                item["last_run"] = today
                due.append(item)
        if due:
            save(_FILE, items)
    return due


def routine_prompt(item: dict[str, Any]) -> str:
    return (f"[Standing order \"{item['name']}\", which I asked you to carry out at this time] "
            f"{item['request']}")


# --------------------------------------------------------------------------- watcher checks
# A check takes the watcher (its ``state`` dict is its memory between checks) and
# returns the sentence to tell the user once the condition is met, else None.

def _github_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {require_env('GITHUB_PAT', 'GitHub')}",
            "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}


def _github(path: str, **params: Any) -> Any:
    return http_get_json(f"https://api.github.com{path}", headers=_github_headers(), params=params, service="GitHub")


_DEPLOY_DONE = {"READY": "is ready", "ERROR": "has failed", "CANCELED": "was cancelled"}


def _check_deploy(w: dict[str, Any]) -> str | None:
    params: dict[str, Any] = {"limit": 1}
    if w["target"]:
        params["projectId"] = w["target"]
    if team := os.environ.get("VERCEL_TEAM_ID", "").strip():
        params["teamId"] = team
    token = require_env("VERCEL_TOKEN", "Vercel")
    found = http_get_json("https://api.vercel.com/v6/deployments", headers={"Authorization": f"Bearer {token}"},
                          params=params, service="Vercel").get("deployments", [])
    if not found:
        raise ToolError("No deployments found" + (f" for the project {w['target']}." if w["target"] else "."))
    latest = found[0]
    state = latest.get("readyState") or latest.get("state") or "UNKNOWN"
    st = w["state"]
    if "uid" not in st:  # first look: a deployment already finished is not news
        st.update(uid=latest["uid"], finished=state in _DEPLOY_DONE)
        return None
    if state not in _DEPLOY_DONE or (latest["uid"] == st["uid"] and st["finished"]):
        return None
    return f"Sir, the {latest.get('target') or 'preview'} deployment of {latest.get('name', 'your project')} {_DEPLOY_DONE[state]}."


def _check_ci(w: dict[str, Any]) -> str | None:
    st = w["state"]
    if "repo" not in st:  # work out once what is being watched
        target = w["target"].strip()
        pr = re.search(r"#?(\d+)\s*$", target)
        repo = re.sub(r"\s*#?\d+\s*$", "", target).strip() if pr else target
        if repo and "/" not in repo:
            repo = f"{_github('/user')['login']}/{repo}"
        if not repo:  # nothing named: the user's most recently updated open pull request
            login = _github("/user")["login"]
            mine = _github("/search/issues", q=f"is:pr is:open author:{login}", sort="updated", per_page=1)["items"]
            if not mine:
                raise ToolError("You have no open pull requests; name a repository to watch its latest workflow run.")
            repo, pr_number = mine[0]["repository_url"].split("/repos/")[-1], mine[0]["number"]
        else:
            pr_number = int(pr.group(1)) if pr else None
        st.update(repo=repo, pr=pr_number)
    if st["pr"] is None:  # the repository's latest workflow run
        runs = _github(f"/repos/{st['repo']}/actions/runs", per_page=1).get("workflow_runs", [])
        if not runs:
            raise ToolError(f"{st['repo']} has no workflow runs.")
        run = runs[0]
        if "run" not in st:
            st.update(run=run["id"], finished=run["status"] == "completed")
            return None
        if run["status"] != "completed" or (run["id"] == st["run"] and st["finished"]):
            return None
        return f"Sir, the {run.get('name', 'workflow')} run on {st['repo']} finished: {run.get('conclusion') or 'no conclusion'}."
    sha = _github(f"/repos/{st['repo']}/pulls/{st['pr']}")["head"]["sha"]
    checks = _github(f"/repos/{st['repo']}/commits/{sha}/check-runs", per_page=100).get("check_runs", [])
    if not checks:
        raise ToolError(f"Pull request #{st['pr']} on {st['repo']} has no checks to wait for.")
    if any(c["status"] != "completed" for c in checks):
        st["seen_running"] = True
        return None
    failed = [c["name"] for c in checks if c.get("conclusion") not in ("success", "skipped", "neutral")]
    name = f"pull request {st['pr']} on {st['repo'].split('/')[-1]}"
    if failed:
        return f"Sir, the checks on {name} have finished, and {len(failed)} did not pass: {', '.join(failed[:3])}."
    return f"Sir, all {len(checks)} checks on {name} have passed."


def steam_find(name: str) -> tuple[str, str]:
    """(app id, title) of the best Steam store match for a game's name."""
    country = os.environ.get("STEAM_COUNTRY", "").strip() or "in"
    found = http_get_json("https://store.steampowered.com/api/storesearch/",
                          params={"term": name, "l": "english", "cc": country}, service="the Steam store")
    items = found.get("items") or []
    if not items:
        raise ToolError(f"The Steam store has no game matching '{name}'.")
    return str(items[0]["id"]), items[0]["name"]


def steam_price(app_id: str) -> dict[str, Any] | None:
    country = os.environ.get("STEAM_COUNTRY", "").strip() or "in"
    data = http_get_json("https://store.steampowered.com/api/appdetails",
                         params={"appids": app_id, "cc": country, "filters": "price_overview"},
                         service="the Steam store")
    entry = data.get(app_id) or {}
    overview = entry.get("data", {}).get("price_overview") if isinstance(entry.get("data"), dict) else None
    return overview or None


def _check_steam(w: dict[str, Any]) -> str | None:
    st = w["state"]
    if "app" not in st:
        st["app"], st["title"] = steam_find(w["target"])
    price = steam_price(st["app"])
    if price is None:  # free, unreleased, or not sold in this country
        if "checked" not in st:
            raise ToolError(f"{st['title']} has no price on Steam at the moment (free, unreleased or unavailable here).")
        return None
    st["checked"] = True
    final = price["final"] / 100
    if w.get("value"):
        if final <= w["value"]:
            return f"Sir, {st['title']} is now {price['final_formatted']} on Steam, at or below the {w['value']:,.0f} you named."
    elif price.get("discount_percent"):
        return (f"Sir, {st['title']} is on sale on Steam: {price['final_formatted']}, "
                f"{price['discount_percent']} percent off {price['initial_formatted']}.")
    return None


def page_text(url: str) -> str:
    """The visible text of a web page, one phrase per line."""
    try:
        response = httpx.get(url, headers={"User-Agent": BROWSER_USER_AGENT}, timeout=20, follow_redirects=True)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ToolError(f"Could not load {url}: {exc}") from exc
    body = re.sub(r"(?is)<(script|style|noscript|svg|head)\b.*?</\1>", " ", response.text)
    body = re.sub(r"(?s)<!--.*?-->", " ", body)
    lines = (" ".join(html.unescape(part).split()) for part in re.split(r"<[^>]+>", body))
    return "\n".join(line for line in lines if line)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def _check_page(w: dict[str, Any]) -> str | None:
    st, phrase = w["state"], (w.get("phrase") or "").strip().lower()
    text = page_text(w["target"])
    where = re.sub(r"^https?://(www\.)?", "", w["target"]).split("/")[0]
    if phrase:
        if phrase in text.lower():
            if "digest" not in st:
                raise ToolError(f"That page already contains '{w['phrase']}'.")
            return f"Sir, the page at {where} now mentions '{w['phrase']}'."
        st["digest"] = "-"
        return None
    if "digest" not in st:
        time.sleep(2)  # a page that differs on every load cannot be watched for change
        if _digest(page_text(w["target"])) != _digest(text):
            raise ToolError("That page is different on every load, so a change cannot be told from noise. "
                            "Name a phrase to wait for instead (for example 'in stock').")
        st["digest"] = _digest(text)
        return None
    return f"Sir, the page at {where} has changed." if _digest(text) != st["digest"] else None


_FOLDERS = {"downloads": "Downloads", "desktop": "Desktop", "documents": "Documents",
            "pictures": "Pictures", "videos": "Videos", "music": "Music"}


def resolve_folder(name: str) -> Path:
    """A folder inside the user's home: by its common name or its path."""
    home = Path.home()
    key = (name or "downloads").strip().strip('"').lower().removeprefix("my ").removesuffix(" folder")
    if key in _FOLDERS:
        direct = home / _FOLDERS[key]
        onedrive = home / "OneDrive" / _FOLDERS[key]  # Desktop and Documents often live in OneDrive
        folder = direct if direct.is_dir() or not onedrive.is_dir() else onedrive
    else:
        folder = Path(os.path.expandvars(name.strip().strip('"'))).expanduser()
    try:
        folder = folder.resolve()
        folder.relative_to(home.resolve())
    except (OSError, ValueError) as exc:
        raise ToolError(f"I may only watch folders inside your home folder, and '{name}' is not one.") from exc
    if not folder.is_dir():
        raise ToolError(f"There is no folder at {folder}.")
    return folder


def _files(folder: Path) -> list[str]:
    try:
        return sorted(p.name for p in folder.iterdir() if p.is_file())
    except OSError as exc:
        raise ToolError(f"Could not read {folder}: {exc}") from exc


def _check_download(w: dict[str, Any]) -> str | None:
    st = w["state"]
    folder = resolve_folder("downloads")
    names = _files(folder)
    partial = [n for n in names if n.lower().endswith(_PARTIAL)]
    if "waiting" not in st:
        if not partial:
            raise ToolError("No download is in progress in your Downloads folder.")
        st.update(waiting=partial, before=[n for n in names if n not in partial])
        return None
    if any(n in partial for n in st["waiting"]):
        return None
    arrived = [n for n in names if n not in st["before"] and n not in partial]
    if not arrived:
        return "Sir, the download is no longer in progress, though no new file has appeared; it may have been cancelled."
    return f"Sir, the download has finished: {', '.join(arrived[:3])}."


def _check_file(w: dict[str, Any]) -> str | None:
    st = w["state"]
    folder = resolve_folder(w["target"])
    pattern = (w.get("phrase") or "*").strip().lower()
    if not any(ch in pattern for ch in "*?"):
        pattern = f"*{pattern}*"
    names = _files(folder)
    if "before" not in st:
        st["before"] = names
        return None
    new = [n for n in names if n not in st["before"] and not n.lower().endswith(_PARTIAL)
           and fnmatch.fnmatch(n.lower(), pattern)]
    return f"Sir, a new file has appeared in {folder.name}: {', '.join(new[:3])}." if new else None


def _check_battery(w: dict[str, Any]) -> str | None:
    battery = psutil.sensors_battery()
    if battery is None:
        raise ToolError("This machine reports no battery.")
    st, level = w["state"], float(w.get("value") or 100)
    if "rising" not in st:
        if round(battery.percent) == round(level):
            raise ToolError(f"The battery is already at {battery.percent:.0f} percent.")
        st["rising"] = battery.percent < level
        return None
    met = battery.percent >= level if st["rising"] else battery.percent <= level
    if not met:
        return None
    return ("Sir, the battery is fully charged." if level >= 100
            else f"Sir, the battery has reached {battery.percent:.0f} percent.")


def _processes(name: str) -> list[psutil.Process]:
    wanted = name.strip().lower().removesuffix(".exe")
    return [p for p in psutil.process_iter(["name"])
            if wanted and wanted in (p.info["name"] or "").lower().removesuffix(".exe")]


def _check_app(w: dict[str, Any]) -> str | None:
    running = bool(_processes(w["target"]))
    if "seen" not in w["state"]:
        if not running:
            raise ToolError(f"No program matching '{w['target']}' is running.")
        w["state"]["seen"] = True
        return None
    return None if running else f"Sir, {w['target']} has closed."


# Processor time used so far, per watcher: kept in memory, not in the file, since it
# means nothing after a restart.
_cpu_marks: dict[str, tuple[float, float]] = {}
_QUIET_CHECKS = 4  # consecutive quiet checks (about two minutes) before it counts


def _cpu_used(name: str) -> float:
    """Processor seconds consumed so far: by one program, or by everything."""
    if name:
        total = 0.0
        for proc in _processes(name):
            try:
                t = proc.cpu_times()
                total += t.user + t.system
            except psutil.Error:
                continue
        return total
    t = psutil.cpu_times()
    return sum(t) - t.idle


def _check_cpu(w: dict[str, Any]) -> str | None:
    st, name = w["state"], (w.get("target") or "").strip()
    limit = float(w.get("value") or 20)
    if name and not _processes(name):
        if "quiet" not in st:
            raise ToolError(f"No program matching '{name}' is running.")
        return f"Sir, {name} has finished and closed."
    now, used = time.monotonic(), _cpu_used(name)
    then, before = _cpu_marks.get(w["id"], (now, used))
    _cpu_marks[w["id"]] = (now, used)
    st.setdefault("quiet", 0)
    if now - then < 5:  # the first look: nothing to compare with yet
        return None
    share = 100 * (used - before) / ((now - then) * (psutil.cpu_count() or 1))
    st["quiet"] = st["quiet"] + 1 if share < limit else 0
    if st["quiet"] < _QUIET_CHECKS:
        return None
    return f"Sir, {name or 'the processor'} has gone quiet; whatever was running appears to have finished."


# kind -> (check, seconds between checks, days before the watch lapses, what the target means)
_KINDS: dict[str, tuple[Callable[[dict[str, Any]], str | None], int, float, str]] = {
    "deploy": (_check_deploy, 60, 1, "Vercel project name, or empty for the latest deployment of any project"),
    "ci": (_check_ci, 60, 1, "'owner/repo#12' or 'repo#12' for a pull request's checks; 'owner/repo' for the latest "
                             "workflow run; empty for the user's most recent open pull request"),
    "steam_price": (_check_steam, 3 * 3600, 60, "the game's name; value = price in rupees to fall to (omit for any sale)"),
    "page": (_check_page, 15 * 60, 30, "the page's URL; phrase = text to wait for (omit to wait for any change)"),
    "download": (_check_download, 30, 1, "empty: the downloads now in progress in the Downloads folder"),
    "file": (_check_file, 30, 7, "folder: downloads, desktop, documents, or a path in the home folder; "
                                 "phrase = file name pattern such as *.pdf (optional)"),
    "battery": (_check_battery, 30, 1, "empty; value = percent to reach (default 100, fully charged)"),
    "app_closed": (_check_app, 30, 1, "the program's name, such as blender or chrome"),
    "cpu_quiet": (_check_cpu, 30, 1, "a program's name, or empty for the whole processor; "
                                     "value = percent below which it counts as quiet (default 20)"),
}


def _label(w: dict[str, Any]) -> str:
    kind, target, value, phrase = w["type"], w.get("target") or "", w.get("value"), w.get("phrase") or ""
    st = w.get("state", {})
    return {
        "deploy": f"the next Vercel deployment{' of ' + target if target else ''} to finish",
        "ci": (f"the checks on pull request {st.get('pr')} of {st.get('repo')}" if st.get("pr")
               else f"the latest workflow run on {st.get('repo') or target}"),
        "steam_price": f"{st.get('title') or target} on Steam " + (f"to reach ₹{value:,.0f}" if value else "to go on sale"),
        "page": f"{target} " + (f"to mention '{phrase}'" if phrase else "to change"),
        "download": "the current download to finish",
        "file": f"a new {phrase + ' ' if phrase else ''}file in {target or 'downloads'}",
        "battery": f"the battery to reach {value or 100:.0f} percent",
        "app_closed": f"{target} to close",
        "cpu_quiet": f"{target or 'the processor'} to go quiet",
    }[kind]


def poll(now: datetime) -> list[str]:
    """Check every watcher that is due. Returns the sentences to tell the user; a
    watcher that has spoken, or lapsed, is removed."""
    messages: list[str] = []
    with _lock:
        items = load(_FILE)
        keep, changed = [], False
        for w in items:
            if w.get("kind") != "watch":
                keep.append(w)
                continue
            check, every, _, _ = _KINDS[w["type"]]
            if now.timestamp() >= w["expires"]:
                messages.append(f"Sir, I have stopped watching for {_label(w)}; it did not happen in the time allowed.")
                sebas_actions.log("watch", f"lapsed: {_label(w)}", ok=False)
                changed = True
                continue
            if now.timestamp() - w.get("checked", 0) < every:
                keep.append(w)
                continue
            w["checked"], changed = now.timestamp(), True
            try:
                message = check(w)
            except ToolError as exc:  # usually the network: try again at the next check
                w["failures"] = w.get("failures", 0) + 1
                message = None
                if w["failures"] >= 30:
                    messages.append(f"Sir, I have had to stop watching for {_label(w)}: {exc}")
                    continue
            else:
                w["failures"] = 0
            if message:
                messages.append(message)
                sebas_actions.log("watch", message)
                _cpu_marks.pop(w["id"], None)
            else:
                keep.append(w)
        if changed:
            save(_FILE, keep)
    return messages


def snapshot() -> list[dict[str, str]]:
    """For the interface: each standing order as a label and a detail."""
    rows = []
    for item in load(_FILE):
        if item.get("kind") == "routine":
            rows.append({"label": item["name"], "detail": f"{item['time']} · {describe_days(item['days'])}"})
        else:
            rows.append({"label": _label(item)[:1].upper() + _label(item)[1:], "detail": "watching"})
    return rows


def _proactive_note() -> str:
    off = os.environ.get("SEBAS_PROACTIVE", "on").strip().lower() in ("off", "0", "false", "no")
    return " Note: SEBAS_PROACTIVE is off in .env, so nothing will happen until it is switched on." if off else ""


# --------------------------------------------------------------------------- tools

@ToolRegistry.register("add_routine")
class AddRoutineTool(SebasTool):
    name = "add_routine"
    description = (
        "Create a standing order: something to do at a set time on set days, such as 'every "
        "weekday at 9, open my workspace and read me my pull requests'. The request is put to "
        "you at that time as if the user had just asked it. For a one-off, use set_reminder or add_task."
    )
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "A short name, two to four words."},
            "request": {"type": "string", "description": "What to do each time, phrased as the user would ask you."},
            "time": {"type": "string", "description": "24-hour HH:MM."},
            "days": {"type": "string", "description": "daily, weekdays, weekends, or day names such as 'mon, wed, fri'. Default daily."},
        },
        "required": ["name", "request", "time"],
    }

    def run(self, name: str, request: str, time: str, days: str = "daily") -> str:  # noqa: A002
        name, request = " ".join((name or "").split()), " ".join((request or "").split())
        if not name or not request:
            raise ToolError("A standing order needs a name and something to do.")
        at, day_list = _parse_clock(time), parse_days(days)
        now = datetime.now()
        with _lock:
            items = [i for i in load(_FILE) if not (i.get("kind") == "routine" and i["name"].lower() == name.lower())]
            items.append({"id": uuid.uuid4().hex[:8], "kind": "routine", "name": name, "request": request,
                          "time": at.strftime("%H:%M"), "days": day_list,
                          # created after today's time: it starts tomorrow, not at once
                          "last_run": now.date().isoformat() if now.time() >= at else ""})
            save(_FILE, items)
        sebas_actions.log("add_routine", f"{name}: {at.strftime('%H:%M')} {describe_days(day_list)}: {request}")
        return (f"Standing order '{name}' set for {at.strftime('%H:%M')}, {describe_days(day_list)}. It runs when "
                f"the user is at the laptop, up to three hours late if he is away at the time.{_proactive_note()}")


@ToolRegistry.register("watch_for")
class WatchForTool(SebasTool):
    name = "watch_for"
    timeout_seconds = 60.0
    description = (
        "Watch for something and tell the user once when it happens ('tell me when...'). Kinds and "
        "what 'target' means: " + "; ".join(f"{k}: {v[3]}" for k, v in _KINDS.items()) + "."
    )
    parameters = {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": list(_KINDS)},
            "target": {"type": "string", "description": "What to watch; its meaning depends on the kind."},
            "value": {"type": "number", "description": "A price, battery percent or CPU percent, where the kind uses one."},
            "phrase": {"type": "string", "description": "Text to wait for on a page, or a file name pattern."},
        },
        "required": ["kind"],
    }

    def run(self, kind: str, target: str = "", value: float | None = None, phrase: str = "") -> str:
        if kind not in _KINDS:
            raise ToolError(f"Unknown kind '{kind}'. Options: {', '.join(_KINDS)}.")
        if kind in ("steam_price", "page", "app_closed") and not (target or "").strip():
            raise ToolError(f"A {kind} watch needs a target: {_KINDS[kind][3]}.")
        if kind == "page" and not re.match(r"https?://", target.strip()):
            target = "https://" + target.strip()
        check, _, days, _ = _KINDS[kind]
        now = datetime.now()
        w: dict[str, Any] = {"id": uuid.uuid4().hex[:8], "kind": "watch", "type": kind, "target": (target or "").strip(),
                             "value": float(value) if value else None, "phrase": (phrase or "").strip(),
                             "state": {}, "created": now.isoformat(timespec="minutes"),
                             "checked": now.timestamp(), "expires": now.timestamp() + days * 86400}
        already = check(w)  # the first look: proves the target exists, and records where things stand
        if already:
            return f"No need to wait: {already}"
        with _lock:
            items = load(_FILE)
            if sum(1 for i in items if i.get("kind") == "watch") >= 20:
                raise ToolError("Twenty things are already being watched; cancel one first.")
            items.append(w)
            save(_FILE, items)
        sebas_actions.log("watch_for", _label(w))
        lapse = f"{days:.0f} days" if days > 1 else "a day"
        return f"Watching for {_label(w)}. I will say so once when it happens, and give up after {lapse}.{_proactive_note()}"


@ToolRegistry.register("list_standing")
class ListStandingTool(SebasTool):
    name = "list_standing"
    description = "List the user's standing orders (timed routines) and the things being watched for."

    def run(self) -> str:
        items = load(_FILE)
        if not items:
            return "There are no standing orders, and nothing is being watched."
        lines = []
        for i in items:
            if i.get("kind") == "routine":
                lines.append(f"- Routine '{i['name']}': {i['time']}, {describe_days(i['days'])}: {i['request']}")
            else:
                lines.append(f"- Watching for {_label(i)} (since {i['created'].replace('T', ' ')})")
        return "\n".join(lines)


@ToolRegistry.register("cancel_standing")
class CancelStandingTool(SebasTool):
    name = "cancel_standing"
    description = (
        "Cancel a standing order or a watch, described as the user describes it; 'all' cancels "
        "every one."
    )
    parameters = {
        "type": "object",
        "properties": {"what": {"type": "string", "description": "The routine's name or what is being watched; 'all' for everything."}},
        "required": ["what"],
    }

    def run(self, what: str) -> str:
        target = (what or "").strip().lower()
        with _lock:
            items = load(_FILE)
            if not items:
                raise ToolError("There is nothing to cancel.")
            names = [i["name"] if i.get("kind") == "routine" else _label(i) for i in items]
            if target in ("all", "everything", "all of them"):
                gone = list(range(len(items)))
            else:
                scored = sorted(((SequenceMatcher(None, target, n.lower()).ratio() + (0.4 if target in n.lower() else 0), idx)
                                 for idx, n in enumerate(names)), reverse=True)
                if scored[0][0] < 0.45:
                    raise ToolError(f"Nothing matches '{what}'. Current: {'; '.join(names)}.")
                gone = [scored[0][1]]
            for idx in gone:
                _cpu_marks.pop(items[idx]["id"], None)
            save(_FILE, [i for idx, i in enumerate(items) if idx not in gone])
        cancelled = "; ".join(names[idx] for idx in gone)
        sebas_actions.log("cancel_standing", cancelled)
        return f"Cancelled ({len(gone)}): {cancelled}."
