"""The coding delegate, offline: a real git repository in a temporary folder, and a
small script standing in for Claude Code (no Claude, no Antigravity, no network)."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sebas_bootstrap import load_env  # noqa: E402

load_env()

import sebas_actions  # noqa: E402
from custom_tools import coding, laptop  # noqa: E402

# Stands in for `claude -p`: reads the brief from stdin, acts by MODE, prints Claude's JSON.
FAKE_CLAUDE = textwrap.dedent('''
    import json, pathlib, sys, time
    mode, brief = sys.argv[1], sys.stdin.read()
    assert "Do not commit" in brief and "SPOKEN:" in brief
    if mode == "works":
        pathlib.Path("calc.py").write_text("def add(a, b):\\n    return a + b\\n")
        pathlib.Path("notes.txt").write_text("new file")
        print(json.dumps({"type": "result", "is_error": False,
                          "result": "Fixed `add`.\\n\\nSPOKEN: I corrected the **add** function. All tests pass."}))
    elif mode == "limit":
        print(json.dumps({"type": "result", "is_error": True, "result": "Usage limit reached"}))
        sys.exit(1)
    elif mode == "breaks":
        pathlib.Path("calc.py").write_text("broken")
        print(json.dumps({"type": "result", "is_error": True, "result": "Lost the connection"}))
        sys.exit(1)
    elif mode == "slow":
        time.sleep(60)
''')


def git(folder: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=folder, capture_output=True, text=True, check=True).stdout.strip()


class _Repo(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.repo = root / "calc"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "config", "user.email", "test@example.com")
        git(self.repo, "config", "user.name", "Test")
        (self.repo / "calc.py").write_text("def add(a, b):\n    return a - b\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-q", "-m", "start")
        self.fake = root / "fake_claude.py"
        self.fake.write_text(FAKE_CLAUDE)
        self.said: list[str] = []
        self.antigravity: list[list[str]] = []
        config = {"projects": {"calc": str(self.repo)}, "coding": {"minutes": 0.05}}
        for target, name, value in (
            (coding, "_section", lambda name: config.get(name, {})),
            (coding, "_lookup", lambda section, name: config[section][name]),
            (coding, "get_data_dir", lambda: root / "data"),
            (sebas_actions, "get_data_dir", lambda: root / "data"),
            (laptop, "_announce", self.said.append),
            (coding, "antigravity_command", lambda prompt: None),
            (coding, "_job", None),
        ):
            p = mock.patch.object(target, name, value)
            p.start()
            self.addCleanup(p.stop)

    def claude(self, mode: str | None):
        p = mock.patch.object(coding, "claude_command", lambda: [sys.executable, str(self.fake), mode] if mode else None)
        p.start()
        self.addCleanup(p.stop)

    def delegate(self, task: str = "Fix the failing add test in the calc project"):
        result = coding.DelegateCodingTool().run_now(project="calc", task=task)
        if result.success:
            coding._job["thread"].join(timeout=30)
        return result


class Delegate(_Repo):
    def test_claude_works_on_a_branch_and_commits_nothing(self):
        self.claude("works")
        result = self.delegate()
        self.assertTrue(result.success, result.content)
        self.assertIn("sebas/fix-failing-add-test-calc", result.content)
        self.assertEqual(git(self.repo, "branch", "--show-current"), "sebas/fix-failing-add-test-calc")
        self.assertEqual(git(self.repo, "rev-list", "--count", "HEAD"), "1")  # nothing committed
        self.assertEqual(len(self.said), 1)
        self.assertIn("I corrected the add function. All tests pass.", self.said[0])  # markdown stripped for speech
        self.assertIn("2 files changed on the branch sebas/fix-failing-add-test-calc", self.said[0])
        report = Path(coding._job["report"]).read_text("utf-8")
        self.assertIn("calc.py", report)
        self.assertIn("Fixed `add`.", report)
        self.assertIn("ended as: done", coding.CodingStatusTool().run_now().content)
        self.assertTrue(any(e["action"] == "delegate_coding" and e["ok"] for e in sebas_actions.recent()))

    def test_uncommitted_work_is_refused_and_no_branch_is_made(self):
        self.claude("works")
        (self.repo / "calc.py").write_text("my own unsaved work")
        result = self.delegate()
        self.assertFalse(result.success)
        self.assertIn("uncommitted", result.content)
        self.assertEqual(git(self.repo, "branch", "--format=%(refname:short)"), "main")
        self.assertEqual((self.repo / "calc.py").read_text(), "my own unsaved work")

    def test_a_second_branch_gets_its_own_name(self):
        git(self.repo, "branch", "sebas/fix-failing-add-test-calc")
        self.assertEqual(coding._new_branch(self.repo, "Fix the failing add test in the calc project"),
                         "sebas/fix-failing-add-test-calc-2")

    def test_discard_needs_a_yes_and_restores_the_project(self):
        self.claude("works")
        self.delegate()
        parked = coding.DiscardCodingTool().execute()
        self.assertIn("NOT DONE YET", parked.content)
        self.assertIn("return to main", sebas_actions.pending_summary())
        self.assertEqual(git(self.repo, "branch", "--show-current"), "sebas/fix-failing-add-test-calc")  # untouched so far
        self.assertIn("back on main", sebas_actions.answer("yes"))
        self.assertEqual(git(self.repo, "branch", "--format=%(refname:short)"), "main")
        self.assertEqual((self.repo / "calc.py").read_text(), "def add(a, b):\n    return a - b\n")
        self.assertFalse((self.repo / "notes.txt").exists())

    def test_claude_unavailable_before_any_change_goes_to_antigravity(self):
        self.claude("limit")
        started = []
        quiet = mock.patch.object(coding, "_watch_until_quiet", lambda job: started.append(job["agent"]))
        launched = mock.patch.object(coding, "antigravity_command", lambda prompt: [sys.executable, "-c", "pass"])
        with quiet, launched:
            self.delegate()
        self.assertEqual(started, ["Antigravity"])
        self.assertIn("Usage limit reached", self.said[0])
        self.assertIn("Antigravity", self.said[0])

    def test_not_installed_and_no_antigravity_says_so(self):
        self.claude(None)
        result = self.delegate()
        self.assertIn("Antigravity's agent", result.content)
        self.assertIn("Claude Code is not installed, and Antigravity was not found", self.said[0])
        self.assertEqual(coding._job["state"], "failed")

    def test_failure_after_edits_is_reported_not_handed_on(self):
        self.claude("breaks")
        with mock.patch.object(coding, "_fall_back", side_effect=AssertionError("must not fall back")):
            self.delegate()
        self.assertIn("stopped with an error part-way", self.said[0])
        self.assertIn("1 file changed", self.said[0])

    def test_time_limit_stops_claude(self):
        self.claude("slow")  # sleeps a minute; the limit here is three seconds
        self.delegate()
        self.assertEqual(coding._job["state"], "timeout")
        self.assertIn("ran out of time", self.said[0])

    def test_one_job_at_a_time_and_stop(self):
        self.claude("slow")
        with mock.patch.object(coding, "_minutes", lambda: 5):
            self.assertTrue(coding.DelegateCodingTool().run_now(project="calc", task="Fix the failing add test").success)
            for _ in range(100):  # wait for the process to exist
                if coding._job.get("proc") is not None:
                    break
                __import__("time").sleep(0.05)
            self.assertIn("working", coding.snapshot()["detail"])
            second = coding.DelegateCodingTool().run_now(project="calc", task="Add a subtract function")
            self.assertFalse(second.success)
            self.assertIn("One job at a time", second.content)
            self.assertFalse(coding.DiscardCodingTool().run_now().success)  # not while it runs
            self.assertIn("Claude has been stopped", coding.StopCodingTool().run_now().content)
            coding._job["thread"].join(timeout=30)
        self.assertEqual(self.said, [])  # the user stopped it himself: no announcement needed
        self.assertIsNone(coding.snapshot())

    def test_antigravity_is_judged_finished_when_files_go_quiet(self):
        job = {"project": "calc", "folder": self.repo, "task": "t", "branch": "main", "base": "main",
               "agent": "Antigravity", "state": "running", "started": 0}
        clock = {"t": 0.0}

        def sleep(seconds):
            clock["t"] += seconds
            if clock["t"] == 40:  # the agent writes a file a little after starting
                (self.repo / "calc.py").write_text("def add(a, b):\n    return a + b\n")

        with mock.patch.object(coding.time, "sleep", sleep), mock.patch.object(coding.time, "monotonic", lambda: clock["t"]), \
                mock.patch.object(coding, "_minutes", lambda: 20):
            coding._watch_until_quiet(job)
        self.assertEqual(job["state"], "done")
        self.assertEqual(clock["t"], 40 + coding._QUIET_SECONDS)
        self.assertIn("1 file changed", self.said[0])

    def test_the_commands_claude_is_given(self):
        with mock.patch.object(coding.shutil, "which", lambda name: "claude.exe"):
            command = coding.claude_command()
        allowed = command[command.index("--allowedTools") + 1]
        refused = command[command.index("--disallowedTools") + 1]
        self.assertIn("acceptEdits", command)
        self.assertNotIn("bypassPermissions", command)
        # the user's own settings (which may allow every command) are not loaded,
        # and only these tools exist for the job: no PowerShell, web or connectors
        self.assertEqual(command[command.index("--setting-sources") + 1], "")
        self.assertEqual(command[command.index("--tools") + 1], "Read,Edit,Write,Glob,Grep,Bash")
        self.assertIn("--strict-mcp-config", command)
        for rule in ("Edit", "Bash(pytest *)", "Bash(npm run build *)", "Bash(git diff *)"):
            self.assertIn(rule, allowed)
        for word in ("git commit", "git push", "rm ", "pip", "curl"):
            self.assertNotIn(f"Bash({word}", allowed)
        for rule in ("Bash(git commit *)", "Bash(git push *)"):
            self.assertIn(rule, refused)
        env = coding._child_env()
        self.assertFalse(any(k.upper().startswith("CLAUDE") for k in env))


if __name__ == "__main__":
    unittest.main()
