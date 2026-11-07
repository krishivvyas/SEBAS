"""Speech recognition with faster-whisper."""

from __future__ import annotations

import io
import wave

import numpy as np
from openjarvis.speech.voice_io import record_until_silence

# Priming Whisper with these words makes it spell them correctly, most
# importantly the name it listens for.
VOCABULARY_PROMPT = (
    "Sebas, the butler. Vercel, GitHub, AWS, EC2, Steam, Bookswagon, "
    "Antigravity, Gemini, Claude."
)


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


class Ears:
    """Transcribes 16 kHz speech with one Whisper model."""

    def __init__(self, model_size: str, silence_threshold: int) -> None:
        self._model_size = model_size
        self._silence_threshold = silence_threshold
        self._model = None

    def load(self) -> None:
        if self._model is None:
            from faster_whisper import WhisperModel

            # 4 threads: quick enough, and leaves the rest of the laptop responsive
            self._model = WhisperModel(self._model_size, device="cpu", compute_type="int8", cpu_threads=4)

    def transcribe(self, pcm: np.ndarray) -> str:
        """Transcribe 16 kHz int16 mono audio."""
        self.load()
        segments, _ = self._model.transcribe(
            pcm.astype(np.float32) / 32768.0,
            language="en",
            beam_size=1,
            initial_prompt=VOCABULARY_PROMPT,
            condition_on_previous_text=False,
        )
        return "".join(segment.text for segment in segments).strip()

    def listen(self, wait_seconds: float = 6.0) -> str:
        """Record one utterance; return "" if nobody starts speaking within ``wait_seconds``."""
        pcm = wav_to_pcm(
            record_until_silence(
                silence_threshold=self._silence_threshold,
                startup_silence_seconds=wait_seconds,
            )
        )
        # Whisper tends to invent words from silence, so never send it silence.
        if peak_rms(pcm) < self._silence_threshold:
            return ""
        return self.transcribe(pcm)
