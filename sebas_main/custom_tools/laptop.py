"""Laptop actions, limited to the allowlist in configs/sebas/laptop.toml."""

from __future__ import annotations

import ctypes
import json
import logging
import os
import threading
import time
import tomllib
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

import psutil
from openjarvis.core.registry import ToolRegistry

from custom_tools._base import SebasTool, ToolError

_ROOT = Path(__file__).resolve().parent.parent


def config_path() -> Path:
    return Path(
        os.environ.get("SEBAS_LAPTOP_CONFIG")
        or _ROOT / "configs" / "sebas" / "laptop.toml"
    )


def load_config() -> dict[str, Any]:
    path = config_path()
    if not path.exists():
        return {}
    try:
        with open(path, "rb") as fh:
            return tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ToolError(f"{path.name} has a syntax error: {exc}") from exc


def _section(name: str) -> dict[str, Any]:
    return load_config().get(name, {}) or {}


def _choice_param(section: str, description: str) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "string", "description": description}
    try:
        names = sorted(_section(section))
    except ToolError as exc:
        # A typo in laptop.toml must not stop Sebas from starting; the tool
        # reports the error when it is used.
        logging.getLogger(__name__).error("%s", exc)
        names = []
    if names:
        schema["enum"] = names
    return schema


def _lookup(section: str, name: str) -> Any:
    entries = _section(section)
    key = next((k for k in entries if k.lower() == (name or "").strip().lower()), None)
    if key is None:
        options = ", ".join(sorted(entries)) or "none configured"
        raise ToolError(
            f"'{name}' is not in the [{section}] list of laptop.toml. Options: {options}."
        )
    return entries[key]


# Launchers are module-level so tests can replace them.
def launch(target: str, *args: str) -> None:
    if args:
        import subprocess

        subprocess.Popen([target, *args])
    else:
        os.startfile(target)  # type: ignore[attr-defined]


def open_url(url: str) -> None:
    webbrowser.open(url)


def _open_app(name: str) -> str:
    launch(str(_lookup("apps", name)))
    return f"Opened {name}."


def _open_website(name: str) -> str:
    open_url(str(_lookup("websites", name)))
    return f"Opened {name} in the browser."


_TASK_LABEL = "Sebas: start terminal command"


def ensure_terminal_task(folder: Path, command: str) -> str:
    """Make the editor run ``command`` in its terminal whenever ``folder`` opens."""
    tasks_file = folder / ".vscode" / "tasks.json"
    if tasks_file.exists():
        text = tasks_file.read_text("utf-8", errors="replace")
        if _TASK_LABEL in text:
            return ""
        return (
            f" {tasks_file} already exists, so {command} was not added to it; "
            "start it in the terminal manually."
        )
    tasks_file.parent.mkdir(exist_ok=True)
    task = {
        "label": _TASK_LABEL,
        "type": "shell",
        "command": command,
        "presentation": {"reveal": "always", "panel": "dedicated", "focus": True},
        "runOptions": {"runOn": "folderOpen"},
    }
    tasks_file.write_text(json.dumps({"version": "2.0.0", "tasks": [task]}, indent=2), "utf-8")
    return (
        f" Created {tasks_file} so {command} starts in the editor's terminal. If the "
        "editor asks whether to allow automatic tasks, allow them once."
    )


def _open_workspace(project: str) -> str:
    folder = Path(str(_lookup("projects", project))).expanduser()
    if not folder.is_dir():
        raise ToolError(f"The folder for {project} does not exist: {folder}")
    ws = _section("workspace")
    editor = ws.get("editor", "")
    if not editor or not Path(editor).exists():
        raise ToolError(f"The [workspace] editor in laptop.toml was not found: {editor}")
    note = ""
    if command := ws.get("terminal_command", ""):
        note = ensure_terminal_task(folder, command)
    launch(editor, str(folder))
    opened = f"Opened {project} in the editor"
    if site := ws.get("website", ""):
        open_url(str(_lookup("websites", site)))
        opened += f" and {site} in the browser"
    if ws.get("music"):
        # Spotify takes a few seconds to start; resume the music without making
        # the user wait for it.
        from custom_tools.media_system import resume_spotify

        threading.Thread(target=resume_spotify, daemon=True).start()
        opened += ", and Spotify is starting to resume your music"
    return opened + "." + note


_STEP_ACTIONS: dict[str, Callable[[str], str]] = {
    "app": _open_app,
    "website": _open_website,
    "workspace": _open_workspace,
}


class _ChoiceTool(SebasTool):
    section: str = ""
    argument: str = "name"
    argument_description: str = ""
    action: Callable[[str], str]

    def parameter_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                self.argument: _choice_param(self.section, self.argument_description)
            },
            "required": [self.argument],
        }

    def run(self, **params: Any) -> str:
        return type(self).action(params.get(self.argument, ""))


@ToolRegistry.register("open_app")
class OpenAppTool(_ChoiceTool):
    name = "open_app"
    acts_on_laptop = True
    description = "Open an application from the user's approved list."
    section = "apps"
    argument_description = "Name of the application."
    action = staticmethod(_open_app)


@ToolRegistry.register("open_website")
class OpenWebsiteTool(_ChoiceTool):
    name = "open_website"
    acts_on_laptop = True
    description = "Open a website from the user's approved list in the default browser."
    section = "websites"
    argument_description = "Name of the website."
    action = staticmethod(_open_website)


@ToolRegistry.register("open_workspace")
class OpenWorkspaceTool(_ChoiceTool):
    name = "open_workspace"
    acts_on_laptop = True
    description = (
        "Open a project folder in the user's editor (Antigravity), start the "
        "configured command in its terminal, and open the configured website. "
        "If the user did not say which project, ask them before calling this."
    )
    section = "projects"
    argument = "project"
    argument_description = "Which project to open."
    action = staticmethod(_open_workspace)


def _run_shortcut(name: str) -> str:
    steps = _lookup("shortcuts", name)
    results = []
    for step in steps:
        kind, _, target = str(step).partition(":")
        action = _STEP_ACTIONS.get(kind.strip())
        if action is None:
            results.append(f"Skipped '{step}': use app:, website: or workspace:.")
            continue
        try:
            results.append(action(target.strip()))
        except ToolError as exc:
            results.append(f"Failed '{step}': {exc}")
    return " ".join(results)


@ToolRegistry.register("run_shortcut")
class RunShortcutTool(_ChoiceTool):
    name = "run_shortcut"
    acts_on_laptop = True
    description = "Run one of the user's named routines, which open several things at once."
    section = "shortcuts"
    argument_description = "Name of the routine."
    action = staticmethod(_run_shortcut)


@ToolRegistry.register("system_status")
class SystemStatusTool(SebasTool):
    name = "system_status"
    description = "Report the laptop's battery, CPU, memory, disk space and uptime."

    def run(self) -> str:
        parts = []
        battery = psutil.sensors_battery()
        if battery:
            state = "charging" if battery.power_plugged else "on battery"
            parts.append(f"Battery {battery.percent:.0f}% ({state})")
        parts.append(f"CPU {psutil.cpu_percent(interval=0.5):.0f}%")
        mem = psutil.virtual_memory()
        parts.append(f"memory {mem.percent:.0f}% used of {mem.total / 2**30:.1f} GB")
        disk = psutil.disk_usage(os.environ.get("SystemDrive", "C:") + "\\")
        parts.append(f"system drive {disk.free / 2**30:.0f} GB free of {disk.total / 2**30:.0f} GB")
        uptime = timedelta(seconds=int(time.time() - psutil.boot_time()))
        parts.append(f"up {uptime.days} days {uptime.seconds // 3600} hours")
        return ", ".join(parts) + "."


def _endpoint_volume():
    from pycaw.pycaw import AudioUtilities

    speakers = AudioUtilities.GetSpeakers()
    volume = getattr(speakers, "EndpointVolume", None)
    if volume is not None:
        return volume
    from ctypes import POINTER, cast

    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import IAudioEndpointVolume

    interface = speakers.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return cast(interface, POINTER(IAudioEndpointVolume))


def get_volume() -> tuple[int, bool]:
    volume = _endpoint_volume()
    return round(volume.GetMasterVolumeLevelScalar() * 100), bool(volume.GetMute())


@ToolRegistry.register("set_volume")
class SetVolumeTool(SebasTool):
    name = "set_volume"
    acts_on_laptop = True
    description = "Set the speaker volume (0-100), mute, unmute, or report the current level."
    parameters = {
        "type": "object",
        "properties": {
            "level": {"type": "integer", "description": "Volume percentage, 0-100."},
            "mute": {"type": "boolean", "description": "true to mute, false to unmute."},
        },
    }

    def run(self, level: int | None = None, mute: bool | None = None) -> str:
        volume = _endpoint_volume()
        if level is not None:
            volume.SetMasterVolumeLevelScalar(max(0, min(int(level), 100)) / 100, None)
        if mute is not None:
            volume.SetMute(int(bool(mute)), None)
        current, muted = get_volume()
        return f"Volume is {current}%" + (", muted." if muted else ".")


@ToolRegistry.register("lock_screen")
class LockScreenTool(SebasTool):
    name = "lock_screen"
    acts_on_laptop = True
    description = "Lock the laptop's screen."

    def run(self) -> str:
        if not ctypes.windll.user32.LockWorkStation():
            raise ToolError("Windows refused to lock the screen.")
        return "The screen is locked."


# Reminders live in memory and announce themselves through whatever
# run_sebas.py registers (speech in voice mode, printing in text mode).
_announce: Callable[[str], None] = print
_reminders: dict[int, tuple[datetime, str, threading.Timer]] = {}
_reminders_lock = threading.Lock()
_next_id = 1


def set_announcer(announce: Callable[[str], None]) -> None:
    global _announce
    _announce = announce


def _fire(reminder_id: int, message: str) -> None:
    with _reminders_lock:
        _reminders.pop(reminder_id, None)
    _announce(f"Pardon the interruption. A reminder: {message}")


@ToolRegistry.register("set_reminder")
class SetReminderTool(SebasTool):
    name = "set_reminder"
    description = (
        "Announce a reminder aloud after a number of minutes. Reminders are lost "
        "if Sebas is closed before they are due."
    )
    parameters = {
        "type": "object",
        "properties": {
            "minutes": {"type": "number", "description": "Minutes from now (up to 1440)."},
            "message": {"type": "string", "description": "What to remind the user of."},
        },
        "required": ["minutes", "message"],
    }

    def run(self, minutes: float, message: str) -> str:
        global _next_id
        minutes = float(minutes)
        if not 0 < minutes <= 1440:
            raise ToolError("Reminders must be between a few seconds and 24 hours away.")
        due = datetime.now() + timedelta(minutes=minutes)
        with _reminders_lock:
            reminder_id, _next_id = _next_id, _next_id + 1
            timer = threading.Timer(minutes * 60, _fire, args=(reminder_id, message))
            timer.daemon = True
            _reminders[reminder_id] = (due, message, timer)
            timer.start()
        return f"Reminder set for {due.strftime('%I:%M %p')}: {message}"


@ToolRegistry.register("list_reminders")
class ListRemindersTool(SebasTool):
    name = "list_reminders"
    description = "List the reminders that are still pending."

    def run(self) -> str:
        with _reminders_lock:
            pending = sorted(_reminders.values(), key=lambda r: r[0])
        if not pending:
            return "No reminders are pending."
        return "\n".join(f"- {due.strftime('%I:%M %p')}: {msg}" for due, msg, _ in pending)
