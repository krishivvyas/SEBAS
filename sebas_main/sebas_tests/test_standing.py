"""Standing orders, watchers and the yes-gate for risky actions. Offline: every
outside service (Vercel, GitHub, Steam, web pages, the battery, processes) is
replaced by a stand-in, and data goes to a temporary folder."""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sebas_bootstrap import load_env  # noqa: E402

load_env()

import sebas_actions  # noqa: E402
from custom_tools import _base, household, standing  # noqa: E402
from custom_tools._base import SebasTool, ToolError  # noqa: E402

MON_9 = datetime(2026, 11, 16, 9, 0)  # a Monday


class _TempData(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data = Path(tmp.name)
        for module in (household, sebas_actions):
            p = mock.patch.object(module, "get_data_dir", return_value=self.data)
            p.start()
            self.addCleanup(p.stop)
        standing._cpu_marks.clear()

    def patch(self, target, name, value):
        p = mock.patch.object(target, name, value)
        p.start()
        self.addCleanup(p.stop)

    def watch(self, **params) -> str:
        result = standing.WatchForTool().run_now(**params)
        self.assertTrue(result.success, result.content)
        return result.content

    def later(self, seconds: float):
        """Poll as though ``seconds`` had passed since the watchers were last checked."""
        return standing.poll(datetime.now() + timedelta(seconds=seconds))


class Routines(_TempData):
    def add(self, **kw):
        return standing.AddRoutineTool().run_now(**{"name": "Morning desk", "request": "open my workspace",
                                                    "time": "09:00", "days": "weekdays", **kw})

    def test_days_and_times_are_read(self):
        self.assertEqual(standing.parse_days("weekdays"), [0, 1, 2, 3, 4])
        self.assertEqual(standing.parse_days("Mon, Wed and Friday"), [0, 2, 4])
        self.assertEqual(standing.parse_days("every day"), list(range(7)))
        self.assertEqual(standing.describe_days([5, 6]), "weekends")
        self.assertEqual(standing._parse_clock("5:30 pm").strftime("%H:%M"), "17:30")
        with self.assertRaises(ToolError):
            standing.parse_days("whenever")

    def test_runs_once_on_its_days_within_the_grace(self):
        with mock.patch.object(standing, "datetime", wraps=datetime) as clock:
            clock.now.return_value = MON_9 - timedelta(hours=2)
            self.assertTrue(self.add().success)
        self.assertEqual(standing.due_routines(MON_9 - timedelta(minutes=1)), [])
        due = standing.due_routines(MON_9 + timedelta(minutes=5))
        self.assertEqual([r["name"] for r in due], ["Morning desk"])
        self.assertIn("open my workspace", standing.routine_prompt(due[0]))
        self.assertEqual(standing.due_routines(MON_9 + timedelta(minutes=6)), [])  # once a day
        self.assertEqual(len(standing.due_routines(MON_9 + timedelta(days=1))), 1)  # Tuesday
        self.assertEqual(standing.due_routines(MON_9 + timedelta(days=5)), [])  # Saturday

    def test_missed_by_more_than_the_grace_waits_for_the_next_day(self):
        with mock.patch.object(standing, "datetime", wraps=datetime) as clock:
            clock.now.return_value = MON_9 - timedelta(hours=2)
            self.add()
        self.assertEqual(standing.due_routines(MON_9 + timedelta(hours=4)), [])

    def test_created_after_todays_time_starts_tomorrow(self):
        with mock.patch.object(standing, "datetime", wraps=datetime) as clock:
            clock.now.return_value = MON_9 + timedelta(hours=1)
            self.add()
        self.assertEqual(standing.due_routines(MON_9 + timedelta(hours=1, minutes=1)), [])
        self.assertEqual(len(standing.due_routines(MON_9 + timedelta(days=1))), 1)

    def test_same_name_replaces_and_cancel_removes(self):
        self.add()
        self.add(time="10:00")
        listed = standing.ListStandingTool().run_now().content
        self.assertEqual(listed.count("Morning desk"), 1)
        self.assertIn("10:00", listed)
        self.assertIn("Morning desk", standing.CancelStandingTool().run_now(what="the morning routine").content)
        self.assertEqual(household.load("standing"), [])


class Watchers(_TempData):
    def test_deploy_reports_only_a_deployment_that_finishes_after_the_watch(self):
        latest = {"uid": "d1", "readyState": "READY", "name": "portfolio", "target": "production"}
        self.patch(standing, "require_env", lambda *a: "token")
        self.patch(standing, "http_get_json", lambda *a, **k: {"deployments": [dict(latest)]})
        self.assertIn("Watching", self.watch(kind="deploy"))
        self.assertEqual(self.later(61), [])  # the old, finished deployment is not news
        latest.update(uid="d2", readyState="BUILDING")
        self.assertEqual(self.later(122), [])
        latest["readyState"] = "ERROR"
        self.assertEqual(self.later(183), ["Sir, the production deployment of portfolio has failed."])
        self.assertEqual(household.load("standing"), [])  # told once, then retired

    def test_deploy_in_progress_when_asked_is_reported(self):
        latest = {"uid": "d1", "readyState": "BUILDING", "name": "portfolio", "target": None}
        self.patch(standing, "require_env", lambda *a: "token")
        self.patch(standing, "http_get_json", lambda *a, **k: {"deployments": [dict(latest)]})
        self.watch(kind="deploy", target="portfolio")
        latest["readyState"] = "READY"
        self.assertEqual(self.later(61), ["Sir, the preview deployment of portfolio is ready."])

    def test_pull_request_checks(self):
        checks = [{"name": "tests", "status": "in_progress", "conclusion": None},
                  {"name": "lint", "status": "completed", "conclusion": "success"}]

        def github(path, **params):
            if path == "/user":
                return {"login": "krishivvyas"}
            if path.endswith("/pulls/12"):
                return {"head": {"sha": "abc"}}
            self.assertEqual(path, "/repos/krishivvyas/SEBAS/commits/abc/check-runs")
            return {"check_runs": checks}

        self.patch(standing, "_github", github)
        self.assertIn("pull request 12 of krishivvyas/SEBAS", self.watch(kind="ci", target="SEBAS#12"))
        self.assertEqual(self.later(61), [])
        checks[0].update(status="completed", conclusion="failure")
        self.assertEqual(self.later(122), ["Sir, the checks on pull request 12 on SEBAS have finished, and 1 did not pass: tests."])

    def test_checks_already_finished_are_told_at_once(self):
        self.patch(standing, "_github", lambda path, **p: {"head": {"sha": "abc"}} if "/pulls/" in path
                   else {"check_runs": [{"name": "tests", "status": "completed", "conclusion": "success"}]})
        self.assertIn("No need to wait: Sir, all 1 checks", self.watch(kind="ci", target="krishivvyas/SEBAS#3"))
        self.assertEqual(household.load("standing"), [])

    def test_workflow_run(self):
        run = {"id": 7, "status": "in_progress", "conclusion": None, "name": "CI"}
        self.patch(standing, "_github", lambda path, **p: {"workflow_runs": [dict(run)]})
        self.watch(kind="ci", target="krishivvyas/SEBAS")
        run.update(status="completed", conclusion="success")
        self.assertEqual(self.later(61), ["Sir, the CI run on krishivvyas/SEBAS finished: success."])

    def test_steam_price_target_and_sale(self):
        price = {"final": 249900, "final_formatted": "₹2,499", "initial_formatted": "₹2,499", "discount_percent": 0}
        self.patch(standing, "steam_find", lambda name: ("1245620", "ELDEN RING"))
        self.patch(standing, "steam_price", lambda app: dict(price))
        self.assertIn("ELDEN RING on Steam to reach ₹1,500", self.watch(kind="steam_price", target="elden ring", value=1500))
        self.assertIn("to go on sale", self.watch(kind="steam_price", target="elden ring"))
        self.assertEqual(self.later(3 * 3600 + 1), [])
        price.update(final=149900, final_formatted="₹1,499", discount_percent=40)
        told = self.later(6 * 3600 + 2)
        self.assertEqual(len(told), 2)
        self.assertIn("at or below the 1,500", told[0])
        self.assertIn("40 percent off", told[1])

    def test_page_change_and_phrase(self):
        page = {"text": "Out of stock\nPrice 500"}
        self.patch(standing, "page_text", lambda url: page["text"])
        self.patch(standing.time, "sleep", lambda s: None)
        self.assertIn("example.com/item to change", self.watch(kind="page", target="example.com/item"))
        self.watch(kind="page", target="https://example.com/item", phrase="In stock")
        self.assertEqual(self.later(901), [])
        page["text"] = "In stock\nPrice 500"
        self.assertEqual(sorted(self.later(1802)), ["Sir, the page at example.com has changed.",
                                                    "Sir, the page at example.com now mentions 'In stock'."])

    def test_a_page_that_differs_on_every_load_is_refused(self):
        loads = iter(["visitor 1", "visitor 2"])
        self.patch(standing, "page_text", lambda url: next(loads))
        self.patch(standing.time, "sleep", lambda s: None)
        result = standing.WatchForTool().run_now(kind="page", target="https://example.com")
        self.assertFalse(result.success)
        self.assertIn("phrase", result.content)

    def test_page_text_drops_scripts_and_tags(self):
        response = SimpleNamespace(text="<html><head><title>x</title></head><body><script>var a=1</script>"
                                        "<h1>Sale &amp; more</h1><p>In   stock</p></body></html>",
                                   raise_for_status=lambda: None)
        self.patch(standing.httpx, "get", lambda *a, **k: response)
        self.assertEqual(standing.page_text("https://example.com"), "Sale & more\nIn stock")

    def test_download_and_new_file(self):
        folder = self.data / "Downloads"
        folder.mkdir()
        (folder / "old.pdf").write_text("x")
        self.patch(standing, "resolve_folder", lambda name: folder)
        self.assertFalse(standing.WatchForTool().run_now(kind="download").success)  # nothing in progress
        (folder / "Unconfirmed 42.crdownload").write_text("x")
        self.watch(kind="download")
        self.watch(kind="file", target="downloads", phrase="*.zip")
        self.assertEqual(self.later(31), [])
        (folder / "Unconfirmed 42.crdownload").rename(folder / "game.zip")
        self.assertEqual(sorted(self.later(62)), ["Sir, a new file has appeared in Downloads: game.zip.",
                                                  "Sir, the download has finished: game.zip."])

    def test_folders_outside_home_are_refused(self):
        with self.assertRaises(ToolError):
            standing.resolve_folder("C:\\Windows\\System32")

    def test_battery_app_and_quiet_processor(self):
        battery = SimpleNamespace(percent=80.0, power_plugged=True)
        self.patch(standing.psutil, "sensors_battery", lambda: battery)
        running = {"blender": True}
        self.patch(standing, "_processes", lambda name: [object()] if running.get(name) else [])
        used = {"v": 0.0}
        self.patch(standing, "_cpu_used", lambda name: used["v"])
        clock = {"t": 1000.0}
        self.patch(standing.time, "monotonic", lambda: clock["t"])
        self.patch(standing.psutil, "cpu_count", lambda: 1)

        self.assertIn("battery to reach 100", self.watch(kind="battery"))
        self.assertIn("blender to close", self.watch(kind="app_closed", target="blender"))
        self.assertFalse(standing.WatchForTool().run_now(kind="app_closed", target="notepad").success)
        self.watch(kind="cpu_quiet")

        for step in range(1, 4):  # busy: 90% of each 30 seconds
            clock["t"] += 30; used["v"] += 27  # noqa: E702
            self.assertEqual(self.later(31 * step), [])
        battery.percent, running["blender"] = 100.0, False
        told = []
        for step in range(4, 9):  # quiet: 3%
            clock["t"] += 30; used["v"] += 1  # noqa: E702
            told += self.later(31 * step)
        self.assertEqual(sorted(told), ["Sir, blender has closed.", "Sir, the battery is fully charged.",
                                        "Sir, the processor has gone quiet; whatever was running appears to have finished."])
        self.assertEqual(household.load("standing"), [])

    def test_network_trouble_is_retried_and_a_lapsed_watch_says_so(self):
        self.patch(standing, "steam_find", lambda name: ("1", "Hades"))
        price = {"ok": True}

        def steam_price(app):
            if not price["ok"]:
                raise ToolError("Could not reach the Steam store")
            return {"final": 100000, "final_formatted": "₹1,000", "initial_formatted": "₹1,000", "discount_percent": 0}

        self.patch(standing, "steam_price", steam_price)
        self.watch(kind="steam_price", target="hades")
        price["ok"] = False
        self.assertEqual(self.later(3 * 3600 + 1), [])
        self.assertEqual(len(household.load("standing")), 1)  # still watching
        told = self.later(61 * 86400)
        self.assertEqual(len(told), 1)
        self.assertIn("stopped watching for Hades", told[0])
        self.assertEqual(household.load("standing"), [])

    def test_interface_rows_and_cancel_all(self):
        self.patch(standing.psutil, "sensors_battery", lambda: SimpleNamespace(percent=50.0, power_plugged=True))
        self.watch(kind="battery", value=90)
        standing.AddRoutineTool().run_now(name="Evening tidy", request="tidy my downloads", time="18:00")
        rows = standing.snapshot()
        self.assertEqual(rows[0], {"label": "The battery to reach 90 percent", "detail": "watching"})
        self.assertEqual(rows[1], {"label": "Evening tidy", "detail": "18:00 · every day"})
        self.assertIn("Cancelled (2)", standing.CancelStandingTool().run_now(what="all").content)
        self.assertTrue(any(e["action"] == "watch_for" for e in sebas_actions.recent()))  # logged


class _Shredder(SebasTool):
    name = "test_shredder"
    description = "Delete a file for good. Cannot be undone."
    risky = True
    ran: list[str] = []

    def run(self, path: str = "") -> str:
        self.ran.append(path)
        return f"Deleted {path}."


class YesGate(_TempData):
    """A risky tool never runs on the model's say-so: only the user's next words release it."""

    def setUp(self):
        super().setUp()
        from openjarvis.core.registry import ToolRegistry

        if not ToolRegistry.contains("test_shredder"):
            ToolRegistry.register("test_shredder")(_Shredder)
        _Shredder.ran.clear()
        sebas_actions.answer("drop anything left over")

    def call(self):
        return _Shredder().execute(path="notes.txt")

    def test_parked_until_yes(self):
        result = self.call()
        self.assertIn("NOT DONE YET", result.content)
        self.assertEqual(_Shredder.ran, [])
        self.assertIn("path: notes.txt", sebas_actions.pending_summary())
        self.assertEqual(sebas_actions.answer("Yes, please."), "Done, sir. Deleted notes.txt.")
        self.assertEqual(_Shredder.ran, ["notes.txt"])
        self.assertIsNone(sebas_actions.answer("yes"))  # a yes releases it only once
        self.assertTrue(any(e["action"] == "test_shredder" and e["ok"] for e in sebas_actions.recent()))

    def test_no_cancels(self):
        self.call()
        self.assertIn("left it as it was", sebas_actions.answer("No."))
        self.assertEqual(_Shredder.ran, [])

    def test_anything_else_drops_it(self):
        self.call()
        self.assertIsNone(sebas_actions.answer("what's the weather?"))
        self.assertIsNone(sebas_actions.answer("yes"))  # too late: it was dropped
        self.assertEqual(_Shredder.ran, [])

    def test_a_late_yes_has_lapsed(self):
        self.call()
        with mock.patch.object(sebas_actions.time, "monotonic", return_value=sebas_actions.time.monotonic() + 600):
            self.assertIn("lapsed", sebas_actions.answer("yes"))
        self.assertEqual(_Shredder.ran, [])

    def test_from_discord_the_remote_gate_takes_it(self):
        asked = []
        self.patch(_base, "REMOTE_REQUEST", True)
        self.patch(_base, "confirm_remote", lambda tool, params, desc: asked.append(tool) or "asked on Discord")
        self.assertEqual(self.call().content, "asked on Discord")
        self.assertEqual((asked, _Shredder.ran, sebas_actions.pending_summary()), (["test_shredder"], [], ""))


if __name__ == "__main__":
    unittest.main()
