"""Hands on the desk: typing, window arrangement, closing programs, and a fixed
list of keyboard shortcuts. All through Windows' own APIs (no extra packages).

- type_text      dictation into whichever program has the keyboard. Sebas's own
                 window is refused, so typed requests do not type into themselves.
- arrange_windows  snap left/right, maximise, minimise, restore, switch to,
                 minimise everything.
- close_apps     asks each window to close (the same as clicking its X, so a
                 program with unsaved work still asks to save). Needs a yes.
- press_keys     only the combinations in SHORTCUTS. Nothing that closes, locks,
                 signs out or opens a system menu (no Alt+F4, Win+L, Win+R, Win+X).
"""

from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes
from typing import Any

import psutil
from openjarvis.core.registry import ToolRegistry

import sebas_actions
from custom_tools._base import SebasTool, ToolError

_MAX_TYPED = 2000
_KEY_PAUSE = 0.012  # seconds between typed characters

# --------------------------------------------------------------------------- keys

_INPUT_KEYBOARD, _KEYUP, _UNICODE = 1, 0x0002, 0x0004
_VK = {
    "ctrl": 0x11, "shift": 0x10, "alt": 0x12, "win": 0x5B,
    "enter": 0x0D, "escape": 0x1B, "tab": 0x09, "space": 0x20, "backspace": 0x08,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "pageup": 0x21, "pagedown": 0x22, "home": 0x24, "end": 0x23,
    "printscreen": 0x2C, "plus": 0xBB, "minus": 0xBD,
    **{f"f{n}": 0x6F + n for n in range(1, 13)},
    **{chr(c): c - 32 for c in range(ord("a"), ord("z") + 1)},
    **{str(n): 0x30 + n for n in range(10)},
}
_ALIASES = {"control": "ctrl", "esc": "escape", "return": "enter", "windows": "win", "pgup": "pageup",
            "pgdn": "pagedown", "prtsc": "printscreen", "spacebar": "space", "=": "plus", "-": "minus"}
_MODIFIERS = ["ctrl", "win", "alt", "shift"]  # the order shortcuts are written in
SHORTCUTS = {
    # editing
    "ctrl+s", "ctrl+c", "ctrl+v", "ctrl+x", "ctrl+z", "ctrl+y", "ctrl+a", "ctrl+f", "ctrl+p", "ctrl+n",
    # tabs and navigation
    "ctrl+t", "ctrl+w", "ctrl+shift+t", "ctrl+tab", "ctrl+shift+tab", "ctrl+l", "ctrl+r", "alt+left", "alt+right",
    "alt+tab", "f5", "f11", "ctrl+plus", "ctrl+minus", "ctrl+0",
    # plain keys
    "enter", "escape", "tab", "space", "backspace", "up", "down", "left", "right", "pageup", "pagedown", "home", "end",
    # desktop
    "win+d", "win+shift+s", "printscreen",
}


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_void_p)]


class _INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("ki", _KEYBDINPUT), ("pad", ctypes.c_byte * 32)]  # sized for the larger mouse variant

    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


def _send(events: list[tuple[int, int, int]]) -> None:
    """Each event is (virtual key, scan code, flags). Module-level so tests can replace it."""
    array = (_INPUT * len(events))()
    for slot, (vk, scan, flags) in zip(array, events):
        slot.type = _INPUT_KEYBOARD
        slot.ki = _KEYBDINPUT(vk, scan, flags, 0, None)
    sent = ctypes.windll.user32.SendInput(len(events), array, ctypes.sizeof(_INPUT))
    if sent != len(events):
        raise ToolError("Windows blocked the keystrokes (a window running as administrator has the keyboard).")


def parse_combo(text: str) -> list[str]:
    """'Control + Shift + T' -> ['ctrl', 'shift', 't']; rejects anything not in SHORTCUTS."""
    low = (text or "").lower().replace("+", " ")
    for spoken in ("page up", "page down", "print screen"):
        low = low.replace(spoken, spoken.replace(" ", ""))
    parts = [_ALIASES.get(p, p) for p in low.split()]
    parts = [p for n, p in enumerate(parts) if p != "plus" or n == len(parts) - 1]  # "control plus s"
    mods = sorted({p for p in parts if p in _MODIFIERS}, key=_MODIFIERS.index)
    keys = [p for p in parts if p not in _MODIFIERS]
    if len(keys) != 1 or keys[0] not in _VK:
        raise ToolError(f"'{text}' is not a key combination I know.")
    combo = mods + keys
    if "+".join(combo) not in SHORTCUTS:
        raise ToolError(f"'{text}' is not on my list of permitted shortcuts. I may press: {', '.join(sorted(SHORTCUTS))}.")
    return combo


def press(combo: list[str]) -> None:
    codes = [_VK[k] for k in combo]
    _send([(vk, 0, 0) for vk in codes] + [(vk, 0, _KEYUP) for vk in reversed(codes)])


def type_out(text: str) -> None:
    # One character at a time, with a pause: sent as a flood, Windows 11's Notepad
    # kept 1 character of 30 (live test, 2026-11-15).
    for ch in text.replace("\r\n", "\n"):
        if ch == "\n":
            events = [(_VK["enter"], 0, 0), (_VK["enter"], 0, _KEYUP)]
        else:
            data = ch.encode("utf-16-le")  # characters outside the basic plane are two code units
            units = [int.from_bytes(data[i:i + 2], "little") for i in range(0, len(data), 2)]
            events = [(0, u, _UNICODE) for u in units] + [(0, u, _UNICODE | _KEYUP) for u in units]
        _send(events)
        time.sleep(_KEY_PAUSE)


# --------------------------------------------------------------------------- windows

_SW_MINIMIZE, _SW_MAXIMIZE, _SW_RESTORE = 6, 3, 9
_WM_CLOSE = 0x0010
_SKIP_PROCESSES = {"textinputhost", "applicationframehost", "systemsettings", "shellexperiencehost",
                   "searchhost", "startmenuexperiencehost", "lockapp"}


def _user32():
    return ctypes.windll.user32


def _pid(hwnd: int) -> int:
    pid = wintypes.DWORD()
    _user32().GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def _title(hwnd: int) -> str:
    length = _user32().GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(length + 1)
    _user32().GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def list_windows() -> list[dict[str, Any]]:
    """The programs' main windows that are on the taskbar: handle, title, program name, pid."""
    user32, found = _user32(), []
    ws_ex_toolwindow, gwl_exstyle, gw_owner = 0x80, -20, 4
    cloaked = wintypes.DWORD()

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def each(hwnd, _):
        if not user32.IsWindowVisible(hwnd) or user32.GetWindow(hwnd, gw_owner):
            return True
        if user32.GetWindowLongW(hwnd, gwl_exstyle) & ws_ex_toolwindow:
            return True
        title = _title(hwnd)
        if not title:
            return True
        try:  # windows on another virtual desktop, and suspended store apps, are "cloaked"
            ctypes.windll.dwmapi.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
            if cloaked.value:
                return True
        except OSError:
            pass
        pid = _pid(hwnd)
        try:
            name = psutil.Process(pid).name().lower().removesuffix(".exe")
        except psutil.Error:
            name = ""
        if name not in _SKIP_PROCESSES:
            found.append({"hwnd": hwnd, "title": title, "app": name, "pid": pid})
        return True

    user32.EnumWindows(each, 0)
    return found


def foreground() -> int:
    return _user32().GetForegroundWindow()


def _own(window_or_hwnd: Any) -> bool:
    pid = window_or_hwnd["pid"] if isinstance(window_or_hwnd, dict) else _pid(window_or_hwnd)
    return pid == os.getpid()


def match_windows(app: str) -> list[dict[str, Any]]:
    """Windows whose program name or title matches what the user called it."""
    wanted = (app or "").strip().lower().removesuffix(".exe")
    nicknames = {"vs code": "code", "vscode": "code", "visual studio code": "code", "edge": "msedge",
                 "file explorer": "explorer", "files": "explorer", "word": "winword", "powerpoint": "powerpnt",
                 "terminal": "windowsterminal", "antigravity": "antigravity ide"}
    wanted = nicknames.get(wanted, wanted)
    windows = list_windows()
    hits = [w for w in windows if wanted and (wanted in w["app"] or w["app"] in wanted)]
    return hits or [w for w in windows if wanted and wanted in w["title"].lower()]


def _target(app: str) -> dict[str, Any]:
    if (app or "").strip().lower() in ("", "this", "this window", "it", "current", "the current window"):
        hwnd = foreground()
        if not hwnd:
            raise ToolError("No window has the focus at the moment.")
        return {"hwnd": hwnd, "title": _title(hwnd), "app": "", "pid": _pid(hwnd)}
    hits = match_windows(app)
    if not hits:
        names = sorted({w["app"] for w in list_windows() if w["app"]})
        raise ToolError(f"No open window matches '{app}'. Open now: {', '.join(names) or 'nothing'}.")
    return hits[0]


def _work_area(hwnd: int) -> tuple[int, int, int, int]:
    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                    ("dwFlags", wintypes.DWORD)]

    info = MONITORINFO(ctypes.sizeof(MONITORINFO))
    _user32().GetMonitorInfoW(_user32().MonitorFromWindow(hwnd, 2), ctypes.byref(info))
    work = info.rcWork
    return work.left, work.top, work.right, work.bottom


def _place(hwnd: int, left: int, top: int, width: int, height: int) -> None:
    """Move a window so its *visible* frame fills the rectangle (Windows 10/11
    windows carry an invisible resize border of a few pixels on three sides)."""
    user32 = _user32()
    user32.ShowWindow(hwnd, _SW_RESTORE)
    outer, frame = wintypes.RECT(), wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(outer))
    try:
        ctypes.windll.dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(frame), ctypes.sizeof(frame))
        pad_l, pad_t = frame.left - outer.left, frame.top - outer.top
        pad_r, pad_b = outer.right - frame.right, outer.bottom - frame.bottom
    except OSError:
        pad_l = pad_t = pad_r = pad_b = 0
    if not all(0 <= p <= 20 for p in (pad_l, pad_t, pad_r, pad_b)):
        pad_l = pad_t = pad_r = pad_b = 0
    user32.SetWindowPos(hwnd, None, left - pad_l, top - pad_t, width + pad_l + pad_r, height + pad_t + pad_b, 0x0004 | 0x0010)


def focus(hwnd: int) -> None:
    user32 = _user32()
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, _SW_RESTORE)
    # Windows only lets a program take the foreground just after input; a tap of
    # Alt counts, and has no other effect.
    user32.keybd_event(0x12, 0, 0, 0)
    user32.keybd_event(0x12, 0, _KEYUP, 0)
    user32.SetForegroundWindow(hwnd)


def arrange(action: str, app: str = "") -> str:
    user32 = _user32()
    if action == "minimise_all":
        others = [w for w in list_windows() if not _own(w)]
        for w in others:
            user32.ShowWindow(w["hwnd"], _SW_MINIMIZE)
        return f"Minimised {len(others)} windows."
    window = _target(app)
    hwnd, name = window["hwnd"], window["app"] or window["title"][:40]
    if action in ("snap_left", "snap_right"):
        left, top, right, bottom = _work_area(hwnd)
        half = (right - left) // 2
        _place(hwnd, left if action == "snap_left" else left + half, top, half, bottom - top)
        focus(hwnd)
        return f"{name} is on the {'left' if action == 'snap_left' else 'right'} half of the screen."
    if action == "maximise":
        user32.ShowWindow(hwnd, _SW_MAXIMIZE)
        focus(hwnd)
        return f"{name} is maximised."
    if action == "minimise":
        user32.ShowWindow(hwnd, _SW_MINIMIZE)
        return f"{name} is minimised."
    if action in ("restore", "switch_to"):
        focus(hwnd)
        return f"{name} is in front."
    raise ToolError("Action must be snap_left, snap_right, maximise, minimise, restore, switch_to or minimise_all.")


def windows_to_close(app: str, except_for: str = "") -> list[dict[str, Any]]:
    everything = (app or "").strip().lower() in ("all", "everything", "all apps", "all windows", "")
    if everything and not except_for:
        raise ToolError("To close everything, say what to keep ('everything except Spotify'), or name the program.")
    keep = {w["hwnd"] for name in except_for.replace(" and ", ",").split(",") if name.strip() for w in match_windows(name)}
    chosen = list_windows() if everything else match_windows(app)
    chosen = [w for w in chosen if w["hwnd"] not in keep and not _own(w)]
    if not chosen:
        raise ToolError(f"No open window matches '{app}'." if not everything else "There is nothing else open to close.")
    return chosen


# --------------------------------------------------------------------------- tools

@ToolRegistry.register("type_text")
class TypeTextTool(SebasTool):
    name = "type_text"
    acts_on_laptop = True
    description = (
        "Type text into whichever program currently has the keyboard, as dictation: 'type this: ...'. "
        "Type exactly what the user dictated (tidy punctuation only); do not compose content unless asked."
    )
    parameters = {
        "type": "object",
        "properties": {"text": {"type": "string", "description": "The text to type. A line break presses Enter."}},
        "required": ["text"],
    }

    def run(self, text: str) -> str:
        if not text:
            raise ToolError("There was nothing to type.")
        if len(text) > _MAX_TYPED:
            raise ToolError(f"That is {len(text):,} characters; I type at most {_MAX_TYPED:,} at a time. "
                            "Put longer text on the clipboard for the user to paste.")
        hwnd = foreground()
        if not hwnd:
            raise ToolError("No window has the keyboard at the moment; click into the program first.")
        if _own(hwnd):
            raise ToolError("My own window has the keyboard. Click into the program you want the text in, "
                            "then ask by voice.")
        type_out(text)
        where = _title(hwnd)[:50]
        sebas_actions.log("type_text", f"{len(text)} characters into '{where}'")
        return f"Typed {len(text)} characters into '{where}'."


@ToolRegistry.register("arrange_windows")
class ArrangeWindowsTool(SebasTool):
    name = "arrange_windows"
    acts_on_laptop = True
    description = (
        "Arrange program windows: snap one to the left or right half of the screen, maximise, minimise, "
        "bring to the front (switch_to), or minimise everything. For two programs side by side, call it "
        "twice (snap_left, then snap_right). Leave app empty for the window in use."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["snap_left", "snap_right", "maximise", "minimise", "restore",
                                                  "switch_to", "minimise_all"]},
            "app": {"type": "string", "description": "The program's name, e.g. chrome, code, spotify. Empty: the current window."},
        },
        "required": ["action"],
    }

    def run(self, action: str, app: str = "") -> str:
        return arrange(action, app)


@ToolRegistry.register("close_apps")
class CloseAppsTool(SebasTool):
    name = "close_apps"
    risky = True
    description = (
        "Close a program's windows, or every window except some ('close everything except Spotify'). "
        "Each window is asked to close, as if its X were clicked, so unsaved work still prompts. "
        "Always needs the user's yes first."
    )
    parameters = {
        "type": "object",
        "properties": {
            "app": {"type": "string", "description": "The program to close, or 'everything'."},
            "except_for": {"type": "string", "description": "With 'everything': programs to keep, comma-separated."},
        },
        "required": ["app"],
    }

    def confirm_summary(self, app: str = "", except_for: str = "", **_: Any) -> str:
        try:
            chosen = windows_to_close(app, except_for)
        except ToolError as exc:
            return f"Close {app} (though: {exc})"
        names = sorted({w["app"] or w["title"][:30] for w in chosen})
        return f"Close {len(chosen)} window{'s' if len(chosen) != 1 else ''}: {', '.join(names)}."

    def run(self, app: str, except_for: str = "") -> str:
        chosen = windows_to_close(app, except_for)
        for w in chosen:
            _user32().PostMessageW(w["hwnd"], _WM_CLOSE, 0, 0)
        names = sorted({w["app"] or w["title"][:30] for w in chosen})
        return (f"Asked {len(chosen)} window{'s' if len(chosen) != 1 else ''} to close ({', '.join(names)}). "
                "Any with unsaved work will be asking whether to save.")


@ToolRegistry.register("press_keys")
class PressKeysTool(SebasTool):
    name = "press_keys"
    acts_on_laptop = True
    description = (
        "Press a keyboard shortcut in the program in use, from a fixed list: " + ", ".join(sorted(SHORTCUTS)) +
        ". ('win+shift+s' starts a screenshot snip.) Nothing else can be pressed."
    )
    parameters = {
        "type": "object",
        "properties": {
            "keys": {"type": "string", "description": "The combination, e.g. 'ctrl+s'."},
            "times": {"type": "integer", "description": "How many times (1-10, default 1)."},
        },
        "required": ["keys"],
    }

    def run(self, keys: str, times: int = 1) -> str:
        combo = parse_combo(keys)
        if _own(foreground()) and "win" not in combo and combo != ["alt", "tab"]:
            raise ToolError("My own window has the keyboard. Click into the program first, then ask by voice.")
        count = max(1, min(int(times or 1), 10))
        for _ in range(count):
            press(combo)
            time.sleep(0.05)
        return f"Pressed {'+'.join(combo)}" + (f" {count} times." if count > 1 else ".")
