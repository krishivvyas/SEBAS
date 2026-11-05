"""Speech output with Kokoro."""

from __future__ import annotations

import io
import queue
import re
import threading

import numpy as np
import soundfile as sf
from openjarvis.speech.kokoro_tts import KokoroTTSBackend
from openjarvis.speech.voice_io import play_wav

from sebas_events import emit

_CHIME_RATE = 24000
_ENVELOPE_STEP = 0.04  # seconds per loudness value sent to the UI


def loudness_envelope(wav_bytes: bytes) -> list[float]:
    """Loudness of a WAV clip in 40 ms steps, scaled to 0..1, for lip-sync."""
    data, rate = sf.read(io.BytesIO(wav_bytes), dtype="float32")
    if data.ndim > 1:
        data = data.mean(axis=1)
    step = max(1, int(rate * _ENVELOPE_STEP))
    usable = data[: data.size - data.size % step]
    if usable.size == 0:
        return []
    rms = np.sqrt(np.mean(usable.reshape(-1, step) ** 2, axis=1))
    peak = float(rms.max()) or 1.0
    return [round(float(v) / peak, 3) for v in rms]


def clean_for_speech(text: str) -> str:
    """Remove formatting that would otherwise be read aloud."""
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)  # links keep their label
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"^\s*(#+|[-*+]|\d+\.|>)\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"[*_`~|]+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def split_sentences(text: str) -> list[str]:
    return [part for part in re.split(r"(?<=[.!?;:])\s+", text) if part]


class Mouth:
    """Speaks text through the default output device."""

    def __init__(self, voice: str) -> None:
        self._backend = KokoroTTSBackend(device="cpu")
        self._voice = voice
        # Reminders speak from a timer thread; one voice at a time.
        self._speaking = threading.Lock()

    def load(self) -> None:
        """Load the model now, so the first reply is not delayed by it."""
        self._synthesize("Ready.")

    def _synthesize(self, sentence: str) -> bytes:
        return self._backend.synthesize(
            sentence, voice_id=self._voice, output_format="wav"
        ).audio

    def speak(self, text: str) -> None:
        """Speak ``text``, starting as soon as its first sentence is ready."""
        with self._speaking:
            self._speak(text)

    def _speak(self, text: str) -> None:
        sentences = split_sentences(clean_for_speech(text))
        # Synthesis runs ahead of playback, so there are no gaps between sentences.
        ready: queue.Queue[bytes | None] = queue.Queue(maxsize=2)
        failures: list[Exception] = []

        def produce() -> None:
            try:
                for sentence in sentences:
                    ready.put(self._synthesize(sentence))
            except Exception as exc:
                failures.append(exc)
            finally:
                ready.put(None)

        threading.Thread(target=produce, daemon=True).start()
        emit("state", state="speaking")
        try:
            while (audio := ready.get()) is not None:
                if audio:
                    emit("speech", envelope=loudness_envelope(audio), step=_ENVELOPE_STEP)
                    play_wav(audio)
        finally:
            emit("state", state="idle")
        if failures:
            raise failures[0]

    def chime(self) -> None:
        """Play a short tone to show that Sebas is listening."""
        times = np.arange(int(_CHIME_RATE * 0.12)) / _CHIME_RATE
        tone = 0.2 * np.sin(2 * np.pi * 880 * times) * np.hanning(times.size)
        buffer = io.BytesIO()
        sf.write(buffer, tone, _CHIME_RATE, format="WAV")
        with self._speaking:
            play_wav(buffer.getvalue())
