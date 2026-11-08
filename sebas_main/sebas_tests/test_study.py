"""Study mode tests: spaced repetition, Gemini output parsing, exams, the Pomodoro
timer and the quiet-butler hold. Uses a temporary data folder; nothing real is touched."""

from __future__ import annotations

import sys
import tempfile
import time
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sebas_bootstrap import load_env  # noqa: E402

load_env()

from custom_tools import household, laptop, study  # noqa: E402


class _TempData(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for module in (household, study):
            p = mock.patch.object(module, "get_data_dir", return_value=Path(tmp.name))
            p.start()
            self.addCleanup(p.stop)
        self.said: list[str] = []
        p = mock.patch.object(laptop, "_announce", self.said.append)
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(study.POMODORO.stop, False, True)


class SpacedRepetition(_TempData):
    def deck(self):
        now = datetime(2026, 11, 8, 10, 0).isoformat(timespec="minutes")
        return {"subject": "DBMS", "cards": [{"id": "a", "q": "Q1", "a": "A1", "box": 0, "due": now},
                                             {"id": "b", "q": "Q2", "a": "A2", "box": 0, "due": now}], "quiz": []}

    def test_grades_move_cards_between_boxes(self):
        d, now = self.deck(), datetime(2026, 11, 8, 10, 0)
        study.grade_card(d, "a", "good", now)
        self.assertEqual((d["cards"][0]["box"], d["cards"][0]["due"]), (1, "2026-11-09T00:00"))
        study.grade_card(d, "a", "easy", now)
        self.assertEqual(d["cards"][0]["box"], 3)  # 4 days
        study.grade_card(d, "a", "again", now)
        self.assertEqual((d["cards"][0]["box"], d["cards"][0]["due"]), (0, "2026-11-08T10:10"))
        self.assertEqual([c["id"] for c in study.due_cards(d, now + timedelta(minutes=11))], ["a", "b"])
        self.assertEqual([c["id"] for c in study.due_cards(d, now)], ["b"])

    def test_saved_progress_and_near_names(self):
        study.save_deck(self.deck())
        study.grade("dbms", "a", "good")
        self.assertEqual(study.load_deck("DBMS")["cards"][0]["box"], 1)
        self.assertEqual(study.load_deck("dbms notes")["subject"], "DBMS")  # near match
        with self.assertRaises(study.ToolError):
            study.load_deck("Thermodynamics")

    def test_quiz_best_score(self):
        study.save_deck({**self.deck(), "quiz": [{"q": "Q", "right": "R", "wrong": ["1", "2", "3"]}]})
        study.record_quiz("DBMS", 6, 10)
        study.record_quiz("DBMS", 4, 10)
        self.assertEqual(study.load_deck("DBMS")["best_quiz"], "6/10")


class GeminiOutput(unittest.TestCase):
    def test_parses_fenced_json_and_drops_bad_items(self):
        reply = '''Here you are:
```json
{"cards": [{"q": "What is 2NF?", "a": "No partial dependencies."}, {"q": "missing answer"}],
 "quiz": [{"q": "Which key?", "right": "Primary", "wrong": ["A", "B", "C"]}, {"q": "bad", "right": "x", "wrong": ["only one"]}]}
```'''
        made = study.parse_study_json(reply)
        self.assertEqual(len(made["cards"]), 1)
        self.assertEqual(len(made["quiz"]), 1)

    def test_garbage_is_a_polite_error(self):
        with self.assertRaises(study.ToolError):
            study.parse_study_json("I'm sorry, I cannot help with that.")


class Exams(_TempData):
    def test_add_replace_list_remove(self):
        soon = (date.today() + timedelta(days=3)).isoformat()
        later = (date.today() + timedelta(days=10)).isoformat()
        study.AddExamTool().run("DBMS", later)
        study.AddExamTool().run("dbms", soon)  # same subject: replaced, not duplicated
        study.AddExamTool().run("Operating Systems", later)
        self.assertEqual([e["subject"] for e in study.upcoming_exams()], ["dbms", "Operating Systems"])
        self.assertIn("in 3 days", study.exams_summary())
        study.RemoveExamTool().run("operating system")
        self.assertEqual(len(study.upcoming_exams()), 1)


class PomodoroTimer(_TempData):
    def test_focus_break_focus_done(self):
        study.POMODORO.start("DBMS", focus=25, rest=5, cycles=2)
        self.assertTrue(study.focus_active())
        released = []
        study._held_releaser[:] = [lambda: released.append(1)]
        self.addCleanup(study._held_releaser.clear)
        s = study.POMODORO.state
        for expected_phase in ("break", "focus"):
            s["ends"] = time.time()  # skip ahead; the timer notices within a second
            for _ in range(50):
                if study.POMODORO.state is None or study.POMODORO.state["phase"] == expected_phase:
                    break
                time.sleep(0.05)
        self.assertEqual(study.POMODORO.state["phase"], "focus")
        self.assertEqual(study.POMODORO.state["cycle"], 2)
        self.assertTrue(released)  # held alerts were released at the break
        s["ends"] = time.time()
        for _ in range(50):
            if study.POMODORO.state is None:
                break
            time.sleep(0.05)
        self.assertIsNone(study.POMODORO.state)
        self.assertFalse(study.focus_active())
        self.assertEqual(round(study.focus_today()["DBMS"]), 50)
        for _ in range(40):  # the closing line is spoken just after the session ends
            if any("50 minutes" in s for s in self.said):
                break
            time.sleep(0.05)
        self.assertTrue(any("50 minutes" in s for s in self.said), self.said)


class QuietButler(_TempData):
    def test_non_urgent_alerts_wait_for_the_break(self):
        from sebas_scheduler import Scheduler

        spoken = []
        sched = Scheduler(spoken.append, lambda p, e: "", None)
        with mock.patch.object(study, "focus_active", return_value=True):
            sched._say("Anime news.")
            sched._say("Anime news.")  # not repeated
            sched._say("Battery low!", urgent=True)
        self.assertEqual(spoken, ["Battery low!"])
        sched.release_held()
        self.assertEqual(spoken[-1], "While you were focusing, sir: Anime news.")
        sched.release_held()
        self.assertEqual(len(spoken), 2)


if __name__ == "__main__":
    unittest.main()
