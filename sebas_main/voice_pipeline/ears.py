"""Speech recognition with faster-whisper, in English, Hindi and Gujarati.

The default request setup ("mix", ``SEBAS_WHISPER_MODEL``) was chosen by
measurement on this laptop (large-v3-turbo took 15-19 s a sentence; this takes
about 2 s for English and 4 s for Hindi or Gujarati):

    1. the tiny multilingual model detects the language (~0.3 s);
    2. if it says Hindi, the small model checks again, since tiny often takes
       Gujarati for Hindi;
    3. English is read by small.en (with Sebas's vocabulary), Hindi and
       Gujarati by small, told the language (detecting inside transcribe()
       would run the model twice);
    4. Whisper writes Gujarati in Devanagari letters; it is converted back to
       Gujarati script, letter for letter.

Only English, Hindi and Gujarati are allowed: Whisper otherwise now and then
takes Hindi for Urdu or Marathi. Any single model can still be named instead
(``SEBAS_WHISPER_MODEL=small``, ``large-v3-turbo``...); an English-only model
(``*.en``, such as the quick name model) stays in English.
"""

from __future__ import annotations

import io
import logging
import os
import threading
import time
import unicodedata
import wave

import numpy as np
from openjarvis.speech.voice_io import record_until_silence

logger = logging.getLogger("sebas.voice")

DEFAULT_MODEL = "mix"
_MIX = {"detect": "tiny", "en": "small.en", "indic": "small"}
LANGUAGES = ("en", "hi", "gu")
LANGUAGE_NAMES = {"en": "English", "hi": "Hindi", "gu": "Gujarati"}

# Priming Whisper with these words makes it spell them correctly, most
# importantly the name it listens for. Only used for English: an English prompt
# on Hindi speech nudges Whisper into writing the Hindi in Latin letters.
VOCABULARY_PROMPT = (
    "Sebas, the butler. Sebas, rise. Vercel, GitHub, AWS, EC2, Steam, Bookswagon, "
    "Antigravity, Gemini, Claude, Spotify, WhatsApp, Discord, AniList, Pomodoro, "
    "agenda, flashcards, DBMS, errand."
)


def request_model() -> str:
    """The model that reads requests (and callers, and Discord voice notes)."""
    return os.environ.get("SEBAS_WHISPER_MODEL", "").split("#")[0].strip() or DEFAULT_MODEL


def _threads() -> int:
    try:
        return max(1, int(os.environ.get("SEBAS_WHISPER_THREADS", "").split("#")[0] or 4))
    except ValueError:
        return 4  # measured: more threads were slower on this busy hybrid CPU


def vocabulary_prompt() -> str:
    """The fixed vocabulary plus the user's own contacts and projects."""
    extra: list[str] = []
    try:
        import tomllib
        from pathlib import Path

        path = Path(__file__).resolve().parents[1] / "configs" / "sebas" / "laptop.toml"
        config = tomllib.loads(path.read_text(encoding="utf-8"))
        extra = [name.title() for name in (config.get("contacts") or {})]
        extra += [name for name in (config.get("projects") or {})]
    except Exception:
        pass
    return VOCABULARY_PROMPT + (" " + ", ".join(extra) + "." if extra else "")


def pick_language(detected: str, probabilities: list[tuple[str, float]] | None) -> str:
    """The detected language if it is one of ours, else the likeliest of ours."""
    if detected in LANGUAGES:
        return detected
    ours = [(lang, p) for lang, p in (probabilities or []) if lang in LANGUAGES]
    if ours:
        return max(ours, key=lambda item: item[1])[0]
    # Urdu and Marathi are almost always Hindi when said to Sebas.
    return "hi" if detected in ("ur", "mr", "ne", "pa") else "en"


def devanagari_to_gujarati(text: str) -> str:
    """Whisper writes Gujarati speech in Devanagari; the two scripts line up
    letter for letter (0x0900 -> 0x0A80). Letters Gujarati lacks stay as they
    are; the danda becomes a full stop, as Gujarati writes it."""
    out = []
    for ch in unicodedata.normalize("NFD", text):  # क़ -> क + nukta, both of which Gujarati has
        code = ord(ch)
        if ch in "।॥":
            out.append(".")
        elif 0x0901 <= code <= 0x097F:
            twin = chr(code + 0x180)
            out.append(twin if unicodedata.name(twin, "") else ch)
        else:
            out.append(ch)
    return unicodedata.normalize("NFC", "".join(out))


def _ours(probabilities) -> list[tuple[str, float]]:
    return sorted(((lang, p) for lang, p in (probabilities or []) if lang in LANGUAGES), key=lambda x: -x[1])


def peak_rms(pcm: np.ndarray, frame_samples: int = 1024) -> float:
    """Return the loudest per-frame RMS of 16-bit audio."""
    if pcm.size == 0:
        return 0.0
    usable = pcm.size - pcm.size % frame_samples
    frames = (pcm[:usable] if usable else pcm).reshape(-1, min(frame_samples, pcm.size))
    return float(np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1)).max())


def wav_to_pcm(wav_bytes: bytes) -> np.ndarray:
    with wave.open(io.BytesIO(wav_bytes), "rb") as wav:
        return np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16)


# What Sebas says when the conversation changes language, in the new language.
LANGUAGE_NOTICES = {
    "en": "Switching back to English, sir.",
    "hi": "भाषा बदलकर हिंदी कर रहा हूँ, साहब।",
    "gu": "ભાષા બદલીને ગુજરાતી કરી રહ્યો છું, સાહેબ.",
}


def idle_minutes() -> float:
    """After this long without Hindi or Gujarati, their models are let go."""
    try:
        return max(1.0, float(os.environ.get("SEBAS_LANGUAGE_IDLE_MINUTES", "").split("#")[0] or 10))
    except ValueError:
        return 10.0


class IdleRelease:
    """Calls ``release`` once nothing has ``touch()``-ed it for ``idle_minutes()``."""

    def __init__(self, release, what: str) -> None:
        self._release, self._what = release, what
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()

    def touch(self) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(idle_minutes() * 60, self._fire)
            self._timer.daemon = True
            self._timer.start()

    def _fire(self) -> None:
        with self._lock:
            self._timer = None
        logger.info("Releasing %s after %.0f idle minutes", self._what, idle_minutes())
        self._release()


class Ears:
    """Transcribes 16 kHz speech with one Whisper model, or with the "mix".

    In the mix only the tiny detector and the English model are kept loaded.
    The Hindi and Gujarati model (small, multilingual) is loaded the first time
    one of those languages is detected, and let go again after
    SEBAS_LANGUAGE_IDLE_MINUTES (default 10) without them."""

    def __init__(self, model_size: str, silence_threshold: int) -> None:
        self._model_size = model_size
        self._silence_threshold = silence_threshold
        self._model = None
        self._models: dict[str, object] = {}  # "mix": detect / en, and indic only while in use
        self._load_lock = threading.Lock()
        self.mixed = model_size == "mix"
        self.english_only = model_size.endswith(".en")
        self.last_language = "en"  # of the most recent transcription (the user's, or a caller's)
        self.spoken_language = "en"  # of the conversation with the user, for the switch notice
        # Called with the new language before a switch is acted on, so Sebas can
        # say so while the model loads. Only for the user's own requests.
        self.on_language_change = None
        self._indic_idle = IdleRelease(self._release_indic, "the Hindi/Gujarati speech model")

    @staticmethod
    def _open(name: str):
        from faster_whisper import WhisperModel

        started = time.monotonic()
        model = WhisperModel(name, device="cpu", compute_type="int8", cpu_threads=_threads())
        logger.info("Speech model %s loaded in %.1f s", name, time.monotonic() - started)
        return model

    def load(self) -> None:
        """Load what is always needed: in the mix, the detector and English only."""
        with self._load_lock:
            if self.mixed:
                for role in ("detect", "en"):
                    if role not in self._models:
                        self._models[role] = self._open(_MIX[role])
            elif self._model is None:
                self._model = self._open(self._model_size)

    def indic_loaded(self) -> bool:
        return "indic" in self._models

    def _indic(self):
        """The Hindi/Gujarati model, loaded on first use and kept while in use."""
        with self._load_lock:
            if "indic" not in self._models:
                self._models["indic"] = self._open(_MIX["indic"])
        self._indic_idle.touch()
        return self._models["indic"]

    def _release_indic(self) -> None:
        with self._load_lock:
            dropped = self._models.pop("indic", None)
        if dropped is not None:
            del dropped
            import gc

            gc.collect()

    def _detect(self, audio: np.ndarray) -> str:
        """The mix's language: tiny decides; a "Hindi" is checked again by small,
        since tiny often takes Gujarati for Hindi."""
        detected, _, probabilities = self._models["detect"].detect_language(audio)
        language = pick_language(detected, probabilities)
        if language == "hi":
            _, _, probabilities = self._indic().detect_language(audio)
            ranked = _ours(probabilities)
            if ranked and ranked[0][0] == "gu":
                language = "gu"
        return language

    def _run(self, audio: np.ndarray, language: str | None, model=None):
        segments, info = (model or self._model).transcribe(
            audio,
            language=language,
            beam_size=1,
            initial_prompt=vocabulary_prompt() if language in (None, "en") else None,
            condition_on_previous_text=False,
            without_timestamps=True,
        )
        return "".join(segment.text for segment in segments).strip(), info

    def _announce(self, language: str) -> None:
        if language == self.spoken_language:
            return
        self.spoken_language = language
        if self.on_language_change is not None:
            try:
                self.on_language_change(language)
            except Exception:
                logger.exception("Could not announce the change of language")

    def transcribe_with_language(self, pcm: np.ndarray, announce: bool = False) -> tuple[str, str]:
        """Transcribe 16 kHz int16 mono audio; returns (text, "en" / "hi" / "gu").
        With ``announce`` (the user's own requests), a change of language is
        announced through ``on_language_change``."""
        self.load()
        audio = pcm.astype(np.float32) / 32768.0
        started = time.monotonic()
        if self.english_only:
            text, _ = self._run(audio, "en")
            language = "en"
        elif self.mixed:
            language = self._detect(audio)
            if announce:
                self._announce(language)  # said before the slower part, the transcription
            model = self._models["en"] if language == "en" else self._indic()
            text, _ = self._run(audio, language, model)
        else:
            text, info = self._run(audio, None)
            language = pick_language(info.language, getattr(info, "all_language_probs", None))
            if language != info.language:  # detected as Urdu, Marathi...: read again as ours
                text, _ = self._run(audio, language)
        if language == "gu":
            text = devanagari_to_gujarati(text)
        if announce and not self.mixed:
            self._announce(language)
        self.last_language = language
        logger.info("Transcribed %.1f s of speech in %d ms (%s, %s)", pcm.size / 16000,
                    (time.monotonic() - started) * 1000, self._model_size, language)
        return text, language

    def transcribe(self, pcm: np.ndarray, announce: bool = False) -> str:
        """Transcribe 16 kHz int16 mono audio (the language is kept in ``last_language``)."""
        return self.transcribe_with_language(pcm, announce)[0]

    def listen(self, wait_seconds: float = 6.0, announce: bool = True) -> str:
        """Record one utterance; return "" if nobody starts speaking within ``wait_seconds``."""
        pcm = wav_to_pcm(
            record_until_silence(
                silence_threshold=self._silence_threshold,
                startup_silence_seconds=wait_seconds,
                silence_seconds=max(1.5, pause_seconds()),
                max_seconds=max_speech_seconds(),
            )
        )
        # Whisper tends to invent words from silence, so never send it silence.
        if peak_rms(pcm) < self._silence_threshold:
            return ""
        return self.transcribe(pcm, announce)


def pause_seconds() -> float:
    """How long a pause may be before Sebas takes the sentence as finished."""
    try:
        return min(4.0, max(0.4, float(os.environ.get("SEBAS_PAUSE_SECONDS", "").split("#")[0] or 1.2)))
    except ValueError:
        return 1.2


def max_speech_seconds() -> float:
    try:
        return min(120.0, max(5.0, float(os.environ.get("SEBAS_MAX_SPEECH_SECONDS", "").split("#")[0] or 25)))
    except ValueError:
        return 25.0
