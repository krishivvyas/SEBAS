"""Voice on Discord, offline: audio formats, and the bridge with fake Discord objects."""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sebas_bootstrap import load_env  # noqa: E402

load_env()

import sebas_discord_voice as dv  # noqa: E402

OWNER = 1001


def tone(seconds: float, rate: int = 24000) -> np.ndarray:
    t = np.arange(int(seconds * rate)) / rate
    return (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


class Formats(unittest.TestCase):
    def test_voice_note_round_trip(self):
        note = dv.voice_note(tone(2.0), 24000)
        self.assertEqual(note[:4], b"OggS")  # Discord plays OGG Opus inline
        pcm = dv.decode_audio(note)
        self.assertEqual(pcm.dtype, np.int16)
        self.assertAlmostEqual(pcm.size / 16000, 2.0, delta=0.1)

    def test_long_notes_are_refused(self):
        with self.assertRaises(dv.NoteTooLong):
            dv.decode_audio(dv.voice_note(tone(3.0), 24000), max_seconds=1)

    def test_voice_channel_pcm(self):
        pcm = dv.discord_pcm(tone(1.0), 24000)
        self.assertEqual(len(pcm), 48000 * 2 * 2)  # 48 kHz, stereo, 16-bit

    def test_long_replies_are_spoken_in_part(self):
        short = "All is well, sir."
        self.assertEqual(dv.spoken_part(short), short)
        long = dv.spoken_part("**Item** one is here. " * 80)
        self.assertLessEqual(len(long), dv.SPOKEN_CHARS + 40)
        self.assertTrue(long.endswith("written above, sir."))
        self.assertNotIn("*", long)

    def test_silence_is_not_transcribed(self):
        kit = dv.VoiceKit(ears=mock.Mock(), mouth=mock.Mock())
        self.assertEqual(kit.transcribe(dv.voice_note(np.zeros(24000, np.float32), 24000)), "")
        kit._ears.transcribe.assert_not_called()  # Whisper would invent words from silence


class _Typing:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _message(author: int, heard_from_note: bool = True, text: str = ""):
    channel = SimpleNamespace(id=5, typing=lambda: _Typing(), send=mock.AsyncMock())
    note = SimpleNamespace(is_voice_message=lambda: True, content_type="audio/ogg", size=30_000, duration=3.0,
                           read=mock.AsyncMock(return_value=b"OggS..."))
    return SimpleNamespace(author=SimpleNamespace(bot=False, id=author), channel=channel, content=text,
                           attachments=[note] if heard_from_note else [], reply=mock.AsyncMock())


class Bridge(unittest.TestCase):
    def setUp(self):
        import sebas_discord

        self.bridge = sebas_discord.DiscordBridge(brain=mock.Mock(), is_sleep=lambda t: "sleep" in t.lower())
        self.bridge.owner_id = OWNER
        self.bridge.channels = {"sebas": SimpleNamespace(id=5)}
        self.bridge.voice = mock.Mock()
        self.bridge.voice.render.return_value = (tone(0.5), 24000)
        self.asked: list[str] = []

        def ask(text):
            self.asked.append(text)
            return "Your agenda is clear, sir."

        self.bridge._ask_remote = ask

    def run_message(self, message):
        asyncio.run(self.bridge._on_message(message))
        return [c.args[0] for c in message.reply.call_args_list]

    def test_voice_note_answered_with_text_and_a_voice_note(self):
        self.bridge.voice.transcribe.return_value = "What's on my agenda?"
        message = _message(OWNER)
        replies = self.run_message(message)
        self.assertEqual(replies, ["🎙️ *What's on my agenda?*", "Your agenda is clear, sir."])
        self.assertEqual(self.asked, ["What's on my agenda?"])
        sent = message.channel.send.call_args.kwargs["file"]
        self.assertEqual(sent.filename, "sebas.ogg")

    def test_typed_message_gets_no_voice_note(self):
        message = _message(OWNER, heard_from_note=False, text="what's on my agenda")
        self.assertEqual(self.run_message(message), ["Your agenda is clear, sir."])
        message.channel.send.assert_not_called()
        self.bridge.voice.render.assert_not_called()

    def test_only_the_master_is_heard(self):
        message = _message(OWNER + 1)
        self.assertEqual(self.run_message(message), [])
        self.bridge.voice.transcribe.assert_not_called()  # not even transcribed

    def test_spoken_yes_confirms_a_laptop_action(self):
        self.bridge.voice.transcribe.return_value = "Yes."
        self.bridge._pending = {"tool": "open_app", "params": {}, "asked": 0}
        with mock.patch.object(self.bridge, "_answer_confirmation", mock.AsyncMock()) as answer:
            self.run_message(_message(OWNER))
        answer.assert_awaited_once()
        self.assertEqual(answer.await_args.args[1], "yes")
        self.assertEqual(self.asked, [])

    def test_sleep_is_still_refused_by_voice(self):
        import sebas_discord

        self.bridge.voice.transcribe.return_value = "Sebas, go to sleep."
        replies = self.run_message(_message(OWNER))
        self.assertEqual(replies[-1], sebas_discord.SLEEP_REFUSAL)
        self.assertEqual(self.asked, [])

    def test_empty_note(self):
        self.bridge.voice.transcribe.return_value = ""
        self.assertEqual(self.run_message(_message(OWNER)), ["I heard no words in that note, sir."])
        self.assertEqual(self.asked, [])


if __name__ == "__main__":
    unittest.main()
