"""Speech output with Kokoro, run through ONNX Runtime (no PyTorch).

The same Kokoro voices (bm_george and friends) as the PyTorch build, at about a
fifth of the memory: measured on this laptop, ~205 MB instead of ~1,140 MB,
loading in 2 s instead of 10 s. The fp16 model and voices (~200 MB) are
downloaded to ~/.cache/sebas/kokoro on first use.
"""

from __future__ import annotations

import io
import logging
import os
import queue
import re
import threading
from pathlib import Path

import numpy as np
import soundfile as sf
from openjarvis.speech.voice_io import play_wav

from sebas_events import emit

logger = logging.getLogger(__name__)

_CHIME_RATE = 24000
_MODEL_DIR = Path(os.environ.get("SEBAS_TTS_DIR") or Path.home() / ".cache" / "sebas" / "kokoro")
_MODEL_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
_MODEL_FILE, _VOICES_FILE = "kokoro-v1.0.fp16.onnx", "voices-v1.0.bin"
_TTS_THREADS = 4  # faster than real time on this CPU without hogging every core


def _ensure_model_files() -> tuple[Path, Path]:
    import httpx

    _MODEL_DIR.mkdir(parents=True, exist_ok=True)
    for name in (_MODEL_FILE, _VOICES_FILE):
        target = _MODEL_DIR / name
        if target.exists() and target.stat().st_size > 1_000_000:
            continue
        logger.warning("Downloading the voice model %s (first run only)...", name)
        partial = target.with_suffix(".part")
        with httpx.stream("GET", _MODEL_URL + name, follow_redirects=True, timeout=120) as response:
            response.raise_for_status()
            with open(partial, "wb") as fh:
                for chunk in response.iter_bytes(1 << 20):
                    fh.write(chunk)
        partial.replace(target)
    return _MODEL_DIR / _MODEL_FILE, _MODEL_DIR / _VOICES_FILE


def _load_kokoro():
    import onnxruntime as ort
    from kokoro_onnx import Kokoro

    model, voices = _ensure_model_files()
    options = ort.SessionOptions()
    options.enable_cpu_mem_arena = False  # the arena alone held ~400 MB that speech never needed
    options.intra_op_num_threads = _TTS_THREADS
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    session = ort.InferenceSession(str(model), options, providers=["CPUExecutionProvider"])
    return Kokoro.from_session(session, str(voices))
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
        self._kokoro = None
        self._voice = voice
        self._lang = "en-gb" if voice.startswith("b") else "en-us"
        # Reminders speak from a timer thread; one voice at a time.
        self._speaking = threading.Lock()

    def load(self) -> None:
        """Load the model now, so the first reply is not delayed by it."""
        self._synthesize("Ready.")

    def _synthesize(self, sentence: str) -> bytes:
        if self._kokoro is None:
            self._kokoro = _load_kokoro()
        audio, rate = self._kokoro.create(sentence, voice=self._voice, speed=1.0, lang=self._lang)
        buffer = io.BytesIO()
        sf.write(buffer, audio, rate, format="WAV")
        return buffer.getvalue()

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
