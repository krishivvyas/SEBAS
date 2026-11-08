"""Help with what is on the laptop: the screen, the clipboard, and the Downloads folder.

- look_at_screen: a screenshot, taken only when asked, described by Gemini's
  vision. The image goes to Google; nothing is captured in the background.
- clipboard: read the copied text (Sebas then summarises, translates or
  explains it), or put text on the clipboard for pasting.
- tidy_downloads: sort the Downloads folder into category folders. It always
  shows the plan first and moves nothing until called again with confirm=true;
  undo_tidy puts everything back.
"""

from __future__ import annotations

import ctypes
import io
import json
import os
import shutil
import time
import uuid
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

from openjarvis.core.paths import get_data_dir
from openjarvis.core.registry import ToolRegistry

from custom_tools._base import SebasTool, ToolError

# --------------------------------------------------------------------------- known folders

_FOLDER_IDS = {
    "downloads": "{374DE290-123F-4565-9164-39C4925E467B}",
    "documents": "{FDD39AD0-238F-46AF-ADB4-6C85480369C7}",
}


def known_folder(name: str) -> Path:
    """The real Downloads/Documents folder, wherever Windows (or OneDrive) put it."""

    class GUID(ctypes.Structure):
        _fields_ = [("d1", wintypes.DWORD), ("d2", wintypes.WORD), ("d3", wintypes.WORD), ("d4", ctypes.c_ubyte * 8)]

    guid = GUID()
    ctypes.oledll.ole32.CLSIDFromString(_FOLDER_IDS[name], ctypes.byref(guid))
    path = ctypes.c_wchar_p()
    ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(path))
    try:
        return Path(path.value)
    finally:
        ctypes.windll.ole32.CoTaskMemFree(path)


# --------------------------------------------------------------------------- screen

def gemini_once(contents: list, *, need: str, timeout_ms: int = 40_000, json_mode: bool = False) -> str:
    """One stand-alone Gemini request (outside the conversation), trying each key
    and model in turn like the brain does. ``need`` names the task for errors."""
    from google import genai

    from sebas_brain import choose_gemini_models, choose_lite_models, classify_failure

    keys = [k for k in (os.environ.get("GEMINI_API_KEY", ""), os.environ.get("GEMINI_API_KEY_2", "")) if k.strip()]
    if not keys:
        raise ToolError(f"{need} needs a Gemini key; the local model cannot do it.")
    last = None
    for key in keys:
        client = genai.Client(api_key=key, http_options={"timeout": timeout_ms})
        # Flash first, then Flash-Lite (far higher free limits) once Flash is spent
        for model in choose_gemini_models(key) + choose_lite_models(key):
            try:
                config = {"response_mime_type": "application/json"} if json_mode else None
                reply = client.models.generate_content(model=model, contents=contents, config=config)
                return (reply.text or "").strip()
            except Exception as exc:  # quota, overload: try the next model, then the next key
                if classify_failure(exc) is None:
                    raise
                last = exc
    raise ToolError(f"Every Gemini model is busy or out of quota right now ({type(last).__name__}).")


def gemini_vision(image_png: bytes, prompt: str) -> str:
    from google.genai import types

    image = types.Part.from_bytes(data=image_png, mime_type="image/png")
    return gemini_once([image, prompt], need="Reading the screen") or "The screen could not be described."


def screenshot_png(max_side: int = 1600) -> bytes:
    from PIL import ImageGrab

    image = ImageGrab.grab(all_screens=False)
    image.thumbnail((max_side, max_side))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


@ToolRegistry.register("look_at_screen")
class LookAtScreenTool(SebasTool):
    name = "look_at_screen"
    acts_on_laptop = True  # the screen is private: from Discord it needs a yes
    description = (
        "Take a screenshot of the laptop's main screen and describe it, answering the "
        "user's question about it: an error message, a chart, a form, some code. Only "
        "use it when the user asks about what is on the screen."
    )
    parameters = {
        "type": "object",
        "properties": {"question": {"type": "string", "description": "What the user wants to know about the screen."}},
        "required": ["question"],
    }
    timeout_seconds = 120.0

    def run(self, question: str) -> str:
        prompt = (
            "This is a screenshot of the user's laptop. Answer their question about it precisely and "
            "briefly; quote any error message exactly, and suggest a fix if it is an error.\n"
            f"Question: {question}"
        )
        return gemini_vision(screenshot_png(), prompt)


# --------------------------------------------------------------------------- clipboard

_CF_UNICODETEXT = 13
_GMEM_MOVEABLE = 0x0002


def _clipboard_api():
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    user32.GetClipboardData.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    return user32, kernel32


def _open_clipboard(user32) -> None:
    for _ in range(10):  # another program may hold it for a moment
        if user32.OpenClipboard(None):
            return
        time.sleep(0.05)
    raise ToolError("The clipboard is busy; please try again.")


def read_clipboard() -> str:
    user32, kernel32 = _clipboard_api()
    _open_clipboard(user32)
    try:
        handle = user32.GetClipboardData(_CF_UNICODETEXT)
        if not handle:
            return ""
        pointer = kernel32.GlobalLock(handle)
        try:
            return ctypes.wstring_at(pointer)
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def write_clipboard(text: str) -> None:
    user32, kernel32 = _clipboard_api()
    data = ctypes.create_unicode_buffer(text)
    size = ctypes.sizeof(data)
    handle = kernel32.GlobalAlloc(_GMEM_MOVEABLE, size)
    pointer = kernel32.GlobalLock(handle)
    ctypes.memmove(pointer, data, size)
    kernel32.GlobalUnlock(handle)
    _open_clipboard(user32)
    try:
        user32.EmptyClipboard()
        if not user32.SetClipboardData(_CF_UNICODETEXT, handle):
            raise ToolError("Windows would not accept the clipboard text.")
    finally:
        user32.CloseClipboard()


@ToolRegistry.register("clipboard")
class ClipboardTool(SebasTool):
    name = "clipboard"
    acts_on_laptop = True
    description = (
        "Read the text the user has copied (action 'read'), so you can summarise, translate, "
        "explain or proofread it; or put text on the clipboard (action 'write') so the user "
        "can paste it, e.g. a translation or a corrected version."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["read", "write"]},
            "text": {"type": "string", "description": "The text to copy (write only)."},
        },
        "required": ["action"],
    }

    def run(self, action: str, text: str = "") -> str:
        if action == "read":
            copied = read_clipboard()
            if not copied.strip():
                raise ToolError("The clipboard has no text in it (perhaps an image or a file was copied).")
            if len(copied) > 20_000:
                return f"(The clipboard holds {len(copied):,} characters; here are the first 20,000.)\n{copied[:20_000]}"
            return copied
        if action == "write":
            if not text:
                raise ToolError("There was no text to copy.")
            write_clipboard(text)
            return f"Copied {len(text):,} characters to the clipboard."
        raise ToolError("Action must be read or write.")


# --------------------------------------------------------------------------- Downloads

CATEGORIES = {
    "Documents": {".pdf", ".doc", ".docx", ".odt", ".rtf", ".txt", ".md", ".xls", ".xlsx", ".csv", ".ppt", ".pptx", ".epub"},
    "Images": {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".heic", ".ico", ".tif", ".tiff"},
    "Videos": {".mp4", ".mkv", ".mov", ".avi", ".webm", ".wmv"},
    "Audio": {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac"},
    "Archives": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"},
    "Installers": {".exe", ".msi", ".msix", ".appx", ".apk", ".dmg", ".iso"},
    "Code": {".py", ".js", ".ts", ".json", ".html", ".css", ".java", ".c", ".cpp", ".ipynb", ".sql", ".sh", ".bat", ".ps1"},
}
_IN_PROGRESS = {".crdownload", ".part", ".tmp", ".download", ".partial"}
_RECENT_SECONDS = 10 * 60


def _category(path: Path) -> str:
    ext = path.suffix.lower()
    return next((name for name, exts in CATEGORIES.items() if ext in exts), "Other")


def plan_tidy(folder: Path) -> list[tuple[Path, Path]]:
    """(source, destination) for every loose file that should move."""
    moves = []
    now = time.time()
    for item in sorted(folder.iterdir()):
        if not item.is_file() or item.name.startswith(".") or item.name.lower() == "desktop.ini":
            continue
        if item.suffix.lower() in _IN_PROGRESS or now - item.stat().st_mtime < _RECENT_SECONDS:
            continue  # still downloading, or just arrived: leave it
        moves.append((item, folder / _category(item) / item.name))
    return moves


def _free_name(target: Path) -> Path:
    n = 2
    candidate = target
    while candidate.exists():
        candidate = target.with_name(f"{target.stem} ({n}){target.suffix}")
        n += 1
    return candidate


def _undo_log() -> Path:
    return get_data_dir() / "sebas" / "tidy_undo.json"


@ToolRegistry.register("tidy_downloads")
class TidyDownloadsTool(SebasTool):
    name = "tidy_downloads"
    acts_on_laptop = True
    description = (
        "Sort the loose files in the Downloads folder into Documents, Images, Videos, Audio, "
        "Archives, Installers, Code and Other folders. Call it first WITHOUT confirm to get "
        "the plan, tell the user, and call again with confirm=true only after they agree. "
        "Files from the last ten minutes and unfinished downloads are left alone."
    )
    parameters = {
        "type": "object",
        "properties": {"confirm": {"type": "boolean", "description": "true only after the user approved the plan."}},
    }

    def run(self, confirm: bool = False) -> str:
        folder = Path(os.environ.get("SEBAS_DOWNLOADS_DIR") or known_folder("downloads"))
        moves = plan_tidy(folder)
        if not moves:
            return "The Downloads folder is already tidy; there are no loose files to sort."
        counts: dict[str, int] = {}
        for _, dest in moves:
            counts[dest.parent.name] = counts.get(dest.parent.name, 0) + 1
        summary = ", ".join(f"{n} to {c}" for c, n in sorted(counts.items(), key=lambda kv: -kv[1]))
        if not confirm:
            return (f"Plan for {folder}: move {len(moves)} files ({summary}). Nothing has been moved yet; "
                    "ask the user, and call again with confirm=true if they agree.")
        done = []
        for source, dest in moves:
            dest.parent.mkdir(exist_ok=True)
            final = _free_name(dest)
            shutil.move(str(source), str(final))
            done.append([str(final), str(source)])
        log = _undo_log()
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(json.dumps({"id": uuid.uuid4().hex[:8], "when": datetime.now().isoformat(timespec="minutes"),
                                   "moves": done}, indent=1), "utf-8")
        return f"Moved {len(done)} files ({summary}). If that was a mistake, undo_tidy puts them back."


@ToolRegistry.register("undo_tidy")
class UndoTidyTool(SebasTool):
    name = "undo_tidy"
    acts_on_laptop = True
    description = "Put back the files moved by the last Downloads tidy."

    def run(self) -> str:
        log = _undo_log()
        if not log.exists():
            raise ToolError("There is no tidy to undo.")
        record = json.loads(log.read_text("utf-8"))
        restored = missing = 0
        for moved_to, original in record["moves"]:
            if Path(moved_to).exists():
                shutil.move(moved_to, str(_free_name(Path(original))))
                restored += 1
            else:
                missing += 1
        log.unlink()
        for folder in {Path(m).parent for m, _ in record["moves"]}:  # remove category folders left empty
            try:
                folder.rmdir()
            except OSError:
                pass
        return f"Put back {restored} files" + (f"; {missing} had since been moved or deleted." if missing else ".")
