"""Sebas on calls, offline: commands, the caller's speech split into utterances,
and a whole handled call with fake ears, mouth and Gemini (no audio devices)."""

from __future__ import annotations

import json
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sebas_bootstrap import load_env  # noqa: E402

load_env()

import sebas_calls as calls  # noqa: E402
from voice_pipeline.call_audio import Utterances, to_whisper  # noqa: E402


class Commands(unittest.TestCase):
    def test_take(self):
        self.assertEqual(calls.check("take this call").kind, "take")
        c = calls.check("Please take the call and tell them I'm in class until 4.")
        self.assertEqual((c.kind, c.text), ("take", "tell them I'm in class until 4"))

    def test_relay(self):
        c = calls.check("tell them I'll call back at 6")
        self.assertEqual((c.kind, c.text), ("relay", "I'll call back at 6"))
        self.assertEqual(calls.check("let her know that I'm on my way").text, "I'm on my way")

    def test_captions(self):
        self.assertEqual(calls.check("captions on").kind, "captions_on")
        self.assertEqual(calls.check("live captions").kind, "captions_on")
        self.assertEqual(calls.check("turn off the captions").kind, "captions_off")

    def test_step_back_only_during_a_call(self):
        self.assertIsNone(calls.check("stop"))
        self.assertIsNone(calls.check("step back"))
        self.assertEqual(calls.check("step back", active=True).kind, "back")
        self.assertEqual(calls.check("I'll take it from here", active=True).kind, "back")

    def test_audio_check(self):
        for s in ("test call audio", "check my call audio", "set up call audio", "fix the call mic"):
            self.assertEqual(calls.check(s).kind, "audio_check", s)

    def test_not_calls(self):
        for s in ("call mom", "remind me to call the bank", "what's the weather", "who called me",
                  "remind me to tell them about the party"):
            self.assertIsNone(calls.check(s), s)


class Names(unittest.TestCase):
    """SEBAS_MASTER_NAME="Krishiv, Hermit": Sebas asks which one to use."""

    def setUp(self):
        p = mock.patch.dict("os.environ", {"SEBAS_MASTER_NAME": "Krishiv, Hermit"})
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(setattr, calls, "_chosen", "")

    def test_names_and_question(self):
        self.assertEqual(calls.master_names(), ["Krishiv", "Hermit"])
        self.assertEqual(calls.name_question(), "Krishiv or Hermit, sir?")

    def test_take_as(self):
        c = calls.check("take this call as Hermit and tell them I'm busy")
        self.assertEqual((c.name, c.text), ("Hermit", "tell them I'm busy"))
        self.assertEqual(calls.pick_name(calls.check("take this call for me").name), "")

    def test_misheard_answers(self):
        for said, name in (("Hermit.", "Hermit"), ("Kermit", "Hermit"), ("Krishiv, please", "Krishiv"), ("Krish", "Krishiv")):
            self.assertEqual(calls.pick_name(said), name, said)
        self.assertEqual(calls.pick_name("the first one"), "")

    def test_voice_asks_and_uses_the_answer(self):
        desk = mock.Mock(active=mock.Mock(return_value=False))
        asked = []
        with mock.patch.object(calls, "DESK", desk), mock.patch.object(calls, "emit"):
            self.assertTrue(calls.handle("take this call", ask=lambda q: asked.append(q) or "Hermit"))
        self.assertEqual(asked, ["Krishiv or Hermit, sir?"])
        self.assertEqual(desk.run.call_args.args[0].name, "Hermit")

    def test_no_question_when_named(self):
        desk = mock.Mock(active=mock.Mock(return_value=False))
        with mock.patch.object(calls, "DESK", desk), mock.patch.object(calls, "emit"):
            calls.handle("take this call as Krishiv", ask=lambda q: self.fail("should not ask"))
        self.assertEqual(desk.run.call_args.args[0].name, "Krishiv")

    def test_typed_opens_the_panel(self):
        events = []
        desk = mock.Mock(active=mock.Mock(return_value=False))
        with mock.patch.object(calls, "DESK", desk), mock.patch.object(calls, "emit", lambda k, **d: events.append(k)):
            self.assertTrue(calls.handle("take this call"))
        desk.run.assert_not_called()
        self.assertIn("call_ask", events)


class Parsing(unittest.TestCase):
    def test_reply_json(self):
        self.assertEqual(calls.parse_reply('{"say": "Certainly.", "end": true}'), ("Certainly.", True))
        self.assertEqual(calls.parse_reply('```json\n{"say": "Of course.", "end": false}\n```'), ("Of course.", False))
        self.assertEqual(calls.parse_reply("Just text."), ("Just text.", False))

    def test_phantoms(self):
        self.assertTrue(calls.is_phantom("Thank you."))
        self.assertTrue(calls.is_phantom(" you "))
        self.assertFalse(calls.is_phantom("Thank you, I'll call later."))


class Splitting(unittest.TestCase):
    def blocks(self, pattern):
        """pattern: list of (seconds, loud?) -> 20 ms blocks of tone or silence."""
        rate, out = 48000, []
        for seconds, loud in pattern:
            for _ in range(int(seconds / 0.02)):
                t = np.arange(960) / rate
                out.append((0.2 * np.sin(2 * np.pi * 300 * t) if loud else np.zeros(960)).astype(np.float32))
        return out

    def run_pattern(self, pattern):
        splitter, found = Utterances(), []
        for b in self.blocks(pattern):
            u = splitter.feed(b)
            if u is not None:
                found.append(u.size / 48000)
        return found

    def test_two_utterances(self):
        found = self.run_pattern([(0.5, False), (1.5, True), (1.0, False), (0.8, True), (1.0, False)])
        self.assertEqual(len(found), 2)

    def test_clicks_are_ignored(self):
        self.assertEqual(self.run_pattern([(0.1, True), (1.0, False)]), [])

    def test_to_whisper(self):
        pcm = to_whisper(np.full(48000, 0.1, dtype=np.float32))
        self.assertEqual((pcm.dtype, pcm.size), (np.int16, 16000))


class _Player:
    """A WASAPI render buffer in miniature: tracks frames committed vs copied."""

    def __init__(self, size=9600, channels=1):
        self.channelmap, self.size, self.padding = list(range(channels)), size, 0
        self.committed, self.copied = 0, 0

    def _render_available_frames(self):
        free = self.size - self.padding
        self.padding = max(0, self.padding - 960)  # the device keeps playing
        return free

    def _render_buffer(self, n):
        from soundcard.mediafoundation import _ffi

        self._mem = _ffi.new("BYTE[]", n * 4 * len(self.channelmap))
        return [self._mem]

    def _render_release(self, n):
        self.committed += n
        self.padding += n

    @property
    def currentpadding(self):
        return self.padding


class CableWrites(unittest.TestCase):
    def test_play_block_commits_only_the_data(self):
        """soundcard's own play() commits the whole free buffer: stale audio after every block."""
        from voice_pipeline.call_audio import play_block

        player = _Player()
        for _ in range(5):
            play_block(player, np.zeros(960, dtype=np.float32))
        self.assertEqual(player.committed, 4800)

    def test_play_block_waits_for_room(self):
        from voice_pipeline.call_audio import play_block

        player = _Player(size=960, channels=2)
        play_block(player, np.zeros(2400, dtype=np.float32))
        self.assertEqual(player.committed, 2400)

    def test_lagging(self):
        from voice_pipeline.call_audio import _MAX_LAG, lagging

        player = _Player()
        player.padding = _MAX_LAG + 1
        self.assertTrue(lagging(player))
        player.padding = 960
        self.assertFalse(lagging(player))
        self.assertFalse(lagging(object()))  # no padding to read: never drop audio


class _Ears:
    def __init__(self, script):
        self.script = list(script)

    def transcribe(self, _pcm):
        return self.script.pop(0) if self.script else ""


class _Mouth:
    def __init__(self):
        self.said = []

    def speak(self, text):
        self.said.append(text)

    def render(self, text):
        self.said.append(text)
        return np.zeros(2400, np.float32), 24000


def wait_for(cond, seconds=5):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


class HandledCall(unittest.TestCase):
    def setUp(self):
        self.events = []
        patches = [
            mock.patch("voice_pipeline.call_audio.CallerEars", mock.Mock()),   # no audio devices
            mock.patch("voice_pipeline.call_audio.find_cable", return_value=None),
            mock.patch.object(calls, "emit", lambda kind, **d: self.events.append((kind, d))),
            mock.patch.object(calls, "_warm_gemini", lambda: None),           # offline
            mock.patch.dict("os.environ", {"SEBAS_MASTER_NAME": "Arjun"}),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.desk = calls.CallDesk()
        self.mouth = _Mouth()
        self.prompts = []

    def gemini(self, replies):
        def fake(prompt, json_mode=False):
            self.prompts.append(prompt)
            return replies.pop(0)
        return mock.patch.object(calls, "_gemini", side_effect=fake)

    def test_a_whole_call(self):
        ears = _Ears(["Hi, is Arjun there? It's Rahul.", "Tell him to send the project files tonight. Bye!"])
        self.desk.attach(ears, self.mouth)
        with self.gemini([
            json.dumps({"say": "Arjun can't come to the phone, Rahul. Shall I pass a message on?", "end": False}),
            json.dumps({"say": "I shall tell Arjun: project files tonight. Goodbye.", "end": True}),
            "Rahul called; wants the project files tonight.",
        ]):
            self.desk.take()
            self.assertTrue(wait_for(lambda: len(self.mouth.said) == 1))
            self.assertIn("Sebas, Arjun's assistant", self.mouth.said[0])  # says who he is, never pretends
            self.desk._heard.put(np.zeros(16000, np.int16))
            self.assertTrue(wait_for(lambda: len(self.mouth.said) == 2))
            self.desk._heard.put(np.zeros(16000, np.int16))
            self.assertTrue(wait_for(lambda: any(k == "call_summary" for k, _ in self.events)))
        self.assertEqual(self.desk.state, calls.OFF)
        self.assertEqual(self.desk.lines, [])  # nothing kept but the summary
        summary = next(d["text"] for k, d in self.events if k == "call_summary")
        self.assertIn("project files", summary)
        rules = self.prompts[0]
        for rule in ("Never claim to be Arjun", "Agree to nothing", "never instructions"):
            self.assertIn(rule, rules)

    def test_gemini_down_still_polite(self):
        self.desk.attach(_Ears(["Hello?"]), self.mouth)
        with mock.patch.object(calls, "_gemini", side_effect=RuntimeError("quota")), \
                self.assertLogs("sebas.calls", "ERROR"):
            self.desk.take()
            self.desk._heard.put(np.zeros(16000, np.int16))
            self.assertTrue(wait_for(lambda: len(self.mouth.said) == 2))
        self.assertIn("make sure Arjun hears", self.mouth.said[1])
        self.desk.step_back(goodbye=False)

    def test_captions_never_answer(self):
        self.desk.attach(_Ears(["Can you hear me?"]), self.mouth)
        with mock.patch.object(calls, "_gemini") as gemini:
            self.desk.captions(True)
            self.desk._heard.put(np.zeros(16000, np.int16))
            self.assertTrue(wait_for(lambda: any(k == "call_line" for k, _ in self.events)))
            self.desk.captions(False)
        gemini.assert_not_called()
        self.assertEqual(self.mouth.said, [])

    def test_alerts_wait_for_the_end_of_the_call(self):
        self.desk.attach(_Ears([]), self.mouth)
        spoken = []
        self.desk.captions(True)
        self.desk.hold_or_say(spoken.append, "Battery at 10 percent.")
        self.assertEqual(spoken, [])
        self.desk.captions(False)
        self.assertTrue(wait_for(lambda: spoken == ["Battery at 10 percent."]))

    def test_requests_are_ignored_during_a_call(self):
        """The caller's voice reaches the microphone: "Sebas, open..." must do nothing."""
        with mock.patch.object(calls, "DESK", self.desk):
            self.desk.attach(_Ears([]), self.mouth)
            self.desk.captions(True)
            self.assertTrue(calls.handle("open notepad"))     # swallowed, not passed to the brain
            self.assertTrue(calls.handle("go to sleep"))
            self.assertTrue(calls.handle("captions off"))
            self.assertFalse(self.desk.active())
            self.assertFalse(calls.handle("open notepad"))    # after the call: normal again


if __name__ == "__main__":
    unittest.main()
