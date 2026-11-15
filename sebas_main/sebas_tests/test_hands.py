"""File hands and desk hands. Files are exercised on a temporary folder standing in
for Downloads and Documents (the Recycle Bin is replaced by a list); typing and
windows use stand-ins for the keyboard and the window list, so nothing on the real
desktop is touched."""

from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sebas_bootstrap import load_env  # noqa: E402

load_env()

import sebas_actions  # noqa: E402
from custom_tools import desk, files  # noqa: E402
from custom_tools._base import ToolError  # noqa: E402


class _Patched(unittest.TestCase):
    def patch(self, target, name, value):
        p = mock.patch.object(target, name, value)
        p.start()
        self.addCleanup(p.stop)

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name).resolve()
        self.patch(sebas_actions, "get_data_dir", lambda: self.home / "data")
        sebas_actions.answer("drop anything left over")


class Files(_Patched):
    def setUp(self):
        super().setUp()
        self.downloads, self.documents = self.home / "Downloads", self.home / "Documents"
        for folder in (self.downloads, self.documents / "College"):
            folder.mkdir(parents=True)
        for name in ("dbms_assignment_final.pdf", "invoice-march.pdf", "setup.exe", "holiday.jpg", "movie.mkv.crdownload"):
            (self.downloads / name).write_text(name)
        (self.documents / "College" / "DBMS notes.txt").write_text("notes")
        (self.home / "secret.txt").write_text("outside")
        self.binned: list[Path] = []
        self.patch(files, "roots", lambda: {"downloads": self.downloads, "documents": self.documents})
        self.patch(files, "get_data_dir", lambda: self.home / "data")
        self.patch(files, "recycle", lambda paths: [self.binned.append(p) or p.unlink() for p in paths])

    def manage(self, **kw):
        return files.ManageFilesTool().run_now(**kw)

    def test_only_the_allowed_folders(self):
        self.assertEqual(files.resolve("Downloads/holiday.jpg"), self.downloads / "holiday.jpg")
        self.assertEqual(files.resolve("my documents folder"), self.documents)
        self.assertEqual(files.display(self.documents / "College" / "DBMS notes.txt"), "Documents/College/DBMS notes.txt")
        for bad in (str(self.home / "secret.txt"), "Downloads/../secret.txt", "C:\\Windows\\System32\\drivers", "notes.txt"):
            with self.assertRaises(ToolError, msg=bad):
                files.resolve(bad)
        self.assertFalse(self.manage(action="move", source="Downloads/holiday.jpg", destination=str(self.home / "elsewhere")).success)
        self.assertTrue((self.downloads / "holiday.jpg").exists())

    def test_code_projects_are_left_alone(self):
        repo = self.documents / "portfolio"
        (repo / ".git").mkdir(parents=True)
        (repo / "src").mkdir()
        (repo / "src" / "dbms_helper.py").write_text("code")
        listed = self.documents / "listed-project"
        listed.mkdir()
        (listed / "dbms_model.py").write_text("code")
        self.patch(files, "_section", lambda name: {"projects": {"listed": str(listed)}}.get(name, {}))
        found = files.FindFilesTool().run_now(query="dbms").content
        self.assertNotIn("dbms_helper", found)
        self.assertNotIn("dbms_model", found)
        for inside in ("Documents/portfolio/src/dbms_helper.py", "Documents/portfolio", "Documents/listed-project/dbms_model.py"):
            with self.assertRaises(ToolError, msg=inside):
                files.resolve(inside)
        self.assertFalse(self.manage(action="move", source="Downloads/holiday.jpg", destination="Documents/portfolio/src").success)
        self.assertFalse(files.DeleteFilesTool().run_now(source="Documents/portfolio/src/dbms_helper.py").success)

    def test_find_by_loose_name(self):
        listed = files.FindFilesTool().run_now(query="DBMS assignment").content
        self.assertTrue(listed.startswith("- Downloads/dbms_assignment_final.pdf"), listed)
        self.assertIn("Documents/College/DBMS notes.txt", files.FindFilesTool().run_now(query="dbms").content)
        self.assertIn("Nothing", files.FindFilesTool().run_now(query="secret").content)  # outside the folders
        self.assertIn("Nothing", files.FindFilesTool().run_now(query="zzzz").content)

    def test_move_by_pattern_never_overwrites_and_undoes(self):
        (self.documents / "College" / "invoice-march.pdf").write_text("already here")
        result = self.manage(action="move", source="Downloads", pattern="*.pdf", destination="Documents/College")
        self.assertTrue(result.success, result.content)
        self.assertIn("Moved 2 items to Documents/College", result.content)
        college = self.documents / "College"
        self.assertEqual((college / "invoice-march.pdf").read_text(), "already here")  # not overwritten
        self.assertEqual((college / "invoice-march (2).pdf").read_text(), "invoice-march.pdf")
        self.assertFalse((self.downloads / "dbms_assignment_final.pdf").exists())
        self.assertIn("Put back 2 items", files.UndoFileActionTool().run_now().content)
        self.assertTrue((self.downloads / "dbms_assignment_final.pdf").exists())
        self.assertTrue((self.downloads / "invoice-march.pdf").exists())
        self.assertFalse(files.UndoFileActionTool().run_now().success)  # one undo only

    def test_unfinished_downloads_and_whole_folders_are_left_alone(self):
        result = self.manage(action="move", source="Downloads", pattern="movie", destination="Documents")
        self.assertFalse(result.success)  # the only match is still downloading
        self.assertFalse(self.manage(action="move", source="Downloads", destination="Documents").success)
        self.assertFalse(files.DeleteFilesTool().run_now(source="Documents").success)

    def test_rename_keeps_the_extension(self):
        self.assertIn("to report.pdf", self.manage(action="rename", source="Downloads/invoice-march.pdf", new_name="report").content)
        self.assertTrue((self.downloads / "report.pdf").exists())
        self.assertFalse(self.manage(action="rename", source="Downloads/report.pdf", new_name="../../x.pdf").success)
        files.UndoFileActionTool().run_now()
        self.assertTrue((self.downloads / "invoice-march.pdf").exists())

    def test_make_folder_and_zip(self):
        self.assertIn("Created the folder Documents/College/Sem 5/DBMS",
                      self.manage(action="make_folder", destination="Documents/College/Sem 5/DBMS").content)
        self.assertIn("Removed the folder Sem 5", files.UndoFileActionTool().run_now().content)
        self.assertFalse((self.documents / "College" / "Sem 5").exists())
        result = self.manage(action="zip", source="Downloads", pattern="*.pdf")
        self.assertIn("Zipped 2 files into Downloads/Downloads.zip", result.content)
        with zipfile.ZipFile(self.downloads / "Downloads.zip") as zf:
            self.assertEqual(sorted(zf.namelist()), ["dbms_assignment_final.pdf", "invoice-march.pdf"])
        self.assertIn("Zipped 1 file into Documents/College.zip", self.manage(action="zip", source="Documents/College").content)

    def test_programs_are_not_opened(self):
        opened = []
        self.patch(files.os, "startfile", opened.append)
        self.assertFalse(files.OpenFileTool().run_now(path="Downloads/setup.exe").success)
        self.assertTrue(files.OpenFileTool().run_now(path="Downloads/holiday.jpg").success)
        self.assertEqual(opened, [str(self.downloads / "holiday.jpg")])

    def test_delete_waits_for_a_yes_and_goes_to_the_bin(self):
        parked = files.DeleteFilesTool().execute(source="Downloads", pattern="*.exe")
        self.assertIn("NOT DONE YET", parked.content)
        self.assertIn("Send 1 item from Downloads to the Recycle Bin: setup.exe", sebas_actions.pending_summary())
        self.assertTrue((self.downloads / "setup.exe").exists())
        self.assertIn("Recycle Bin", sebas_actions.answer("yes"))
        self.assertEqual(self.binned, [self.downloads / "setup.exe"])


def _window(hwnd, app, title, pid=100):
    return {"hwnd": hwnd, "app": app, "title": title, "pid": pid}


class Desk(_Patched):
    def setUp(self):
        super().setUp()
        self.keys: list[tuple[int, int, int]] = []
        self.windows = [_window(1, "chrome", "Inbox - Google Chrome"), _window(2, "code", "sebas - Visual Studio Code"),
                        _window(3, "spotify", "Spotify Premium"), _window(4, "python", "Sebas", pid=desk.os.getpid())]
        self.front = {"hwnd": 1}
        self.patch(desk, "_send", self.keys.extend)
        self.patch(desk, "list_windows", lambda: list(self.windows))
        self.patch(desk, "foreground", lambda: self.front["hwnd"])
        self.patch(desk, "_pid", lambda hwnd: next(w["pid"] for w in self.windows if w["hwnd"] == hwnd))
        self.patch(desk, "_title", lambda hwnd: next(w["title"] for w in self.windows if w["hwnd"] == hwnd))
        self.patch(desk.time, "sleep", lambda s: None)

    def test_dictation_types_every_character(self):
        result = desk.TypeTextTool().run_now(text="Hi, ₹5\nok")
        self.assertTrue(result.success, result.content)
        self.assertIn("Inbox - Google Chrome", result.content)
        downs = [(vk, scan) for vk, scan, flags in self.keys if not flags & desk._KEYUP]
        self.assertEqual(downs, [(0, ord(c)) for c in "Hi, ₹5"] + [(desk._VK["enter"], 0)] + [(0, ord(c)) for c in "ok"])
        self.assertEqual(len(self.keys), 2 * len(downs))  # every key is released

    def test_dictation_refuses_sebas_own_window_and_long_text(self):
        self.front["hwnd"] = 4
        self.assertFalse(desk.TypeTextTool().run_now(text="hello").success)
        self.front["hwnd"] = 1
        self.assertFalse(desk.TypeTextTool().run_now(text="x" * 3000).success)
        self.assertEqual(self.keys, [])

    def test_only_listed_shortcuts(self):
        self.assertEqual(desk.parse_combo("Ctrl+S"), ["ctrl", "s"])
        self.assertEqual(desk.parse_combo("control plus shift plus T"), ["ctrl", "shift", "t"])
        self.assertEqual(desk.parse_combo("shift + windows + s"), ["win", "shift", "s"])
        self.assertEqual(desk.parse_combo("page down"), ["pagedown"])
        self.assertEqual(desk.parse_combo("ctrl+="), ["ctrl", "plus"])
        self.assertEqual(desk.parse_combo("control plus plus"), ["ctrl", "plus"])
        for refused in ("alt+f4", "win+l", "win+r", "ctrl+alt+delete", "win+x", "ctrl+shift+escape", "shift+delete", "nonsense"):
            with self.assertRaises(ToolError, msg=refused):
                desk.parse_combo(refused)
        self.assertIn("Pressed ctrl+s", desk.PressKeysTool().run_now(keys="ctrl+s").content)
        self.assertEqual(self.keys, [(0x11, 0, 0), (0x53, 0, 0), (0x53, 0, desk._KEYUP), (0x11, 0, desk._KEYUP)])
        self.assertFalse(desk.PressKeysTool().run_now(keys="alt+f4").success)

    def test_windows_are_matched_by_program_nickname_or_title(self):
        self.assertEqual([w["hwnd"] for w in desk.match_windows("VS Code")], [2])
        self.assertEqual([w["hwnd"] for w in desk.match_windows("chrome.exe")], [1])
        self.assertEqual([w["hwnd"] for w in desk.match_windows("inbox")], [1])
        self.assertEqual(desk.match_windows("blender"), [])

    def test_arranging(self):
        placed, shown, focused = [], [], []
        self.patch(desk, "_work_area", lambda hwnd: (0, 0, 1920, 1040))
        self.patch(desk, "_place", lambda hwnd, *rect: placed.append((hwnd, rect)))
        self.patch(desk, "focus", focused.append)
        self.patch(desk, "_user32", lambda: mock.Mock(ShowWindow=lambda hwnd, how: shown.append((hwnd, how))))
        self.assertIn("left half", desk.ArrangeWindowsTool().run_now(action="snap_left", app="code").content)
        self.assertIn("right half", desk.ArrangeWindowsTool().run_now(action="snap_right", app="chrome").content)
        self.assertEqual(placed, [(2, (0, 0, 960, 1040)), (1, (960, 0, 960, 1040))])
        desk.ArrangeWindowsTool().run_now(action="maximise")  # no app: the window in use
        self.assertEqual(shown[-1], (1, desk._SW_MAXIMIZE))
        self.assertIn("Minimised 3 windows", desk.ArrangeWindowsTool().run_now(action="minimise_all").content)
        self.assertNotIn((4, desk._SW_MINIMIZE), shown)  # Sebas stays up
        missing = desk.ArrangeWindowsTool().run_now(action="switch_to", app="blender")
        self.assertFalse(missing.success)
        self.assertIn("chrome, code", missing.content)

    def test_closing_needs_a_yes_and_spares_sebas(self):
        posted = []
        self.patch(desk, "_user32", lambda: mock.Mock(PostMessageW=lambda hwnd, msg, a, b: posted.append((hwnd, msg))))
        parked = desk.CloseAppsTool().execute(app="everything", except_for="Spotify")
        self.assertIn("NOT DONE YET", parked.content)
        self.assertEqual(sebas_actions.pending_summary(), "Close 2 windows: chrome, code.")
        self.assertEqual(posted, [])
        self.assertIn("Asked 2 windows to close", sebas_actions.answer("go ahead"))
        self.assertEqual(posted, [(1, desk._WM_CLOSE), (2, desk._WM_CLOSE)])
        with self.assertRaises(ToolError):
            desk.windows_to_close("everything")  # must say what to keep
        self.assertEqual([w["hwnd"] for w in desk.windows_to_close("chrome")], [1])


if __name__ == "__main__":
    unittest.main()
