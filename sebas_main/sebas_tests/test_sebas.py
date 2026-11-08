"""Sebas's own tests: offline, no API keys, no microphone, no quota spent.

    run.bat --selftest
    .venv\\Scripts\\python.exe -m unittest discover sebas_tests -v

The Gemini chain is tested against stub providers, so key 1, key 2, the
Flash-Lite tier and the local model are all exercised without a request ever
leaving the laptop. (OpenJarvis's own tests live in tests/.)
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sebas_bootstrap import load_env  # noqa: E402

load_env()


class NameParsing(unittest.TestCase):
    def setUp(self):
        from voice_pipeline import name_listener as nl
        self.nl = nl

    def test_addressed(self):
        self.assertEqual(self.nl.split_address("Sebas, check GitHub."), "check GitHub.")
        self.assertEqual(self.nl.split_address("Hey Sebas what's the weather"), "what's the weather")
        self.assertEqual(self.nl.split_address("Seb us, open workspace"), "open workspace")
        self.assertIsNone(self.nl.split_address("I was talking to my friend"))

    def test_summon_and_rise(self):
        self.assertTrue(self.nl.is_summon("rise"))
        self.assertTrue(self.nl.is_summon(""))
        self.assertFalse(self.nl.is_summon("check my deployments"))
        self.assertEqual(self.nl.request_text("rise and check GitHub"), "check GitHub")

    def test_sleep_only_on_its_own(self):
        for s in ("Sebas, sleep", "good night", "that will be all", "Sebas go to sleep please"):
            self.assertTrue(self.nl.is_sleep_request(s), s)
        for s in ("turn off the wifi", "remind me to sleep at 11", "how did I sleep"):
            self.assertFalse(self.nl.is_sleep_request(s), s)


class LocalMatchers(unittest.TestCase):
    """Easter eggs and games are answered on the laptop, never sent to Gemini."""

    def test_eggs(self):
        import sebas_eggs
        self.assertEqual(sebas_eggs.check("El Psy Congroo").name, "divergence")
        self.assertEqual(sebas_eggs.check("are you merely a butler?").name, "butler")
        self.assertEqual(sebas_eggs.check("what's your power level").name, "power")
        self.assertIsNone(sebas_eggs.check("what's on my agenda"))
        self.assertEqual(sebas_eggs.check("Ains Oal Gown").name, "nazarick-on")
        self.assertEqual(sebas_eggs.check("Ainz Ooal Gown").name, "nazarick-off")  # a toggle

    def test_games(self):
        import sebas_games
        self.assertEqual(sebas_games.check("let's play tic tac toe")[0], "tictactoe")
        self.assertEqual(sebas_games.check("Sebas, pong")[0], "pong")
        self.assertEqual(sebas_games.check("play rock paper scissors")[0], "rps")
        self.assertEqual(sebas_games.check("play anime trivia")[0], "trivia")
        self.assertEqual(sebas_games.check("Sebas, connect 4")[0], "connect4")
        self.assertEqual(sebas_games.check("play some hang man")[0], "hangman")
        self.assertEqual(sebas_games.check("let's play snake")[0], "snake")
        self.assertIsNone(sebas_games.check("there is a snake in the garden"))
        self.assertIsNone(sebas_games.check("quiz me on DBMS"))  # study mode, not a game
        self.assertEqual(sebas_games.check("I'm bored"), (None, sebas_games._LINES[None]))
        for s in ("play some music", "what's my memory usage", "take a quiz on Friday", "turn off the wifi"):
            self.assertIsNone(sebas_games.check(s), s)


def _quota(seconds: int):
    from google.genai import errors
    return errors.ClientError(429, {"error": {"code": 429, "message": "Quota exceeded",
                                              "status": "RESOURCE_EXHAUSTED", "details": [{"retryDelay": f"{seconds}s"}]}})


class FailureClasses(unittest.TestCase):
    def test_classify(self):
        from google.genai import errors
        import httpx
        from sebas_brain import classify_failure

        self.assertEqual(classify_failure(_quota(40))[0], "quota-minute")
        self.assertEqual(classify_failure(_quota(30000))[0], "quota-day")
        self.assertEqual(classify_failure(errors.ServerError(503, {"error": {"code": 503, "message": "overloaded", "status": "UNAVAILABLE"}}))[0], "busy")
        self.assertEqual(classify_failure(errors.ClientError(401, {"error": {"code": 401, "message": "API key not valid", "status": "UNAUTHENTICATED"}}))[0], "bad-key")
        self.assertEqual(classify_failure(httpx.ConnectError("no route"))[0], "offline")
        self.assertEqual(classify_failure(httpx.ReadTimeout("slow"))[0], "busy")
        self.assertIsNone(classify_failure(ValueError("a bug, not a provider problem")))


class BrainChain(unittest.TestCase):
    """Flash (key 1, key 2) -> Flash-Lite (key 1, key 2) -> local, with stub models."""

    def setUp(self):
        import sebas_brain

        self.tmp = tempfile.TemporaryDirectory()
        spent = Path(self.tmp.name) / "spent_models.json"
        self.failing: dict[str, Exception] = {}  # model -> the error it raises
        self.calls: list[str] = []

        def fake_ask(brain, provider, text):
            self.calls.append(provider.model)
            if provider.model in self.failing:
                raise self.failing[provider.model]
            return f"answer from {provider.model}"

        patches = [
            mock.patch.dict(os.environ, {"GEMINI_API_KEY": "key-one", "GEMINI_API_KEY_2": "key-two"}),
            mock.patch.object(sebas_brain, "gemini_reachable", return_value=True),
            mock.patch.object(sebas_brain, "choose_gemini_models", side_effect=lambda k: [f"flash-a/{k}", f"flash-b/{k}"]),
            mock.patch.object(sebas_brain, "choose_lite_models", side_effect=lambda k: [f"lite/{k}"]),
            mock.patch.object(sebas_brain, "choose_local_models", return_value=["qwen-local"]),
            mock.patch.object(sebas_brain.Brain, "_spent_path", staticmethod(lambda: spent)),
            mock.patch.object(sebas_brain.Brain, "_start_local_keepalive", lambda *a, **k: None),
            mock.patch.object(sebas_brain.Brain, "_ask_once", fake_ask),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)
        self.spent = spent
        self.brain = sebas_brain.Brain()

    def test_first_model_answers(self):
        self.assertEqual(self.brain.ask("hello"), "answer from flash-a/key-one")

    def test_spent_model_moves_down_the_ladder_silently(self):
        self.failing["flash-a/key-one"] = _quota(30000)
        self.assertEqual(self.brain.ask("hello"), "answer from flash-b/key-one")
        # remembered across restarts, by a hash of the key, never the key itself
        saved = self.spent.read_text("utf-8")
        self.assertNotIn("key-one", saved.replace("flash-a/key-one", ""))
        self.assertEqual(len(json.loads(saved)), 1)

    def test_key_two_then_lite_then_local(self):
        for m in ("flash-a/key-one", "flash-b/key-one"):
            self.failing[m] = _quota(30000)
        self.assertEqual(self.brain.ask("hi"), "answer from flash-a/key-two")  # switching keys is silent
        for m in ("flash-a/key-two", "flash-b/key-two"):
            self.failing[m] = _quota(30000)
        reply = self.brain.ask("hi")
        self.assertTrue(reply.startswith("Today's Gemini quota is spent"), reply)
        self.assertTrue(reply.endswith("answer from lite/key-one"), reply)
        self.failing["lite/key-one"] = _quota(30000)
        self.failing["lite/key-two"] = _quota(30000)
        reply = self.brain.ask("hi")
        self.assertIn("local model", reply)
        self.assertTrue(reply.endswith("answer from qwen-local"))

    def test_per_minute_limit_rests_only_briefly(self):
        self.failing["flash-a/key-one"] = _quota(30)
        self.brain.ask("hi")
        self.assertFalse(self.spent.exists())  # a per-minute limit is not saved as a spent day

    def test_bugs_are_not_hidden_by_switching(self):
        self.failing["flash-a/key-one"] = ValueError("bug")
        with self.assertRaises(ValueError):
            self.brain.ask("hi")


class Discord(unittest.TestCase):
    def test_split_respects_the_limit(self):
        from sebas_discord import COMMAND_GUIDE, _split
        text = "\n".join(f"line {i} " + "x" * 80 for i in range(100))
        parts = _split(text)
        self.assertTrue(all(len(p) <= 1900 for p in parts))
        self.assertEqual("".join(parts).replace("\n", ""), text.replace("\n", ""))
        self.assertTrue(all(len(section) <= 2000 for section in COMMAND_GUIDE))  # one message each


class Safety(unittest.TestCase):
    def test_laptop_allowlist_has_no_big_system_commands(self):
        config = tomllib.loads((ROOT / "configs" / "sebas" / "laptop.toml").read_text("utf-8"))
        flat = json.dumps(config).lower()
        for word in ("shutdown", "restart", "format", "regedit", "rmdir", "del /", "bcdedit", "diskpart"):
            self.assertNotIn(word, flat, word)

    def test_remote_requests_need_a_yes(self):
        from custom_tools import _base
        self.assertTrue(hasattr(_base, "REMOTE_REQUEST"))
        self.assertTrue(hasattr(_base, "confirm_remote"))

    def test_secrets_file_is_ignored_by_git(self):
        ignore = (ROOT / ".gitignore").read_text("utf-8")
        self.assertRegex(ignore, r"(?m)^\.env\b")


if __name__ == "__main__":
    unittest.main()
