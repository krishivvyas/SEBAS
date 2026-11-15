"""Errands, offline: real agenda tools on a temporary data folder, stand-in tools
for a search and a risky action, and stand-ins for both models (Gemini and the
local one), so the quarter rule and the local-to-Gemini rescue can be watched."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sebas_bootstrap import load_env  # noqa: E402

load_env()

import sebas_actions  # noqa: E402
import sebas_brain  # noqa: E402
from custom_tools import errands, household, laptop  # noqa: E402
from custom_tools._base import SebasTool, ToolError  # noqa: E402
from openjarvis.core.registry import ToolRegistry  # noqa: E402


class _Finder(SebasTool):
    name = "test_finder"
    description = "Find a file by name."
    parameters = {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}

    def run(self, query: str) -> str:
        if query == "nothing":
            raise ToolError("Nothing was found.")
        return "- Documents/College/DBMS notes.txt (12 Nov 2026)\n- Downloads/dbms_old.pdf (01 Jan 2025)"


class _Reader(SebasTool):
    name = "test_reader"
    description = "Open a file."
    parameters = {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}
    opened: list[str] = []

    def run(self, path: str) -> str:
        self.opened.append(path)
        return f"Opened {path}."


class _Bin(SebasTool):
    name = "test_bin"
    description = "Delete a file. Cannot be undone."
    risky = True
    parameters = {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}
    deleted: list[str] = []

    def run(self, path: str) -> str:
        self.deleted.append(path)
        return f"Deleted {path}."


for _tool in (_Finder, _Reader, _Bin):
    if not ToolRegistry.contains(_tool.name):
        ToolRegistry.register(_tool.name)(_tool)


class _Errands(unittest.TestCase):
    def patch(self, target, name, value):
        p = mock.patch.object(target, name, value)
        p.start()
        self.addCleanup(p.stop)

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        data = Path(tmp.name)
        for module in (household, sebas_actions):
            self.patch(module, "get_data_dir", lambda: data)
        self.patch(sebas_brain, "_budget_path", lambda: data / "gemini_budget.json")
        self.said: list[str] = []
        self.patch(laptop, "_announce", self.said.append)
        self.patch(errands, "_errand", None)
        self.patch(errands, "_parked", None)
        self.patch(errands, "_gemini_keys", lambda: ["key"])
        self.patch(sebas_brain, "choose_local_model", lambda: "qwen-test")
        self.gemini: list[str] = []   # prompts each model was asked
        self.local: list[str] = []
        self.gemini_says = lambda prompt: json.dumps({"args": {"path": "Documents/College/DBMS notes.txt"}})
        self.local_says = lambda prompt: json.dumps({"args": {"path": "Documents/College/DBMS notes.txt"}})
        self.patch(errands, "ask_gemini", lambda p: (self.gemini.append(p), self.gemini_says(p))[1])
        self.patch(errands, "ask_local", lambda p: (self.local.append(p), self.local_says(p))[1])
        _Reader.opened.clear()
        _Bin.deleted.clear()
        sebas_actions.answer("drop anything left over")

    def start(self, steps, title="Exam preparation", engine="auto"):
        result = errands.StartErrandTool().run_now(title=title, steps=steps, engine=engine)
        if result.success and errands._errand is not None:
            errands._errand["thread"].join(timeout=20)  # until the report has been spoken
        return result

    def states(self):
        return [s["state"] for s in errands._errand["steps"]]


FIND_THEN_OPEN = [
    {"say": "Find the DBMS notes", "tool": "test_finder", "args": '{"query": "dbms notes"}'},
    {"say": "Open them", "tool": "test_reader", "decide": "path = the most recent DBMS notes file from step 1"},
]


class Plans(_Errands):
    def test_plain_steps_run_without_any_model(self):
        result = self.start([
            {"say": "Add revision", "tool": "add_task", "args": '{"task": "Revise joins", "due": "2026-11-18"}'},
            {"say": "Add past paper", "tool": "add_task", "args": {"task": "Solve a past paper"}},
            {"say": "Read the agenda", "tool": "list_tasks", "tell": True},
        ])
        self.assertTrue(result.success, result.content)
        self.assertIn("has begun: 3 steps", result.content)
        self.assertEqual(self.states(), ["done", "done", "done"])
        self.assertEqual([t["task"] for t in household.open_tasks()], ["Revise joins", "Solve a past paper"])
        self.assertIn("Revise joins", errands._errand["steps"][2]["result"])
        self.assertEqual((self.gemini, self.local), ([], []))
        self.assertEqual(self.said, ["Sir, the errand 'Exam preparation' is complete: 3 of 3 steps done. Read the agenda: "
                                     "- Revise joins (Wed 18 Nov) - Solve a past paper (no deadline)"])  # he asked to be told
        self.assertIn("3. Read the agenda [done]", errands.ErrandTool().run_now(action="status").content)

    def test_bad_plans_are_refused_before_anything_runs(self):
        for steps, word in (
            ([{"say": "x", "tool": "no_such_tool"}], "not a tool"),
            ([{"say": "x", "tool": "start_errand"}], "not a tool"),  # no errand inside an errand
            ([{"say": "x", "tool": "add_task"}], "needs task"),
            ([{"say": "x", "tool": "add_task", "args": '{"task": "a", "colour": "red"}'}], "no parameter colour"),
            ([{"say": "x", "tool": "add_task", "args": "{broken"}], "not valid JSON"),
            ([{"say": "x", "tool": "list_tasks"}] * 13, "at most 12"),
        ):
            result = self.start(steps)
            self.assertFalse(result.success, steps)
            self.assertIn(word, result.content)
        self.assertIsNone(errands._errand)

    def test_a_failed_step_does_not_stop_the_rest(self):
        self.start([{"say": "Find", "tool": "test_finder", "args": '{"query": "nothing"}'},
                    {"say": "Add a task", "tool": "add_task", "args": '{"task": "Carry on"}'}])
        self.assertEqual(self.states(), ["failed", "done"])
        self.assertIn("1 of 2 steps done", self.said[0])
        self.assertIn("step 1 (Find) failed: Nothing was found.", self.said[0])

    def test_one_at_a_time_stop_save_and_run_again(self):
        gate = __import__("threading").Event()
        self.patch(_Reader, "run", lambda self_, path: (gate.wait(10), "Opened.")[1])
        steps = [{"say": "Open", "tool": "test_reader", "args": '{"path": "a.txt"}'},
                 {"say": "Add a task", "tool": "add_task", "args": '{"task": "Later"}'}]
        self.assertTrue(errands.StartErrandTool().run_now(title="Slow one", steps=steps).success)
        self.assertFalse(errands.StartErrandTool().run_now(title="Another", steps=steps).success)
        self.assertEqual(errands.snapshot()["steps"][0], {"say": "Open", "state": "running"})
        self.assertIn("will stop", errands.ErrandTool().run_now(action="stop").content)
        gate.set()
        errands._errand["thread"].join(timeout=20)
        self.assertEqual(self.states(), ["done", "skipped"])
        self.assertEqual(household.open_tasks(), [])
        self.assertEqual(self.said, [])  # he stopped it himself
        self.assertIn("Saved as 'slow one'", errands.ErrandTool().run_now(action="save", name="slow one").content)
        self.assertIn("slow one: 2 steps", errands.ErrandTool().run_now(action="list").content)
        self.assertTrue(errands.ErrandTool().run_now(action="run", name="my slow one").success)
        errands._errand["thread"].join(timeout=20)
        self.assertEqual(self.states(), ["done", "done"])
        self.assertIn("Forgotten", errands.ErrandTool().run_now(action="forget", name="slow one").content)
        self.assertFalse(errands.ErrandTool().run_now(action="run", name="slow one").success)


class WhoThinks(_Errands):
    def test_small_errand_with_plenty_of_budget_uses_gemini(self):
        result = self.start(FIND_THEN_OPEN)
        self.assertNotIn("local model", result.content)
        self.assertEqual((len(self.gemini), len(self.local)), (1, 0))
        self.assertEqual(_Reader.opened, ["Documents/College/DBMS notes.txt"])
        prompt = self.gemini[0]
        for expected in ("Exam preparation", "Find the DBMS notes [done]", "dbms_old.pdf", "most recent DBMS notes file", '"path"'):
            self.assertIn(expected, prompt)

    def test_more_than_a_quarter_of_what_is_left_goes_local(self):
        sebas_brain.note_gemini_use(55)  # 5 of 60 left: this errand (2) is more than a quarter
        result = self.start(FIND_THEN_OPEN)
        self.assertIn("local model (qwen-test)", result.content)
        self.assertIn("2 of 5 requests", result.content)
        self.assertEqual((len(self.gemini), len(self.local)), (0, 1))
        self.assertEqual(self.states(), ["done", "done"])

    def test_exactly_a_quarter_stays_on_gemini(self):
        sebas_brain.note_gemini_use(52)  # 8 left; cost 2
        self.assertEqual(errands.choose_engine(errands.check_plan("t", FIND_THEN_OPEN))[0], "gemini")
        sebas_brain.note_gemini_use(1)   # 7 left
        self.assertEqual(errands.choose_engine(errands.check_plan("t", FIND_THEN_OPEN))[0], "local")

    def test_the_user_can_force_either(self):
        self.assertIn("As asked", self.start(FIND_THEN_OPEN, engine="local").content)
        self.assertEqual((len(self.gemini), len(self.local)), (0, 1))
        sebas_brain.note_gemini_use(59)
        self.start(FIND_THEN_OPEN, engine="gemini")
        self.assertEqual(len(self.gemini), 1)

    def test_no_local_model_stays_on_gemini_and_says_so(self):
        self.patch(sebas_brain, "choose_local_model", mock.Mock(side_effect=RuntimeError("Ollama is not installed")))
        sebas_brain.note_gemini_use(58)
        result = self.start(FIND_THEN_OPEN)
        self.assertIn("no local model is available", result.content)
        self.assertEqual(len(self.gemini), 1)

    def test_local_nonsense_is_retried_then_rescued_by_gemini(self):
        self.local_says = lambda prompt: "I think the file is the notes one!"
        self.start(FIND_THEN_OPEN, engine="local")
        self.assertEqual((len(self.local), len(self.gemini)), (2, 1))
        self.assertEqual(self.states(), ["done", "done"])
        self.assertIn("needed Gemini's help on 1 step", self.said[0])

    def test_invented_arguments_and_missing_ones_are_not_accepted(self):
        read = errands._read_judgment
        schema = _Reader.parameters
        self.assertEqual(read('{"args": {"path": "a.txt", "extra": 1}}', schema), {"args": {"path": "a.txt"}})
        self.assertEqual(read('{"skip": "no notes were found"}', schema), {"skip": "no notes were found"})
        for bad in ('{"args": {}}', '{"args": "a.txt"}', '[1]', 'nope'):
            with self.assertRaises(ToolError, msg=bad):
                read(bad, schema)

    def test_the_model_may_skip_a_step(self):
        self.gemini_says = lambda prompt: '{"skip": "no notes were found"}'
        self.start([{"say": "Find", "tool": "test_finder", "args": '{"query": "nothing"}'}, FIND_THEN_OPEN[1]])
        self.assertEqual(self.states(), ["failed", "skipped"])
        self.assertEqual(_Reader.opened, [])

    def test_budget_counts_by_day(self):
        self.assertEqual(sebas_brain.gemini_remaining(), 60)
        sebas_brain.note_gemini_use()
        sebas_brain.note_gemini_use(4)
        self.assertEqual(sebas_brain.gemini_remaining(), 55)
        with mock.patch.object(sebas_brain, "_budget_day", return_value="2099-01-01"):
            self.assertEqual(sebas_brain.gemini_remaining(), 60)  # a new day
        with mock.patch.dict(sebas_brain.os.environ, {"SEBAS_GEMINI_DAILY_BUDGET": "100"}):
            self.assertEqual(sebas_brain.gemini_remaining(), 95)


class Risk(_Errands):
    def test_a_plan_with_a_risky_step_waits_for_a_yes(self):
        result = self.start([{"say": "Add a task", "tool": "add_task", "args": '{"task": "Before"}'},
                             {"say": "Delete the old paper", "tool": "test_bin", "args": '{"path": "Downloads/old.pdf"}'}])
        self.assertIn("NOT DONE YET", result.content)
        self.assertIn("It includes Delete the old paper", sebas_actions.pending_summary())
        self.assertIsNone(errands._errand)
        self.assertEqual(household.open_tasks(), [])
        self.assertIn("has begun", sebas_actions.answer("yes"))
        errands._errand["thread"].join(timeout=20)
        self.assertEqual(self.states(), ["done", "done"])
        self.assertEqual(_Bin.deleted, ["Downloads/old.pdf"])  # approved with the plan: not asked twice

    def test_a_no_starts_nothing(self):
        self.start([{"say": "Delete", "tool": "test_bin", "args": '{"path": "x"}'}])
        sebas_actions.answer("no")
        self.assertIsNone(errands._errand)
        self.assertFalse(errands.ErrandGoTool().run_now().success)

    def _judged_delete(self, reply: str):
        steps = [FIND_THEN_OPEN[0], {"say": "Delete the old one", "tool": "test_bin", "decide": "path = the 2025 file"}]
        self.gemini_says = lambda prompt: '{"args": {"path": "Downloads/dbms_old.pdf"}}'
        self.start(steps)  # parks: the plan has a risky step
        asked = __import__("threading").Event()
        self.patch(errands, "_tell", lambda text: (self.said.append(text), asked.set()))
        sebas_actions.answer("yes")  # the plan is approved and starts
        self.assertTrue(asked.wait(10))  # ...but the particulars were decided mid-errand: he asks again
        self.assertIn("Delete a file (path: Downloads/dbms_old.pdf)", self.said[-1])
        self.assertEqual(errands.snapshot()["steps"][1]["state"], "waiting")
        self.assertEqual(_Bin.deleted, [])
        sebas_actions.answer(reply)
        errands._errand["thread"].join(timeout=20)

    def test_a_risky_step_decided_mid_errand_asks_again(self):
        self._judged_delete("yes")
        self.assertEqual(_Bin.deleted, ["Downloads/dbms_old.pdf"])
        self.assertEqual(self.states(), ["done", "done"])

    def test_and_a_no_skips_only_that_step(self):
        self._judged_delete("no")
        self.assertEqual(_Bin.deleted, [])
        self.assertEqual(self.states(), ["done", "skipped"])
        self.assertIn("declined by the user", errands._errand["steps"][1]["result"])


if __name__ == "__main__":
    unittest.main()
