"""Call audio: hearing the other side of a call, and speaking into it.

Hearing: the caller's voice is whatever the laptop plays, so it is captured from
the default output device with WASAPI loopback (the soundcard library). Nothing
in the room is picked up, and nothing is recorded to disk: utterances go straight
to Whisper and are dropped.

Speaking, two routes, chosen automatically:
  speaker  Sebas talks through the laptop's speakers and the call app's microphone
           picks him up. No install; best in a quiet room with the speakers up.
  clean    with VB-Cable (a free virtual audio cable) installed and "CABLE Output"
           chosen as the call app's microphone, Sebas sends your real microphone
           into the cable with his voice mixed in: the caller hears both of you,
           clearly. Only while Sebas is running, so pick the cable only then.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Callable

import numpy as np

logger = logging.getLogger("sebas.voice")

_LOOP_RATE = 48000
_BLOCK = 960                 # 20 ms: what is read and written at a time
_BUFFER = 9600               # 200 ms: the WASAPI buffer behind it (soundcard makes the buffer
                             # the size of `blocksize`; at 20 ms any pause in Python, e.g. while
                             # Whisper runs, ran the cable dry or overflowed the mic: choppy audio)
_WHISPER_RATE = 16000
_START_RMS = 0.012           # the caller has started speaking (digital audio: silence is ~0)
_QUIET_RMS = 0.006
_END_SILENCE = 0.8           # seconds of quiet that end an utterance
_MIN_SPEECH = 0.45
_MAX_SPEECH = 20.0
_CABLE_NAME = "CABLE Input"  # VB-Cable's playback side; the call app records "CABLE Output"


class Utterances:
    """Splits a stream of mono float blocks into utterances (pure, testable)."""

    def __init__(self, rate: int = _LOOP_RATE) -> None:
        self.rate = rate
        self._buf: list[np.ndarray] = []
        self._speaking = False
        self._quiet = 0.0
        self._length = 0.0

    def reset(self) -> None:
        self._buf, self._speaking, self._quiet, self._length = [], False, 0.0, 0.0

    def feed(self, block: np.ndarray) -> np.ndarray | None:
        """Add one block; return a finished utterance (float mono) or None."""
        seconds = block.size / self.rate
        rms = float(np.sqrt(np.mean(block ** 2))) if block.size else 0.0
        if not self._speaking:
            if rms < _START_RMS:
                self._buf = self._buf[-5:] + [block]  # 100 ms of lead-in
                return None
            self._speaking, self._quiet, self._length = True, 0.0, 0.0
        self._buf.append(block)
        self._length += seconds
        self._quiet = self._quiet + seconds if rms < _QUIET_RMS else 0.0
        if self._quiet >= _END_SILENCE or self._length >= _MAX_SPEECH:
            audio = np.concatenate(self._buf)
            spoken = self._length - self._quiet
            self.reset()
            return audio if spoken >= _MIN_SPEECH else None
        return None


def to_whisper(audio: np.ndarray, rate: int = _LOOP_RATE) -> np.ndarray:
    """Float mono at ``rate`` -> int16 at 16 kHz, louder if the call was quiet."""
    from math import gcd

    from scipy.signal import resample_poly

    g = gcd(_WHISPER_RATE, rate)
    pcm = resample_poly(audio, _WHISPER_RATE // g, rate // g)
    peak = float(np.abs(pcm).max()) if pcm.size else 0.0
    if 0 < peak < 0.5:
        pcm = pcm * (0.5 / peak)  # a quiet line is normalised for Whisper
    return (np.clip(pcm, -1, 1) * 32767).astype(np.int16)


class CallerEars:
    """Listens to the laptop's own sound output and hands each utterance on."""

    def __init__(self, on_utterance: Callable[[np.ndarray], None], muted: Callable[[], bool]) -> None:
        self._on_utterance = on_utterance
        self._muted = muted
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="sebas-call-ears", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        import ctypes
        import warnings

        import soundcard as sc

        # Windows sends no loopback data while nothing plays; soundcard warns each time
        warnings.filterwarnings("ignore", category=sc.SoundcardRuntimeWarning)
        ctypes.windll.ole32.CoInitializeEx(None, 0)  # WASAPI from a worker thread
        splitter = Utterances()
        try:
            speaker = sc.default_speaker()
            loop = sc.get_microphone(id=str(speaker.name), include_loopback=True)
            logger.info("Call: listening to %s", speaker.name)
            with loop.recorder(samplerate=_LOOP_RATE, channels=2, blocksize=_BUFFER) as recorder:
                while not self._stop.is_set():
                    block = recorder.record(numframes=_BLOCK).mean(axis=1).astype(np.float32)
                    if self._muted():  # Sebas's own voice from the speakers, not the caller's
                        splitter.reset()
                        continue
                    utterance = splitter.feed(block)
                    if utterance is not None:
                        self._on_utterance(to_whisper(utterance))
        except Exception:
            logger.exception("Call: could not listen to the laptop's sound output")


_NOT_A_MIC = ("cable", "stereo mix", "what u hear", "loopback")


def find_cable():
    """VB-Cable's playback side ("CABLE Input"), looked up live: installing the cable
    while Sebas runs is noticed at the next call. None if it is not installed."""
    import soundcard as sc

    try:
        return next((s for s in sc.all_speakers() if _CABLE_NAME.lower() in s.name.lower()), None)
    except Exception:
        return None


def real_microphone():
    """The user's own microphone: the default one, unless that is the cable itself
    (choosing CABLE Output as the *Windows* default would feed Sebas his own voice)."""
    import soundcard as sc

    default = sc.default_microphone()
    if not any(word in default.name.lower() for word in _NOT_A_MIC):
        return default
    return next((m for m in sc.all_microphones() if not any(w in m.name.lower() for w in _NOT_A_MIC)), None)


_MAX_LAG = 2880  # 60 ms queued for the cable: more than this and your voice reaches the caller late


def play_block(player, data: np.ndarray) -> None:
    """Write mono float ``data`` to a soundcard player, exactly.

    soundcard 0.4.6's ``play`` commits every free frame of the WASAPI buffer
    however little data it was given, so with a buffer larger than the block
    each write added stale audio after it. This commits only what was copied.
    """
    channels = len(set(player.channelmap))
    frames = np.ascontiguousarray(np.tile(np.asarray(data, dtype=np.float32)[:, None], (1, channels)))
    from soundcard.mediafoundation import _ffi

    while frames.shape[0]:
        free = player._render_available_frames()
        if free == 0:
            time.sleep(0.002)
            continue
        part, frames = frames[:free], frames[free:]
        raw = part.tobytes()
        buffer = player._render_buffer(part.shape[0])
        _ffi.memmove(buffer[0], raw, len(raw))
        player._render_release(part.shape[0])


def lagging(player) -> bool:
    """True when more than ``_MAX_LAG`` frames wait in the player's buffer (after a pause
    the microphone's backlog is written all at once, and would otherwise stay as delay)."""
    try:
        return int(player.currentpadding) > _MAX_LAG
    except Exception:
        return False


class CableRoute:
    """Clean mode: the real microphone into VB-Cable, with Sebas's voice mixed in.

    The call app records "CABLE Output", so the caller hears you (passed through,
    about 40 ms behind) and Sebas, and never the laptop's speakers. One thread
    reads the microphone and writes the cable in 20 ms blocks.
    """

    def __init__(self, cable) -> None:
        self.cable = cable
        self.name = cable.name
        self._voice: queue.Queue[np.ndarray] = queue.Queue()
        self._current = np.zeros(0, dtype=np.float32)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.playing = threading.Event()
        self.ready = threading.Event()  # set once audio is flowing into the cable (opening takes 3-5 s cold)
        self.error: str = ""

    def start(self) -> None:
        self._stop.clear()
        self.ready.clear()
        self._thread = threading.Thread(target=self._run, name="sebas-call-cable", daemon=True)
        self._thread.start()

    def alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _next_voice(self, frames: int) -> np.ndarray:
        while self._current.size < frames and not self._voice.empty():
            self._current = np.concatenate([self._current, self._voice.get_nowait()])
        voice, self._current = self._current[:frames], self._current[frames:]
        if voice.size == 0:
            self.playing.clear()
        return voice

    def _run(self) -> None:
        import ctypes
        import warnings

        import soundcard as sc

        warnings.filterwarnings("ignore", category=sc.SoundcardRuntimeWarning)
        ctypes.windll.ole32.CoInitializeEx(None, 0)
        from scipy.signal import resample_poly  # noqa: F401  2.5 s cold: load it now, not on the greeting

        mic = real_microphone()
        try:
            with self.cable.player(samplerate=_LOOP_RATE, channels=1, blocksize=_BUFFER) as player:
                if mic is None:  # no microphone: Sebas's voice alone
                    logger.warning("Call: no microphone to pass through; only Sebas will be heard")
                    self.ready.set()
                    while not self._stop.is_set():
                        block = np.zeros(_BLOCK, dtype=np.float32)
                        voice = self._next_voice(_BLOCK)
                        block[: voice.size] += voice
                        play_block(player, block)
                    return
                with mic.recorder(samplerate=_LOOP_RATE, channels=1, blocksize=_BUFFER) as recorder:
                    logger.info("Call: clean mode, %s and Sebas into %s", mic.name, self.name)
                    self.ready.set()
                    while not self._stop.is_set():
                        block = recorder.record(numframes=_BLOCK)[:, 0].astype(np.float32)
                        if lagging(player) and not self.playing.is_set():
                            continue  # catch up after a pause: drop 20 ms of room sound, not Sebas
                        voice = self._next_voice(block.size)
                        block[: voice.size] += voice
                        play_block(player, np.clip(block, -1, 1))
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"
            logger.exception("Call: the VB-Cable route stopped")

    def say(self, audio: np.ndarray, rate: int) -> None:
        """Queue Sebas's voice and wait until it has gone into the call."""
        from math import gcd

        from scipy.signal import resample_poly

        g = gcd(_LOOP_RATE, rate)
        voice = resample_poly(np.asarray(audio, dtype=np.float32), _LOOP_RATE // g, rate // g).astype(np.float32)
        self._voice.put(voice)
        self.playing.set()
        time.sleep(voice.size / _LOOP_RATE)
        deadline = time.monotonic() + 2
        while self.playing.is_set() and time.monotonic() < deadline:
            time.sleep(0.05)

    def stop(self) -> None:
        self._stop.set()


def check_cable(route: CableRoute) -> tuple[bool, str]:
    """Play a short tone through the route and listen for it on "CABLE Output",
    exactly where the call app will. Returns (ok, explanation)."""
    import ctypes
    import warnings

    import soundcard as sc

    warnings.filterwarnings("ignore", category=sc.SoundcardRuntimeWarning)
    ctypes.windll.ole32.CoInitializeEx(None, 0)
    out = next((m for m in sc.all_microphones() if "cable output" in m.name.lower()), None)
    if out is None:
        return False, "VB-Cable's 'CABLE Output' microphone was not found."
    route.ready.wait(timeout=10)  # a route started a moment ago is still opening the microphone
    if not route.alive() or not route.ready.is_set():
        return False, f"The cable route is not running ({route.error or 'stopped'})."
    t = np.arange(int(0.6 * _LOOP_RATE)) / _LOOP_RATE
    tone = (0.3 * np.sin(2 * np.pi * 660 * t)).astype(np.float32)
    heard: list[np.ndarray] = []
    with out.recorder(samplerate=_LOOP_RATE, channels=1, blocksize=_BUFFER) as recorder:
        recorder.record(numframes=_BLOCK * 5)  # settle
        sender = threading.Thread(target=route.say, args=(tone, _LOOP_RATE), daemon=True)
        sender.start()
        for _ in range(int(1.2 * _LOOP_RATE / _BLOCK)):
            heard.append(recorder.record(numframes=_BLOCK)[:, 0])
        sender.join(timeout=3)
    audio = np.concatenate(heard)
    peak = float(np.sqrt(np.mean(audio ** 2)))
    ok = peak > 0.02
    return ok, (f"The test tone reached CABLE Output (level {peak:.2f}): callers will hear me."
                if ok else f"The test tone did not reach CABLE Output (level {peak:.3f}).")
