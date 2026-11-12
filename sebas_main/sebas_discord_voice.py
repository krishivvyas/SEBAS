"""Sebas's voice on Discord: voice notes in, voice notes out, and speech in a voice channel.

Hearing: a voice note the master sends in #sebas (hold the mic in the Discord
app) is decoded in memory and transcribed on the laptop with the same Whisper
model as voice mode. The audio is never written to disk, never kept, and never
sent anywhere else.

Speaking: a reply to a voice note comes back as text plus a voice note in his own
Kokoro voice. While the master is in Sebas's voice channel, he joins and speaks
his replies and #alerts there instead.

Listening live in a voice channel is deliberately not supported: since March 2026
Discord encrypts every call end to end (DAVE), and receiving that audio needs an
unofficial, unfinished library. Sending it is officially supported (PyNaCl and
davey, both installed with discord.py[voice]).
"""

from __future__ import annotations

import io
import logging
import os
import threading
from math import gcd

import numpy as np

logger = logging.getLogger("sebas.discord")

MAX_NOTE_SECONDS = 180          # a longer note is politely refused
MAX_NOTE_BYTES = 8_000_000
SPOKEN_CHARS = 700              # longer replies are spoken in part; the text has the rest
_WHISPER_RATE = 16000
_DISCORD_RATE = 48000


class NoteTooLong(ValueError):
    pass


def decode_audio(data: bytes, rate: int = _WHISPER_RATE, max_seconds: float = MAX_NOTE_SECONDS) -> np.ndarray:
    """Any audio file Discord sends (voice notes are OGG Opus) as int16 mono at ``rate``."""
    import av

    chunks: list[np.ndarray] = []
    total = 0
    with av.open(io.BytesIO(data)) as container:
        stream = container.streams.audio[0]
        resampler = av.AudioResampler(format="s16", layout="mono", rate=rate)
        frames = [*container.decode(stream), None]  # None flushes the resampler
        for frame in frames:
            for out in resampler.resample(frame):
                chunk = out.to_ndarray().reshape(-1).astype(np.int16)
                total += chunk.size
                if total > rate * max_seconds:
                    raise NoteTooLong(f"longer than {max_seconds:.0f} seconds")
                chunks.append(chunk)
    return np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.int16)


def spoken_part(text: str, limit: int = SPOKEN_CHARS) -> str:
    """What to say aloud: the whole reply, or its opening sentences when it is long."""
    from voice_pipeline.mouth import clean_for_speech, split_sentences

    clean = clean_for_speech(text)
    if len(clean) <= limit:
        return clean
    said = ""
    for sentence in split_sentences(clean):
        if len(said) + len(sentence) > limit:
            break
        said += sentence + " "
    return (said or clean[:limit]).strip() + " The rest is written above, sir."


def voice_note(audio: np.ndarray, rate: int) -> bytes:
    """Float audio as an OGG Opus file, which Discord plays inline."""
    import soundfile as sf

    buffer = io.BytesIO()
    sf.write(buffer, np.clip(audio, -1, 1), rate, format="OGG", subtype="OPUS")
    return buffer.getvalue()


def discord_pcm(audio: np.ndarray, rate: int) -> bytes:
    """Float mono audio as the 48 kHz 16-bit stereo PCM a Discord voice channel takes."""
    from scipy.signal import resample_poly

    g = gcd(_DISCORD_RATE, rate)
    pcm = resample_poly(np.asarray(audio, dtype=np.float32), _DISCORD_RATE // g, rate // g)
    pcm = (np.clip(pcm, -1, 1) * 32767).astype("<i2")
    return np.repeat(pcm, 2).tobytes()  # left, right


class VoiceKit:
    """Whisper and Kokoro for Discord: the laptop's own when voice mode has loaded
    them, else loaded on first use (e.g. with typing only, or voice unavailable)."""

    def __init__(self, ears=None, mouth=None) -> None:
        self._ears, self._mouth = ears, mouth
        self._loading = threading.Lock()

    def attach(self, ears=None, mouth=None) -> None:
        self._ears = ears or self._ears
        self._mouth = mouth or self._mouth

    def _get_ears(self):
        with self._loading:
            if self._ears is None:
                from voice_pipeline.ears import Ears

                threshold = int(float(os.environ.get("SEBAS_SILENCE_THRESHOLD") or 500))
                self._ears = Ears(os.environ.get("SEBAS_WHISPER_MODEL") or "small.en", threshold)
            return self._ears

    def _get_mouth(self):
        with self._loading:
            if self._mouth is None:
                from voice_pipeline.mouth import Mouth

                self._mouth = Mouth(voice=os.environ.get("SEBAS_VOICE") or "bm_george")
            return self._mouth

    def transcribe(self, data: bytes) -> str:
        pcm = decode_audio(data)
        if pcm.size < _WHISPER_RATE * 0.3:
            return ""
        from voice_pipeline.ears import peak_rms

        if peak_rms(pcm) < 150:  # silence: Whisper would invent words
            return ""
        return self._get_ears().transcribe(pcm)

    def render(self, text: str) -> tuple[np.ndarray, int]:
        return self._get_mouth().render(spoken_part(text))
