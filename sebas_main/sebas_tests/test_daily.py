"""Screen-time diary, "what did I do today?", bedtime, search my stuff, and PR reviews.
Offline: temporary data folders, a stand-in for the desktop, GitHub and Claude."""

from __future__ import annotations

import json
import sys
import tempfile
import textwrap
import unittest
import zipfile
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sebas_bootstrap import load_env  # noqa: E402

load_env()

import sebas_actions  # noqa: E402
import sebas_scheduler  # noqa: E402
from custom_tools import coding, daylog, household, laptop, screentime, search, study, wellbeing  # noqa: E402
from custom_tools._base import ToolError  # noqa: E402

NOW = datetime.now().replace(second=0, microsecond=0)
_GITHUB_REPO = coding.github_repo  # before any test replaces it


class _Data(unittest.TestCase):
    def patch(self, target, name, value):
        p = mock.patch.object(target, name, value)
        p.start()
        self.addCleanup(p.stop)

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data = Path(tmp.name)
        for module in (household, sebas_actions, screentime, search, study, coding):
            self.patch(module, "get_data_dir", lambda: self.data)
        self.patch(screentime, "_today", None)
        self.patch(screentime, "_last_save", 0.0)


class ScreenTime(_Data):
    def test_site_names_never_page_titles(self):
        name = screentime.site_name
        self.assertEqual(name("Lo-fi beats to study to - YouTube - Personal - Microsoft​ Edge"), "YouTube")
        self.assertEqual(name("GitHub - krishivvyas/SEBAS: voice butler and 3 more pages - Personal - Microsoft Edge"), "GitHub")
        self.assertEqual(name("Fix add by krishivvyas · Pull Request #12 · krishivvyas/calc - Personal - Microsoft Edge"), "GitHub")
        self.assertEqual(name("krishivvyas/SEBAS: voice butler and 1 more page - Personal - Microsoft​ Edge"), "GitHub")
        self.assertEqual(name("Notes: week 3 - Microsoft Edge"), "Other sites")
        self.assertEqual(name("Inbox (12) - me@example.com - Gmail - Google Chrome"), "Gmail")
        self.assertEqual(name("Normalization in DBMS | Tutorialspoint - Google Chrome"), "Tutorialspoint")
        self.assertEqual(name("New tab - Personal - Microsoft Edge"), "New tab")
        self.assertEqual(name("A very long article title with no site name at all - Google Chrome"), "Other sites")
        self.assertEqual(screentime.app_name("msedge.exe"), "Edge")
        self.assertEqual(screentime.app_name("Code.exe"), "VS Code")
        self.assertEqual(screentime.app_name("blender.exe"), "Blender")

    def test_recording_summary_and_storage(self):
        for app, site, secs in (("Edge", "YouTube", 3000), ("Edge", "GitHub", 1200), ("VS Code", "", 5400), ("Spotify", "", 30)):
            screentime.record(app, site, secs, NOW)
        screentime.flush()
        saved = json.loads((self.data / "sebas" / "screentime" / f"{NOW.date()}.json").read_text("utf-8"))
        self.assertEqual(saved["apps"], {"Edge": 4200, "VS Code": 5400, "Spotify": 30})
        self.assertNotIn("Lo-fi", json.dumps(saved))
        text = screentime.summary()
        self.assertIn("2 h 40 min at the screen", text)
        self.assertIn("Apps: VS Code 1 h 30 min, Edge 1 h 10 min.", text)  # Spotify under a minute: left out
        self.assertIn("Websites: YouTube 50 min, GitHub 20 min.", text)
        tool = screentime.ScreenTimeTool()
        self.assertEqual(tool.run_now(action="report", target="youtube").content, "youtube: 50 min today.")
        self.assertEqual(tool.run_now(action="report", target="VS Code").content, "VS Code: 1 h 30 min today.")

    def test_a_limit_is_mentioned_once(self):
        tool = screentime.ScreenTimeTool()
        self.assertIn("Limit set: YouTube, 1 h a day", tool.run_now(action="set_limit", target="YouTube", minutes=60).content)
        screentime.record("Edge", "YouTube", 3000, NOW)
        self.assertEqual(screentime.check_limits(NOW), [])
        screentime.record("Edge", "YouTube", 700, NOW)
        told = screentime.check_limits(NOW)
        self.assertEqual(len(told), 1)
        self.assertIn("1 h 02 min on YouTube today, past the 1 h you set", told[0])
        self.assertEqual(screentime.check_limits(NOW), [])  # once a day
        self.assertIn("YouTube: 1 h a day", tool.run_now(action="limits").content)
        self.assertIn("removed", tool.run_now(action="remove_limit", target="youtube").content)
        self.assertFalse(tool.run_now(action="remove_limit", target="youtube").success)

    def test_week_and_a_new_day(self):
        screentime.record("Edge", "", 3600, NOW - timedelta(days=1))
        screentime.record("Edge", "", 1800, NOW)
        self.assertIn("1 h 30 min at the screen over 2 days", screentime.week_summary())
        self.assertIn("1 h at the screen", screentime.summary(NOW.date() - timedelta(days=1)))


class MyDay(_Data):
    def test_the_day_is_gathered_from_what_sebas_keeps(self):
        today = NOW.date().isoformat()
        household.save("agenda", [
            {"id": "a", "task": "Submit DBMS assignment", "due": None, "added": "2026-01-01T09:00", "done": f"{today}T15:00"},
            {"id": "b", "task": "Revise joins", "due": None, "added": f"{today}T10:00", "done": False}])
        household.save("expenses", [{"date": today, "amount": 240, "category": "food", "note": ""}])
        household.save("journal", [{"date": today, "time": "21:40", "entry": "Good day.", "mood": "happy"}])
        study.add_focus("DBMS", 50)
        self.patch(wellbeing, "_settings_store", lambda: {"water": {today: 4}})
        screentime.record("VS Code", "", 5400, NOW)
        screentime.record("Edge", "YouTube", 1800, NOW)
        sebas_actions.log("send_message", "To rahul: hi")
        sebas_actions.log("watch", "Sir, the deploy is ready.")
        text = daylog.MyDayTool().run_now().content
        for expected in ("Your day (today):", "At the screen 2 h", "most in VS Code 1 h 30 min, Edge 30 min",
                         "websites: YouTube 30 min", "Focused study 50 min: DBMS 50 min",
                         "Done (1): Submit DBMS assignment.", "Added to the agenda: Revise joins.",
                         "Spent ₹240 (food).", "Water: 4 glasses.", "Journal: 1 entry.", "I sent a message."):
            self.assertIn(expected, text)
        self.assertNotIn("deploy", text)

    def test_an_empty_day_and_bad_dates(self):
        self.assertEqual(daylog.MyDayTool().run_now(day="yesterday").content, "I have nothing recorded for yesterday yet.")
        self.assertFalse(daylog.MyDayTool().run_now(day="last tuesday").success)

    def test_the_evening_check_in_asks_for_it(self):
        self.assertIn("use my_day", sebas_scheduler.EVENING_PROMPT)


class Bedtime(_Data):
    def test_the_night_window(self):
        at = dtime(23, 30)
        past = lambda h, m: daylog.is_past_bedtime(datetime(2026, 11, 16, h, m), at)  # noqa: E731
        self.assertEqual([past(23, 29), past(23, 30), past(2, 0), past(4, 59), past(5, 0), past(14, 0)],
                         [False, True, True, True, False, False])
        late = lambda h, m: daylog.is_past_bedtime(datetime(2026, 11, 16, h, m), dtime(0, 30))  # noqa: E731
        self.assertEqual([late(23, 50), late(0, 30), late(3, 0)], [False, True, True])
        self.assertEqual(daylog.night_of(datetime(2026, 11, 17, 1, 0)), "2026-11-16")

    def test_settings(self):
        tool = daylog.BedtimeSettingsTool()
        self.assertIn("23:30", tool.run_now().content)
        self.assertIn("00:15", tool.run_now(time="00:15").content)
        self.assertIn("off", tool.run_now(enabled=False).content)
        self.assertIsNone(daylog.bedtime())
        self.assertIn("00:15", tool.run_now(enabled=True).content)
        self.assertFalse(tool.run_now(time="quarter past").success)

    def test_tomorrow_line(self):
        night = datetime(2026, 11, 16, 23, 40)
        self.assertEqual(daylog.tomorrow_line(night), "Tomorrow's agenda is clear.")
        household.save("agenda", [
            {"id": "a", "task": "Submit the report", "due": "2026-11-17T17:00:00", "added": "x", "done": False},
            {"id": "b", "task": "Pay the fees", "due": "2026-11-17T00:00:00", "added": "x", "done": False}])
        household.save("exams", [{"id": "e", "subject": "DBMS", "date": "2026-11-19"}])
        with mock.patch.object(study, "date") as clock:
            clock.today.return_value = date(2026, 11, 16)
            line = daylog.tomorrow_line(night)
        self.assertEqual(line, "Tomorrow: Pay the fees is due, and 1 more; your DBMS exam is 2 days later.")
        after_midnight = daylog.tomorrow_line(datetime(2026, 11, 17, 0, 40))  # "tomorrow" is now the 17th itself
        self.assertIn("Pay the fees is due", after_midnight)

    def test_the_scheduler_says_it_once_then_once_more(self):
        said, pressed = [], []
        sched = sebas_scheduler.Scheduler.__new__(sebas_scheduler.Scheduler)
        sched._raw_say, sched._state, sched._save = said.append, {}, lambda: None
        self.patch(sebas_scheduler, "idle_seconds", lambda: 5)
        self.patch(sebas_scheduler, "_pause_music", lambda: pressed.append(1) or True)
        self.patch(daylog, "bedtime", lambda: dtime(23, 30))
        self.patch(daylog, "tomorrow_line", lambda now: "Tomorrow's agenda is clear.")
        start = datetime(2026, 11, 16, 23, 31)
        for minutes in (0, 1, 10, 29):
            sched._bedtime(start + timedelta(minutes=minutes))
        self.assertEqual(len(said), 1)
        self.assertEqual(said[0], "It is 11:31, sir, and past your bedtime. I have paused the music. Tomorrow's agenda is clear. Do rest when you are ready.")
        sched._bedtime(start + timedelta(minutes=31))
        sched._bedtime(start + timedelta(minutes=90))
        self.assertEqual(len(said), 2)
        self.assertIn("Still up, sir?", said[1])
        self.assertEqual(len(pressed), 1)
        sched._bedtime(start + timedelta(hours=24))  # the next night
        self.assertEqual(len(said), 3)

    def test_not_while_away_or_focusing(self):
        said = []
        sched = sebas_scheduler.Scheduler.__new__(sebas_scheduler.Scheduler)
        sched._raw_say, sched._state, sched._save = said.append, {}, lambda: None
        self.patch(daylog, "bedtime", lambda: dtime(23, 30))
        self.patch(sebas_scheduler, "idle_seconds", lambda: 900)
        sched._bedtime(datetime(2026, 11, 16, 23, 45))
        self.patch(sebas_scheduler, "idle_seconds", lambda: 5)
        with mock.patch.object(study, "focus_active", lambda: True):
            sched._bedtime(datetime(2026, 11, 16, 23, 45))
        self.assertEqual(said, [])


def _docx(path: Path, paragraphs: list[str]) -> None:
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("word/document.xml", f'<w:document xmlns:w="w"><w:body>{body}</w:body></w:document>')


class Search(_Data):
    def setUp(self):
        super().setUp()
        self.docs = self.data / "Documents"
        notes = self.docs / "Sebas Notes"
        notes.mkdir(parents=True)
        (notes / "2026-11-10 DBMS lecture.md").write_text(
            "# DBMS lecture\n\nNormalisation removes redundancy. Third normal form (3NF) means no transitive dependency "
            "on the key.\n\nBCNF is stricter than 3NF.\n\nUnrelated: the canteen closes at four.", "utf-8")
        _docx(self.docs / "College" / "os.docx" if (self.docs / "College").mkdir() is None else None,
              ["Operating systems notes", "Deadlock needs four conditions: mutual exclusion, hold and wait, no "
               "preemption, circular wait."])
        repo = self.docs / "portfolio"
        (repo / ".git").mkdir(parents=True)
        (repo / "README.md").write_text("normalisation of the database in the portfolio code", "utf-8")
        household.save("journal", [{"date": "2026-11-12", "entry": "Finally understood normalisation today.", "mood": ""}])
        deck = self.data / "sebas" / "study"
        deck.mkdir(parents=True)
        (deck / "dbms.json").write_text(json.dumps({"subject": "DBMS", "cards": [{"q": "What is 2NF?", "a": "No partial dependency."}],
                                                    "quiz": [{"q": "BCNF is stricter than?", "right": "3NF", "wrong": ["1NF", "2NF", "4NF"]}]}), "utf-8")
        self.patch(search, "_documents_root", lambda: self.docs)

    def test_finds_notes_journal_and_word_files_but_not_code(self):
        found = search.search("what did I note about normalisation")
        sources = [f["source"] for f in found]
        self.assertIn("Lecture notes: 2026-11-10 DBMS lecture", sources)
        self.assertIn("Journal, 2026-11-12", sources)
        self.assertFalse(any("portfolio" in s for s in sources))
        self.assertIn("transitive dependency", found[sources.index("Lecture notes: 2026-11-10 DBMS lecture")]["text"])
        deadlock = search.search("deadlock conditions")
        self.assertEqual(deadlock[0]["source"], "Documents/College/os.docx")
        self.assertIn("circular wait", deadlock[0]["text"])
        self.assertTrue(any(f["source"] == "Quiz: DBMS" for f in search.search("BCNF stricter")))

    def test_the_tool_and_a_miss(self):
        text = search.SearchMyStuffTool().run_now(query="third normal form").content
        self.assertIn("[Lecture notes: 2026-11-10 DBMS lecture]", text)
        self.assertIn("Nothing in the user's notes", search.SearchMyStuffTool().run_now(query="quantum gravity").content)
        self.assertFalse(search.SearchMyStuffTool().run_now(query="what did I note about").success)

    def test_word_files_are_read_once_and_cached(self):
        reads = []
        real = search.read_docx
        self.patch(search, "read_docx", lambda p: (reads.append(p), real(p))[1])
        search.search("deadlock")
        search.search("deadlock")
        self.assertEqual(len(reads), 1)

    def test_chunks_keep_pdf_page_numbers(self):
        pieces = list(search.chunks("\f[page 1]\nIntro text.\f[page 2]\nNormalisation on page two."))
        self.assertEqual(pieces, [("p. 1", "Intro text."), ("p. 2", "Normalisation on page two.")])


FAKE_REVIEWER = textwrap.dedent('''
    import json, sys
    brief = sys.stdin.read()
    assert "Pull request #12" in brief and "+    return a + b" in brief
    print(json.dumps({"type": "result", "is_error": False,
                      "result": "1. calc.py line 2: fine.\\n\\nSPOKEN: One real problem: the **divide** function ignores zero."}))
''')


class Review(_Data):
    def setUp(self):
        super().setUp()
        self.repo = self.data / "proj"
        self.repo.mkdir()
        self.fake = self.data / "fake_reviewer.py"
        self.fake.write_text(FAKE_REVIEWER)
        self.said = []
        self.patch(laptop, "_announce", self.said.append)
        self.patch(coding, "_lookup", lambda section, name: str(self.repo))
        self.patch(coding, "_review", None)
        self.patch(coding, "github_repo", lambda folder: "krishivvyas/calc")
        self.calls = []

        def github(path, accept="application/vnd.github+json", **params):
            self.calls.append((path, accept, params))
            if path == "/user":
                return {"login": "krishivvyas"}
            if path == "/search/issues":
                return {"items": [{"number": 12}]} if "author:" in params["q"] else {"items": []}
            if "diff" in accept:
                return "--- a/calc.py\n+++ b/calc.py\n@@\n-    return a - b\n+    return a + b\n"
            return {"number": 12, "title": "Fix add", "html_url": "https://github.com/x/12", "changed_files": 1,
                    "head": {"ref": "fix"}, "base": {"ref": "main"}, "body": "Fixes the add bug."}

        self.patch(coding, "_github", github)

    def test_review_runs_read_only_and_reads_out_the_findings(self):
        self.patch(coding, "review_command", lambda: [sys.executable, str(self.fake)])
        result = coding.ReviewPrTool().run_now(project="calc")
        self.assertTrue(result.success, result.content)
        self.assertIn("reviewing pull request 12 in krishivvyas/calc, 'Fix add'", result.content)
        coding._review["thread"].join(timeout=30)
        self.assertEqual(self.said, ["Sir, Claude has reviewed pull request 12, Fix add. One real problem: the divide "
                                     "function ignores zero. The full review is saved with the coding reports."])
        report = Path(coding._review["report"]).read_text("utf-8")
        self.assertIn("calc.py line 2", report)
        self.assertIn("ended as: done", coding.ReviewPrTool().run_now(action="status").content)
        self.assertIsNone(coding.review_snapshot())

    def test_the_review_command_can_only_read(self):
        with mock.patch.object(coding.shutil, "which", lambda name: "claude.exe"):
            command = coding.review_command()
        self.assertEqual(command[command.index("--tools") + 1], "Read,Glob,Grep")
        self.assertEqual(command[command.index("--setting-sources") + 1], "")
        for word in ("Bash", "Edit", "Write", "acceptEdits", "bypassPermissions"):
            self.assertNotIn(word, " ".join(command))

    def test_which_pull_request(self):
        self.assertEqual(coding.find_pr("krishivvyas/calc", None)["number"], 12)
        self.assertIn("author:krishivvyas", self.calls[1][2]["q"])
        self.patch(coding, "_github", lambda path, accept="", **p: {"login": "k"} if path == "/user" else {"items": []})
        with self.assertRaises(ToolError):
            coding.find_pr("krishivvyas/calc", None)

    def test_github_remote_parsing(self):
        for url, repo in (("https://github.com/krishivvyas/SEBAS.git", "krishivvyas/SEBAS"),
                          ("git@github.com:krishivvyas/SEBAS.git", "krishivvyas/SEBAS"),
                          ("https://github.com/a/b", "a/b")):
            with mock.patch.object(coding, "_git", lambda folder, *a, check=True: url):
                self.assertEqual(_GITHUB_REPO(self.repo), repo)


if __name__ == "__main__":
    unittest.main()
