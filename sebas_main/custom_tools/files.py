"""File hands: find, open, move, rename, zip and (after a yes) recycle files.

Where he may work: Downloads, Desktop, Documents, Pictures, Videos and Music,
plus any folders listed under [files] folders in laptop.toml. Every path is
resolved first and must lie inside one of those; nothing else can be touched.

How he works:
- Nothing is ever overwritten: a clash of names gets a numbered copy, "notes (2).pdf".
- Moves, renames, new folders and zips run at once and are logged; "undo that"
  reverses the last one.
- Deleting needs the user's yes (sebas_actions) and goes to the Recycle Bin.
- Programs and scripts are never opened, and unfinished downloads are left alone.
- Code projects are left alone: a folder from [projects], or any git repository,
  inside those folders is neither searched nor touched (that is the coding
  agent's ground), unless the user lists it under [files] folders.
"""

from __future__ import annotations

import ctypes
import fnmatch
import json
import os
import shutil
import time
import zipfile
from ctypes import wintypes
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from openjarvis.core.paths import get_data_dir
from openjarvis.core.registry import ToolRegistry

import sebas_actions
from custom_tools._base import SebasTool, ToolError
from custom_tools.assist import _free_name, known_folder
from custom_tools.laptop import _section

_ROOT_NAMES = ("downloads", "desktop", "documents", "pictures", "videos", "music")
_NEVER_OPEN = {".exe", ".msi", ".bat", ".cmd", ".ps1", ".vbs", ".js", ".jse", ".wsf", ".scr", ".com", ".lnk",
               ".reg", ".hta", ".cpl", ".jar", ".msix", ".appx"}
_IN_PROGRESS = {".crdownload", ".part", ".tmp", ".download", ".partial", ".opdownload"}
_SKIP_FOLDERS = {"node_modules", ".git", ".venv", "venv", "__pycache__", "$recycle.bin", "appdata"}
_MAX_FILES = 200           # in one action
_SEARCH_SECONDS = 8.0      # a search gives up politely rather than crawl a huge tree


# --------------------------------------------------------------------------- where he may work

def roots() -> dict[str, Path]:
    """The folders Sebas may work in, by spoken name."""
    found: dict[str, Path] = {}
    for name in _ROOT_NAMES:
        try:
            folder = known_folder(name)
        except (OSError, KeyError):
            continue
        if folder.is_dir():
            found[name] = folder.resolve()
    for extra in _section("files").get("folders", []):
        folder = Path(os.path.expandvars(str(extra))).expanduser()
        if folder.is_dir():
            found[folder.name.lower()] = folder.resolve()
    return found


def display(path: Path) -> str:
    """A path as it is said: 'Documents/College/notes.pdf'."""
    for name, root in roots().items():
        try:
            inner = path.resolve().relative_to(root)
        except ValueError:
            continue
        return "/".join([name.capitalize(), *inner.parts])
    return str(path)


def resolve(text: str, must_exist: bool = True) -> Path:
    """A spoken or written location -> a real path inside the allowed folders."""
    raw = (text or "").strip().strip('"').replace("\\", "/")
    if not raw:
        raise ToolError("No file or folder was named.")
    allowed = roots()
    first, _, rest = raw.partition("/")
    key = first.lower().removeprefix("my ").removesuffix(" folder")
    if key in allowed:
        path = allowed[key] / rest if rest else allowed[key]
    else:
        path = Path(os.path.expandvars(raw)).expanduser()
        if not path.is_absolute():
            raise ToolError(f"'{text}' should begin with one of: {', '.join(n.capitalize() for n in allowed)}; "
                            "or use find_files to look for it by name.")
    path = Path(os.path.abspath(path))
    real = path.resolve()  # follows links: a shortcut out of the folder does not get round the rule
    if not any(real == root or root in real.parents for root in allowed.values()):
        raise ToolError(f"{path} is outside the folders I may work in ({', '.join(n.capitalize() for n in allowed)}).")
    if in_project(real):
        raise ToolError(f"{display(path)} is inside a code project, which I leave alone. (The coding agent works "
                        "there; to let me handle its files, add the folder under [files] in laptop.toml.)")
    if must_exist and not path.exists():
        raise ToolError(f"There is nothing at {display(path)}.")
    return path


def _project_folders() -> list[Path]:
    return [Path(str(p)).expanduser().resolve() for p in _section("projects").values()]


def in_project(real: Path) -> bool:
    """True inside a folder from [projects], or inside any git repository, that lies
    within an allowed folder (Desktop often holds projects). A folder the user
    listed under [files] is theirs to open up, repository or not."""
    allowed = set(roots().values())
    projects = _project_folders()
    for folder in [real, *real.parents]:
        if folder in allowed:
            return False
        if folder in projects or (folder / ".git").exists():
            return True
    return False


def _is_root(path: Path) -> bool:
    return path.resolve() in roots().values()


def _select(source: str, pattern: str) -> list[Path]:
    """The files an action applies to: one file or folder, or a folder's files matching a pattern."""
    path = resolve(source)
    pattern = (pattern or "").strip().lower()
    if pattern:
        if not path.is_dir():
            raise ToolError(f"A pattern needs a folder to look in, and {display(path)} is a file.")
        if not any(ch in pattern for ch in "*?"):
            pattern = f"*{pattern}*"
        chosen = [p for p in sorted(path.iterdir())
                  if p.is_file() and fnmatch.fnmatch(p.name.lower(), pattern) and p.suffix.lower() not in _IN_PROGRESS
                  and p.name.lower() != "desktop.ini"]
        if not chosen:
            raise ToolError(f"No files in {display(path)} match '{pattern}'.")
    else:
        if _is_root(path):
            raise ToolError(f"{display(path)} itself cannot be moved, renamed or deleted; name what is inside it, "
                            "or give a pattern such as *.pdf.")
        chosen = [path]
    if len(chosen) > _MAX_FILES:
        raise ToolError(f"That is {len(chosen)} files; I handle at most {_MAX_FILES} at a time. Narrow the pattern.")
    return chosen


# --------------------------------------------------------------------------- undo

def _undo_path() -> Path:
    return get_data_dir() / "sebas" / "files_undo.json"


def _remember(kind: str, steps: list[list[str]]) -> None:
    """``steps``: [now, before] pairs for moves; [created] for folders and zips."""
    path = _undo_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"kind": kind, "when": datetime.now().isoformat(timespec="minutes"), "steps": steps},
                               indent=1), "utf-8")


# --------------------------------------------------------------------------- the actions

def find(query: str, folder: str = "", limit: int = 10) -> list[Path]:
    words = [w for w in (query or "").lower().replace("_", " ").replace("-", " ").split() if w]
    if not words:
        raise ToolError("Say what to look for: part of the file's name.")
    starts = [resolve(folder)] if folder else list(dict.fromkeys(roots().values()))
    deadline, scored = time.monotonic() + _SEARCH_SECONDS, []
    projects = _project_folders()
    for start in starts:
        for here, folders, names in os.walk(start):
            folders[:] = [f for f in folders if f.lower() not in _SKIP_FOLDERS and not f.startswith(".")
                          and not (Path(here) / f / ".git").exists() and (Path(here) / f).resolve() not in projects]
            for name in names + folders:
                plain = name.lower().replace("_", " ").replace("-", " ")
                hits = sum(w in plain for w in words)
                if not hits:
                    continue
                score = hits / len(words) + 0.3 * SequenceMatcher(None, " ".join(words), Path(plain).stem).ratio()
                scored.append((score, Path(here) / name))
            if time.monotonic() > deadline:
                break
    if not scored:
        return []
    best = max(s for s, _ in scored)

    def modified(p: Path) -> float:
        try:
            return p.stat().st_mtime
        except OSError:
            return 0.0

    near = sorted((p for s, p in scored if s >= best - 0.25), key=modified, reverse=True)
    return near[:limit]


def move(source: str, destination: str, pattern: str = "") -> str:
    chosen = _select(source, pattern)
    target = resolve(destination, must_exist=False)
    if target.exists() and not target.is_dir():
        raise ToolError(f"{display(target)} is a file; name a folder to move into.")
    if any(target == p or p in target.parents for p in chosen):
        raise ToolError("A folder cannot be moved into itself.")
    target.mkdir(parents=True, exist_ok=True)
    steps = []
    for item in chosen:
        if item.parent == target:
            continue
        final = _free_name(target / item.name)
        shutil.move(str(item), str(final))
        steps.append([str(final), str(item)])
    if not steps:
        return f"Those are already in {display(target)}."
    _remember("move", steps)
    names = ", ".join(Path(s[0]).name for s in steps[:3]) + ("..." if len(steps) > 3 else "")
    return f"Moved {len(steps)} item{'s' if len(steps) != 1 else ''} to {display(target)}: {names}. 'Undo that' puts them back."


def rename(source: str, new_name: str) -> str:
    item = _select(source, "")[0]
    new_name = (new_name or "").strip().strip('"')
    if not new_name or any(ch in new_name for ch in '\\/:*?"<>|'):
        raise ToolError("The new name must be a plain name, without slashes or the characters : * ? \" < > |.")
    if item.is_file() and not Path(new_name).suffix:
        new_name += item.suffix  # "rename it to report" keeps the .pdf
    final = _free_name(item.with_name(new_name))
    item.rename(final)
    _remember("rename", [[str(final), str(item)]])
    return f"Renamed {item.name} to {final.name}, in {display(final.parent)}."


def make_folder(location: str) -> str:
    folder = resolve(location, must_exist=False)
    if folder.exists():
        return f"{display(folder)} already exists."
    first_new = next(p for p in [*reversed(folder.parents), folder] if not p.exists())
    folder.mkdir(parents=True)
    _remember("folder", [[str(first_new)]])
    return f"Created the folder {display(folder)}."


def make_zip(source: str, pattern: str = "") -> str:
    chosen = _select(source, pattern)
    base = chosen[0] if len(chosen) == 1 else resolve(source)
    archive = _free_name(base.parent / f"{base.stem if base.is_file() else base.name}.zip") if len(chosen) == 1 \
        else _free_name(base / f"{base.name}.zip")
    count = 0
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in chosen:
            if item.is_dir():
                for here, folders, names in os.walk(item):
                    folders[:] = [f for f in folders if f.lower() not in _SKIP_FOLDERS]
                    for name in names:
                        full = Path(here) / name
                        zf.write(full, full.relative_to(item.parent))
                        count += 1
            else:
                zf.write(item, item.name)
                count += 1
    _remember("zip", [[str(archive)]])
    return f"Zipped {count} file{'s' if count != 1 else ''} into {display(archive)} ({archive.stat().st_size / 2**20:.1f} MB)."


def recycle(paths: list[Path]) -> None:
    """Send files or folders to the Recycle Bin (never a permanent delete)."""

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR),
                    ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]

    fo_delete, allow_undo, no_confirm, silent, no_error_ui = 0x3, 0x40, 0x10, 0x4, 0x400
    op = SHFILEOPSTRUCTW(None, fo_delete, "\0".join(str(p) for p in paths) + "\0\0", None,
                         allow_undo | no_confirm | silent | no_error_ui, False, None, None)
    code = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if code or op.fAnyOperationsAborted:
        raise ToolError(f"Windows could not move everything to the Recycle Bin (code {code}).")


def undo_last() -> str:
    path = _undo_path()
    if not path.exists():
        raise ToolError("There is no file action to undo.")
    record = json.loads(path.read_text("utf-8"))
    path.unlink()
    if record["kind"] in ("move", "rename"):
        back = missing = 0
        for now, before in record["steps"]:
            if Path(now).exists():
                Path(before).parent.mkdir(parents=True, exist_ok=True)
                shutil.move(now, str(_free_name(Path(before))))
                back += 1
            else:
                missing += 1
        return f"Put back {back} item{'s' if back != 1 else ''}" + (f"; {missing} had since been moved or deleted." if missing else ".")
    created = Path(record["steps"][0][0])
    if not created.exists():
        return f"{created.name} is already gone."
    if record["kind"] == "folder":
        if any(p.is_file() for p in created.rglob("*")):
            raise ToolError(f"{display(created)} now has files in it, so I have left it.")
        shutil.rmtree(created)
        return f"Removed the folder {created.name}."
    recycle([created])  # a zip he made
    return f"Removed {created.name} (it is in the Recycle Bin)."


# --------------------------------------------------------------------------- tools

@ToolRegistry.register("find_files")
class FindFilesTool(SebasTool):
    name = "find_files"
    description = (
        "Find the user's files or folders by name ('find my DBMS assignment'), in Downloads, Desktop, "
        "Documents, Pictures, Videos and Music. Returns up to ten, newest first, as paths the other "
        "file tools accept."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Words from the file's name."},
            "folder": {"type": "string", "description": "Limit the search to one folder, e.g. 'Documents/College'. Optional."},
        },
        "required": ["query"],
    }

    def run(self, query: str, folder: str = "") -> str:
        found = find(query, folder)
        if not found:
            return f"Nothing with '{query}' in its name was found."
        lines = []
        for p in found:
            try:
                when = datetime.fromtimestamp(p.stat().st_mtime).strftime("%d %b %Y")
            except OSError:
                when = "?"
            lines.append(f"- {display(p)}{'/' if p.is_dir() else ''} ({when})")
        return "\n".join(lines)


@ToolRegistry.register("open_file")
class OpenFileTool(SebasTool):
    name = "open_file"
    acts_on_laptop = True
    description = "Open one of the user's files or folders in its usual program. Programs and scripts are not opened."
    parameters = {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "A path as find_files gives it, e.g. 'Documents/College/notes.pdf'."}},
        "required": ["path"],
    }

    def run(self, path: str) -> str:
        target = resolve(path)
        if target.is_file() and target.suffix.lower() in _NEVER_OPEN:
            raise ToolError(f"{target.name} is a program or script; I do not run those. Open it yourself if you trust it.")
        os.startfile(str(target))  # type: ignore[attr-defined]
        return f"Opened {display(target)}."


@ToolRegistry.register("manage_files")
class ManageFilesTool(SebasTool):
    name = "manage_files"
    acts_on_laptop = True
    timeout_seconds = 120.0
    description = (
        "Move, rename, zip or create folders among the user's files. action 'move': source (a file, a "
        "folder, or a folder plus pattern such as *.pdf) into the folder 'destination' (created if "
        "missing). 'rename': source to new_name. 'make_folder': create 'destination'. 'zip': source "
        "(optionally with pattern) into a .zip beside it. Paths begin with Downloads, Desktop, Documents, "
        "Pictures, Videos or Music. Nothing is overwritten, and undo_file_action reverses the last action."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["move", "rename", "make_folder", "zip"]},
            "source": {"type": "string", "description": "The file or folder to act on."},
            "destination": {"type": "string", "description": "Folder to move into, or folder to create."},
            "pattern": {"type": "string", "description": "With a folder as source: which files in it, e.g. *.pdf or 'invoice'."},
            "new_name": {"type": "string", "description": "For rename: the new name (the extension is kept if omitted)."},
        },
        "required": ["action"],
    }

    def run(self, action: str, source: str = "", destination: str = "", pattern: str = "", new_name: str = "") -> str:
        try:
            if action == "move":
                result = move(source, destination, pattern)
            elif action == "rename":
                result = rename(source, new_name)
            elif action == "make_folder":
                result = make_folder(destination or source)
            elif action == "zip":
                result = make_zip(source, pattern)
            else:
                raise ToolError("Action must be move, rename, make_folder or zip.")
        except OSError as exc:
            raise ToolError(f"Windows refused: {exc.strerror or exc}. The file may be open in another program.") from exc
        sebas_actions.log(f"files.{action}", result)
        return result


@ToolRegistry.register("delete_files")
class DeleteFilesTool(SebasTool):
    name = "delete_files"
    risky = True
    description = (
        "Send the user's files or folders to the Recycle Bin: one file or folder, or a folder's files "
        "matching a pattern. Always needs the user's yes first."
    )
    parameters = {
        "type": "object",
        "properties": {
            "source": {"type": "string", "description": "The file or folder; begins with Downloads, Desktop, Documents..."},
            "pattern": {"type": "string", "description": "With a folder as source: which files in it, e.g. *.exe."},
        },
        "required": ["source"],
    }

    def confirm_summary(self, source: str = "", pattern: str = "", **_: Any) -> str:
        try:
            chosen = _select(source, pattern)
        except ToolError as exc:
            return f"Delete from {source} (though: {exc})"
        names = ", ".join(p.name for p in chosen[:4]) + (f" and {len(chosen) - 4} more" if len(chosen) > 4 else "")
        return f"Send {len(chosen)} item{'s' if len(chosen) != 1 else ''} from {display(chosen[0].parent)} to the Recycle Bin: {names}."

    def run(self, source: str, pattern: str = "") -> str:
        chosen = _select(source, pattern)
        recycle(chosen)
        return (f"Sent {len(chosen)} item{'s' if len(chosen) != 1 else ''} to the Recycle Bin, "
                "where they can still be restored.")


@ToolRegistry.register("undo_file_action")
class UndoFileActionTool(SebasTool):
    name = "undo_file_action"
    acts_on_laptop = True
    description = (
        "Reverse the last move, rename, new folder or zip made with manage_files. (Deleted files are "
        "restored from the Recycle Bin by the user; a Downloads tidy is undone with undo_tidy.)"
    )

    def run(self) -> str:
        try:
            result = undo_last()
        except OSError as exc:
            raise ToolError(f"Windows refused: {exc.strerror or exc}.") from exc
        sebas_actions.log("files.undo", result)
        return result
