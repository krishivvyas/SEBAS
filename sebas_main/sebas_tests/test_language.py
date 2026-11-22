"""English, Hindi and Gujarati: language choice, the name in three scripts,
voices chosen by script, the yes-gate's yes and no, and the pause settings.
Offline: no speech model is loaded (a stand-in plays Whisper)."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from voice_pipeline import ears as ears_mod  # noqa: E402
from voice_pipeline import name_listener as nl  # noqa: E402
from voice_pipeline.mouth import script_language, split_sentences  # noqa: E402


class FakeWhisper:
    """Answers like faster-whisper: detects ``detected`` unless told the language."""

    def __init__(self, detected: str, probs=None) -> None:
        self.detected, self.probs, self.calls = detected, probs or [], []

    def transcribe(self, audio, language=None, initial_prompt=None, **_):
        self.calls.append((language, initial_prompt))
        lang = language or self.detected
        info = SimpleNamespace(language=lang, all_language_probs=self.probs)
        return iter([SimpleNamespace(text=f" text in {lang}")]), info


def ears_with(fake, model="large-v3-turbo"):
    ears = ears_mod.Ears(model, 500)
    ears._model = fake
    return ears


class LanguageChoice(unittest.TestCase):
    def test_ours_are_kept(self):
        for lang in ("en", "hi", "gu"):
            self.assertEqual(ears_mod.pick_language(lang, []), lang)

    def test_others_become_the_likeliest_of_ours(self):
        probs = [("ur", 0.6), ("hi", 0.3), ("gu", 0.05), ("en", 0.05)]
        self.assertEqual(ears_mod.pick_language("ur", probs), "hi")
        self.assertEqual(ears_mod.pick_language("mr", [("mr", 0.7), ("gu", 0.2), ("hi", 0.1)]), "gu")

    def test_without_probabilities_urdu_and_marathi_mean_hindi(self):
        self.assertEqual(ears_mod.pick_language("ur", None), "hi")
        self.assertEqual(ears_mod.pick_language("mr", None), "hi")
        self.assertEqual(ears_mod.pick_language("fr", None), "en")

    def test_hindi_is_transcribed_once_without_the_english_prompt(self):
        fake = FakeWhisper("hi")
        text, lang = ears_with(fake).transcribe_with_language(np.zeros(16000, dtype=np.int16))
        self.assertEqual((text, lang), ("text in hi", "hi"))
        self.assertEqual(len(fake.calls), 1)

    def test_urdu_is_read_again_as_hindi(self):
        fake = FakeWhisper("ur", [("ur", 0.5), ("hi", 0.4), ("en", 0.1)])
        ears = ears_with(fake)
        text, lang = ears.transcribe_with_language(np.zeros(16000, dtype=np.int16))
        self.assertEqual(lang, "hi")
        self.assertEqual([c[0] for c in fake.calls], [None, "hi"])
        self.assertIsNone(fake.calls[1][1])  # no English vocabulary prompt on Hindi
        self.assertEqual(ears.last_language, "hi")

    def test_english_only_model_stays_english_with_the_prompt(self):
        fake = FakeWhisper("hi")
        _, lang = ears_with(fake, "tiny.en").transcribe_with_language(np.zeros(16000, dtype=np.int16))
        self.assertEqual(lang, "en")
        self.assertEqual(fake.calls[0][0], "en")
        self.assertIn("Sebas", fake.calls[0][1])

    def test_default_model_and_env_override(self):
        with mock.patch.dict(os.environ, {"SEBAS_WHISPER_MODEL": ""}):
            self.assertEqual(ears_mod.request_model(), "mix")
        with mock.patch.dict(os.environ, {"SEBAS_WHISPER_MODEL": "small   # faster"}):
            self.assertEqual(ears_mod.request_model(), "small")


class FakeModel:
    """A Whisper stand-in for the mix: detects ``lang``, transcribes as told."""

    def __init__(self, name, lang="en", text=None):
        self.name, self.lang, self.text, self.runs = name, lang, text, []

    def detect_language(self, audio):
        return self.lang, 0.9, [(self.lang, 0.9), ("en", 0.05)]

    def transcribe(self, audio, language=None, **_):
        self.runs.append(language)
        return iter([SimpleNamespace(text=self.text or f"{self.name}:{language}")]), SimpleNamespace(language=language)


class TheMix(unittest.TestCase):
    """tiny detects; small.en reads English; small (Hindi/Gujarati) loads only when needed."""

    def make(self, detect="en", indic="hi", indic_text=None):
        ears = ears_mod.Ears("mix", 500)
        opened = []

        def open_(name):
            opened.append(name)
            return {"tiny": FakeModel("tiny", detect), "small.en": FakeModel("small.en"),
                    "small": FakeModel("small", indic, indic_text)}[name]

        ears._open = open_
        notices = []
        ears.on_language_change = notices.append
        return ears, opened, notices

    def pcm(self):
        return np.zeros(16000, dtype=np.int16)

    def test_english_never_loads_the_hindi_gujarati_model(self):
        ears, opened, notices = self.make("en")
        with mock.patch.object(ears_mod.IdleRelease, "touch"):
            text, lang = ears.transcribe_with_language(self.pcm(), announce=True)
        self.assertEqual((text, lang), ("small.en:en", "en"))
        self.assertEqual(opened, ["tiny", "small.en"])
        self.assertFalse(ears.indic_loaded())
        self.assertEqual(notices, [])  # already English: nothing to say

    def test_hindi_loads_it_once_and_announces_once(self):
        ears, opened, notices = self.make("hi", "hi")
        with mock.patch.object(ears_mod.IdleRelease, "touch"):
            _, lang = ears.transcribe_with_language(self.pcm(), announce=True)
            ears.transcribe_with_language(self.pcm(), announce=True)
        self.assertEqual(lang, "hi")
        self.assertEqual(opened, ["tiny", "small.en", "small"])
        self.assertEqual(notices, ["hi"])

    def test_gujarati_taken_for_hindi_is_corrected_and_announced_once_as_gujarati(self):
        ears, _, notices = self.make("hi", "gu", indic_text="आजे शुं छे।")
        with mock.patch.object(ears_mod.IdleRelease, "touch"):
            text, lang = ears.transcribe_with_language(self.pcm(), announce=True)
        self.assertEqual(lang, "gu")
        self.assertEqual(text, "આજે શું છે.")  # Devanagari letters turned into Gujarati script
        self.assertEqual(notices, ["gu"])

    def test_back_to_english_is_announced(self):
        ears, _, notices = self.make("hi", "hi")
        with mock.patch.object(ears_mod.IdleRelease, "touch"):
            ears.transcribe_with_language(self.pcm(), announce=True)
            ears._models["detect"].lang = "en"
            ears.transcribe_with_language(self.pcm(), announce=True)
        self.assertEqual(notices, ["hi", "en"])

    def test_a_caller_speaking_hindi_is_not_announced(self):
        ears, _, notices = self.make("hi", "hi")
        with mock.patch.object(ears_mod.IdleRelease, "touch"):
            _, lang = ears.transcribe_with_language(self.pcm())  # calls and Discord: announce=False
        self.assertEqual((lang, notices), ("hi", []))

    def test_idle_release_lets_the_model_go(self):
        ears, opened, _ = self.make("hi", "hi")
        with mock.patch.object(ears_mod.IdleRelease, "touch"):
            ears.transcribe_with_language(self.pcm())
        self.assertTrue(ears.indic_loaded())
        ears._indic_idle._fire()
        self.assertFalse(ears.indic_loaded())
        with mock.patch.object(ears_mod.IdleRelease, "touch"):
            ears.transcribe_with_language(self.pcm())  # loads again when needed
        self.assertEqual(opened.count("small"), 2)

    def test_idle_timer_fires_after_the_set_minutes(self):
        fired = []
        with mock.patch.dict(os.environ, {"SEBAS_LANGUAGE_IDLE_MINUTES": "1"}),              mock.patch.object(ears_mod.threading, "Timer") as timer:
            ears_mod.IdleRelease(lambda: fired.append(1), "x").touch()
        self.assertEqual(timer.call_args[0][0], 60)

    def test_devanagari_to_gujarati(self):
        self.assertEqual(ears_mod.devanagari_to_gujarati("कल सुबह नौ बजे।"), "કલ સુબહ નૌ બજે.")
        self.assertEqual(ears_mod.devanagari_to_gujarati("GitHub ठीक"), "GitHub ઠીક")


class NameInThreeScripts(unittest.TestCase):
    def test_hindi_and_gujarati_spellings_wake_him(self):
        self.assertEqual(nl.split_address("सेबास, आज मेरा एजेंडा क्या है?"), "आज मेरा एजेंडा क्या है?")
        self.assertEqual(nl.split_address("સેબાસ, આજે શું છે?"), "આજે શું છે?")
        self.assertEqual(nl.split_address("सेबस, लाइट बंद करो"), "लाइट बंद करो")

    def test_other_hindi_words_do_not(self):
        self.assertIsNone(nl.split_address("सब ठीक है, चलो चलते हैं"))
        self.assertIsNone(nl.split_address("આજે શું છે?"))

    def test_english_unchanged(self):
        self.assertEqual(nl.split_address("Sebas, open YouTube"), "open YouTube")
        self.assertIsNone(nl.split_address("Several people came"))

    def test_rise_misheard_and_hindi_rise_are_summons(self):
        for said in ("Horizon.", "Nice.", "Raise", "", "rise", "उठो", "ઊઠો"):
            self.assertTrue(nl.is_summon(said), said)
        self.assertFalse(nl.is_summon("open YouTube"))
        self.assertFalse(nl.is_summon("आज मेरा एजेंडा क्या है"))


class VoiceByScript(unittest.TestCase):
    def test_script_language(self):
        self.assertEqual(script_language("Very good, sir."), "en")
        self.assertEqual(script_language("नमस्ते सर।"), "hi")
        self.assertEqual(script_language("આજે ત્રણ કામ છે."), "gu")
        self.assertEqual(script_language("आपका GitHub ठीक है।"), "hi")  # an app name inside Hindi
        self.assertEqual(script_language("Your GitHub PR #12 is ready, sir: नमस्ते"), "en")

    def test_hindi_sentences_split_at_the_danda(self):
        self.assertEqual(split_sentences("नमस्ते सर। आज तीन काम हैं।आपका दिन शुभ हो।"),
                         ["नमस्ते सर।", "आज तीन काम हैं।", "आपका दिन शुभ हो।"])
        self.assertEqual(split_sentences("One. Two!"), ["One.", "Two!"])

    def test_each_sentence_gets_its_voice(self):
        from voice_pipeline.mouth import Mouth

        mouth = Mouth(voice="bm_george")
        made = []
        mouth._kokoro = SimpleNamespace(create=lambda s, voice, speed, lang: made.append((voice, lang)) or (np.zeros(10), 24000))
        with mock.patch.dict(os.environ, {"SEBAS_HINDI_VOICE": "", "SEBAS_GUJARATI_VOICE": "kokoro"}):
            mouth.render("Very good, sir. नमस्ते सर। આજે ત્રણ કામ છે.")
        self.assertEqual(made, [("bm_george", "en-gb"), ("hm_omega", "hi"), ("hm_omega", "gu")])

    def test_gujarati_goes_to_the_native_voice_and_falls_back(self):
        from voice_pipeline import gujarati_voice
        from voice_pipeline.mouth import Mouth

        mouth = Mouth(voice="bm_george")
        made = []
        mouth._kokoro = SimpleNamespace(create=lambda s, voice, speed, lang: made.append((voice, lang)) or (np.zeros(10), 24000))
        native = mock.Mock(return_value=(np.full(1600, 0.1, dtype=np.float32), 16000))
        with mock.patch.dict(os.environ, {"SEBAS_GUJARATI_VOICE": ""}), mock.patch.object(gujarati_voice, "synthesize", native):
            audio, rate = mouth._create("આજે ત્રણ કામ છે.")
        self.assertEqual((rate, audio.size), (24000, 2400))  # resampled to Kokoro's rate
        self.assertTrue(0.25 < float(abs(audio).max()) <= 0.7)  # a quiet voice raised, at most x3
        self.assertEqual(made, [])
        broken = mock.Mock(side_effect=RuntimeError("no model"))
        with mock.patch.dict(os.environ, {"SEBAS_GUJARATI_VOICE": ""}), mock.patch.object(gujarati_voice, "synthesize", broken):
            mouth._create("આજે ત્રણ કામ છે.")
        self.assertEqual(made, [("hm_omega", "gu")])

    def test_gujarati_text_to_model_ids(self):
        from voice_pipeline.gujarati_voice import to_ids

        table = {"|": 0, "ક": 1, "ા": 2, "મ": 3, " ": 4, "એ": 5, "બ": 6, "ે": 7}
        self.assertEqual(to_ids("કામ!", table), [0, 1, 0, 2, 0, 3, 0])
        self.assertEqual(to_ids("કામ  ,  કામ", table), [0, 1, 0, 2, 0, 3, 0, 4, 0, 1, 0, 2, 0, 3, 0])
        self.assertEqual(to_ids("૨", table)[1::2], [6, 7])  # the digit read as the word "બે"


class YesAndNo(unittest.TestCase):
    def test_hindi_and_gujarati(self):
        import sebas_actions as actions

        for said in ("हाँ।", "हां जी", "Haan ji.", "ठीक है", "હા", "બરાબર", "yes."):
            self.assertIn(actions._normalise(said), actions._YES, said)
        for said in ("नहीं।", "नहीं, रहने दो", "ना", "ના.", "નહીં", "nahi", "no"):
            self.assertIn(actions._normalise(said), actions._NO, said)

    def test_an_unclear_answer_is_neither(self):
        import sebas_actions as actions

        said = actions._normalise("हाँ, लेकिन पहले बताओ")
        self.assertNotIn(said, actions._YES)
        self.assertNotIn(said, actions._NO)


class PausesAndLength(unittest.TestCase):
    def test_defaults(self):
        with mock.patch.dict(os.environ, {"SEBAS_PAUSE_SECONDS": "", "SEBAS_MAX_SPEECH_SECONDS": ""}):
            self.assertEqual(ears_mod.pause_seconds(), 1.2)
            self.assertEqual(ears_mod.max_speech_seconds(), 25.0)
            self.assertEqual(nl._end_silence_frames(), 15)  # 15 x 80 ms
            self.assertEqual(nl._max_frames(), int(25 * 16000 / 1280))

    def test_limits_and_bad_values(self):
        with mock.patch.dict(os.environ, {"SEBAS_PAUSE_SECONDS": "0.1", "SEBAS_MAX_SPEECH_SECONDS": "abc"}):
            self.assertEqual(ears_mod.pause_seconds(), 0.4)
            self.assertEqual(ears_mod.max_speech_seconds(), 25.0)
        with mock.patch.dict(os.environ, {"SEBAS_PAUSE_SECONDS": "2  # slow speaker"}):
            self.assertEqual(ears_mod.pause_seconds(), 2.0)

    def test_a_pause_shorter_than_the_setting_does_not_end_the_sentence(self):
        listener = nl.NameListener(ears=None, silence_threshold=100)
        loud, quiet = np.full((1280, 1), 3000, dtype=np.int16), np.zeros((1280, 1), dtype=np.int16)
        # speech, a 0.8 s pause (10 frames), more speech, then 1.2 s of quiet
        frames = [quiet] * 2 + [loud] * 6 + [quiet] * 10 + [loud] * 6 + [quiet] * 15
        stream = SimpleNamespace(read=lambda n, it=iter(frames): (next(it), False))
        with mock.patch.dict(os.environ, {"SEBAS_PAUSE_SECONDS": ""}), mock.patch.object(nl, "emit"):
            pcm = listener.next_utterance(stream)
        self.assertGreaterEqual(pcm.size, (6 + 10 + 6) * 1280)  # both halves in one utterance


if __name__ == "__main__":
    unittest.main()
