"""Music (Spotify and any media player) and minor system settings.

Music uses the keyboard media keys, so it works with Spotify, YouTube in a
browser, or any player; what is playing is read from the Spotify window title.

System settings are deliberately small and reversible: Wi-Fi and Bluetooth
radios, screen brightness, and dark/light mode. Nothing here shuts down,
restarts, or changes anything that needs administrator rights.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import time
import urllib.parse
import winreg
from ctypes import wintypes

import psutil
from openjarvis.core.registry import ToolRegistry

from custom_tools._base import SebasTool, ToolError

# --------------------------------------------------------------------------- media keys

_VK = {"play_pause": 0xB3, "next": 0xB0, "previous": 0xB1, "stop": 0xB2}
_KEYEVENTF_KEYUP = 0x0002


def press_media_key(action: str) -> None:
    vk = _VK[action]
    ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
    ctypes.windll.user32.keybd_event(vk, 0, _KEYEVENTF_KEYUP, 0)


def _window_titles(process_name: str) -> list[str]:
    """Titles of the visible top-level windows of every process with this name."""
    pids = {p.pid for p in psutil.process_iter(["name"]) if (p.info["name"] or "").lower() == process_name.lower()}
    if not pids:
        return []
    titles: list[str] = []
    user32 = ctypes.windll.user32

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def collect(hwnd, _):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in pids and user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                titles.append(buf.value)
        return True

    user32.EnumWindows(collect, 0)
    return titles


def spotify_running() -> bool:
    return any((p.info["name"] or "").lower() == "spotify.exe" for p in psutil.process_iter(["name"]))


def spotify_now_playing() -> str | None:
    """'Artist - Song' while Spotify is playing; None when paused or closed.

    The desktop app shows the track in its window title while playing, and
    just 'Spotify' / 'Spotify Premium' / 'Spotify Free' while paused.
    """
    for title in _window_titles("Spotify.exe"):
        if " - " in title:
            return title
    return None


def open_spotify(uri: str = "spotify:") -> None:
    os.startfile(uri)  # type: ignore[attr-defined]


def resume_spotify(wait_seconds: float = 10.0) -> str:
    """Open Spotify if needed and resume the last track. Returns what happened."""
    if spotify_now_playing():
        return f"Spotify is already playing {spotify_now_playing()}."
    started = not spotify_running()
    if started:
        open_spotify()
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline and not _window_titles("Spotify.exe"):
        time.sleep(0.5)
    if started:
        time.sleep(2.5)  # the app needs a moment before it accepts media keys
    press_media_key("play_pause")
    time.sleep(1.5)
    playing = spotify_now_playing()
    return f"Resumed {playing} on Spotify." if playing else "Spotify is open; it did not start playing on its own, so press play once."


@ToolRegistry.register("media_control")
class MediaControlTool(SebasTool):
    name = "media_control"
    acts_on_laptop = True
    description = (
        "Control whatever music or video is playing (Spotify, a browser, any player): "
        "play or pause, next track, previous track, stop. Also reports what Spotify is playing."
    )
    parameters = {
        "type": "object",
        "properties": {"action": {"type": "string", "enum": ["play_pause", "next", "previous", "stop", "now_playing"]}},
        "required": ["action"],
    }

    def run(self, action: str) -> str:
        if action == "now_playing":
            playing = spotify_now_playing()
            if playing:
                return f"Spotify is playing {playing}."
            return "Spotify is paused." if spotify_running() else "Spotify is not open."
        if action not in _VK:
            raise ToolError(f"Unknown action '{action}'.")
        press_media_key(action)
        time.sleep(1.2)
        playing = spotify_now_playing()
        done = {"play_pause": "Toggled play/pause", "next": "Skipped to the next track",
                "previous": "Went back a track", "stop": "Stopped playback"}[action]
        return f"{done}." + (f" Now playing {playing}." if playing else "")


@ToolRegistry.register("spotify")
class SpotifyTool(SebasTool):
    name = "spotify"
    acts_on_laptop = True
    description = (
        "Open Spotify; resume the music that was playing; or look up a song, artist, "
        "album or playlist in Spotify. A lookup opens Spotify's search results, and the "
        "user presses play on the one they want (choosing a track by name needs the "
        "Spotify Web API, which is not set up)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["open", "resume", "search"]},
            "query": {"type": "string", "description": "What to search for (search only)."},
        },
        "required": ["action"],
    }
    timeout_seconds = 30.0

    def run(self, action: str, query: str = "") -> str:
        if action == "open":
            open_spotify()
            return "Spotify is open."
        if action == "resume":
            return resume_spotify()
        if action == "search":
            if not query.strip():
                raise ToolError("Say what to search for.")
            open_spotify("spotify:search:" + urllib.parse.quote(query.strip()))
            return f"Spotify is showing results for '{query.strip()}'; the user can press play on the one they want."
        raise ToolError(f"Unknown action '{action}'.")


# --------------------------------------------------------------------------- system settings

_RADIO_SCRIPT = r"""
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
  $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
  $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, $type) { $t = $asTask.MakeGenericMethod($type).Invoke($null, @($op)); $t.Wait(-1) | Out-Null; $t.Result }
[Windows.Devices.Radios.Radio, Windows.System.Devices, ContentType=WindowsRuntime] | Out-Null
[Windows.Devices.Radios.RadioAccessStatus, Windows.System.Devices, ContentType=WindowsRuntime] | Out-Null
[Windows.Devices.Radios.RadioState, Windows.System.Devices, ContentType=WindowsRuntime] | Out-Null
Await ([Windows.Devices.Radios.Radio]::RequestAccessAsync()) ([Windows.Devices.Radios.RadioAccessStatus]) | Out-Null
$radios = Await ([Windows.Devices.Radios.Radio]::GetRadiosAsync()) ([System.Collections.Generic.IReadOnlyList[Windows.Devices.Radios.Radio]])
$kind = '{KIND}'; $target = '{STATE}'
$radio = $radios | Where-Object { $_.Kind -eq $kind } | Select-Object -First 1
if (-not $radio) { 'MISSING'; exit }
if ($target -ne 'Query') { Await ($radio.SetStateAsync($target)) ([Windows.Devices.Radios.RadioAccessStatus]) | Out-Null }
$radio.State
"""


def _powershell(script: str, timeout: float = 30) -> str:
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True, text=True, timeout=timeout,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode != 0:
        raise ToolError(f"Windows refused: {(result.stderr or result.stdout).strip()[:200]}")
    return result.stdout.strip()


def radio_state(kind: str, state: str = "Query") -> str:
    """kind: WiFi | Bluetooth; state: On | Off | Query. Returns the radio's state."""
    out = _powershell(_RADIO_SCRIPT.replace("{KIND}", kind).replace("{STATE}", state))
    if "MISSING" in out:
        raise ToolError(f"This laptop has no {kind} radio that Windows lets me control.")
    return out.splitlines()[-1].strip() if out else "Unknown"


@ToolRegistry.register("set_radio")
class SetRadioTool(SebasTool):
    name = "set_radio"
    acts_on_laptop = True
    description = (
        "Turn the laptop's Wi-Fi or Bluetooth on or off, or report whether it is on. "
        "Turning Wi-Fi off disconnects the internet, so Sebas falls back to his local model."
    )
    parameters = {
        "type": "object",
        "properties": {
            "radio": {"type": "string", "enum": ["wifi", "bluetooth"]},
            "state": {"type": "string", "enum": ["on", "off", "status"]},
        },
        "required": ["radio", "state"],
    }
    timeout_seconds = 40.0

    def run(self, radio: str, state: str) -> str:
        kind = {"wifi": "WiFi", "bluetooth": "Bluetooth"}.get(radio.lower())
        if kind is None:
            raise ToolError("Only Wi-Fi and Bluetooth can be switched.")
        target = {"on": "On", "off": "Off", "status": "Query"}.get(state.lower())
        if target is None:
            raise ToolError("State must be on, off or status.")
        now = radio_state(kind, target)
        label = "Wi-Fi" if kind == "WiFi" else "Bluetooth"
        return f"{label} is {now.lower()}."


def get_brightness() -> int:
    return int(_powershell("(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness).CurrentBrightness"))


@ToolRegistry.register("set_brightness")
class SetBrightnessTool(SebasTool):
    name = "set_brightness"
    acts_on_laptop = True
    description = "Set the laptop screen's brightness (0-100), or report it if no level is given."
    parameters = {
        "type": "object",
        "properties": {"level": {"type": "integer", "description": "Brightness percentage, 0-100."}},
    }

    def run(self, level: int | None = None) -> str:
        if level is not None:
            level = max(0, min(int(level), 100))
            _powershell(
                "Invoke-CimMethod -InputObject (Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods) "
                f"-MethodName WmiSetBrightness -Arguments @{{Timeout=1; Brightness={level}}} | Out-Null"
            )
        try:
            return f"Brightness is {get_brightness()} percent."
        except (ToolError, ValueError):
            raise ToolError("This display does not let Windows change its brightness (external monitors usually don't).")


_THEME_KEY = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"


def is_dark_mode() -> bool:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _THEME_KEY) as key:
        return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0


@ToolRegistry.register("set_theme")
class SetThemeTool(SebasTool):
    name = "set_theme"
    acts_on_laptop = True
    description = "Switch Windows between dark and light mode, or report the current mode."
    parameters = {
        "type": "object",
        "properties": {"mode": {"type": "string", "enum": ["dark", "light", "status"]}},
        "required": ["mode"],
    }

    def run(self, mode: str) -> str:
        if mode in ("dark", "light"):
            light = 1 if mode == "light" else 0
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _THEME_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, "AppsUseLightTheme", 0, winreg.REG_DWORD, light)
                winreg.SetValueEx(key, "SystemUsesLightTheme", 0, winreg.REG_DWORD, light)
        return f"Windows is in {'dark' if is_dark_mode() else 'light'} mode."
