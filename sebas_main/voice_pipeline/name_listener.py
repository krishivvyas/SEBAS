"""Wake on the name: react only to sentences that begin with "Sebas".

Every stretch of speech is transcribed locally by a small, fast Whisper model;
anything not addressed to Sebas is discarded. This makes both forms work:

    "Sebas, rise."              -> Sebas answers and waits for a request
    "Sebas, open YouTube."      -> the request is handled straight away
"""

from __future__ import annotations

import collections
import logging
import re
import threading
from difflib import SequenceMatcher

import numpy as np
import sounddevice as sd

from sebas_events import emit
from voice_pipeline.ears import Ears

logger = logging.getLogger(__name__)

NAME = "sebas"
# Spellings Whisper produces for "Sebas" that plain similarity would miss.
_ALIASES = {"sebas", "sebass", "sebaz", "seebas", "sebbas", "sabas", "sebus", "cebas", "sevas"}
_FILLERS = {"hey", "hi", "hello", "ok", "okay", "oh", "so", "um", "uh", "yo", "now"}
SUMMON_WORDS = {"", "rise", "arise", "wake up", "awaken", "are you there"}

_RATE = 16000
_FRAME = 1280  # 80 ms
_PRE_ROLL_FRAMES = 4  # keep 320 ms before speech starts, so the "S" is not clipped
_END_SILENCE_FRAMES = 9  # 720 ms of quiet ends an utterance
_MIN_SPEECH_FRAMES = 4
_MAX_FRAMES = int(15 * _RATE / _FRAME)
_NAME_CHECK_SECONDS = 3


def _norm(word: str) -> str:
    return re.sub(r"[^a-z]", "", word.lower())


def _is_name(candidate: str) -> bool:
    return candidate in _ALIASES or SequenceMatcher(None, candidate, NAME).ratio() >= 0.8


def split_address(text: str) -> str | None:
    """If ``text`` is addressed to Sebas, return what follows the name, else None."""
    words = text.split()
    i = 0
    while i < len(words) and i < 2 and _norm(words[i]) in _FILLERS:
        i += 1
    if i >= len(words):
        return None
    one = _norm(words[i])
    two = one + _norm(words[i + 1]) if i + 1 < len(words) else ""
    if one and _is_name(one):
        rest = words[i + 1 :]
    elif two and _is_name(two):  # "Seb us, ..."
        rest = words[i + 2 :]
    else:
        return None
    return " ".join(rest).lstrip(",.;:!?- ").strip()


def is_summon(remainder: str) -> bool:
    """True when the user only called Sebas ("Sebas", "Sebas, rise")."""
    words = re.sub(r"[^a-z ]", "", remainder.lower()).split()
    if " ".join(words) in SUMMON_WORDS:
        return True
    # A single word that sounds like "rise" ("Riza", "rights") is a summon too.
    # Misreading a one-word request this way costs only a "What do you need?".
    return len(words) == 1 and any(
        SequenceMatcher(None, words[0], w).ratio() >= 0.5 for w in ("rise", "arise")
    )


SLEEP_PHRASES = {
    "sleep", "go to sleep", "goodnight", "good night", "rest", "go rest", "retire",
    "shut down", "shutdown", "turn off", "power down", "that will be all", "thats all",
    "dismissed", "you may go", "you may retire", "sleep now", "go to bed",
}


def is_sleep_request(text: str) -> bool:
    """True for "sleep" / "good night" / "that will be all" said on its own.

    Only the whole request counts, so "turn off the wifi" is not mistaken for
    sending Sebas to sleep. A leading "Sebas," and politeness are ignored.
    """
    words = re.sub(r"[^a-z ]", "", text.lower()).split()
    if words and _is_name(words[0]):
        words = words[1:]
    words = [w for w in words if w not in {"please", "now", "sebas", "ok", "okay", "you", "can"}] or words
    return " ".join(words) in SLEEP_PHRASES


def request_text(remainder: str) -> str:
    """Drop a leading "rise" from a request: "rise and check GitHub" -> "check GitHub"."""
    return re.sub(r"^a?rise\b[,.!]?\s*(and\s+)?", "", remainder, flags=re.IGNORECASE).strip()


class PushToTalk(Exception):
    """Raised inside the listener when the UI's bell button is pressed."""


class NameListener:
    """Waits until someone says a sentence starting with "Sebas"."""

    def __init__(self, ears: Ears, silence_threshold: int) -> None:
        self._ears = ears
        self._threshold = silence_threshold
        self._push_to_talk = threading.Event()

    def push_to_talk(self) -> None:
        """Stop waiting for the name; the next utterance is a request."""
        self._push_to_talk.set()

    def next_utterance(self, stream) -> np.ndarray:
        """Read frames until one stretch of speech has been captured."""
        pre_roll: collections.deque = collections.deque(maxlen=_PRE_ROLL_FRAMES)
        frames: list[np.ndarray] = []
        loud = quiet = 0
        while True:
            if self._push_to_talk.is_set():
                self._push_to_talk.clear()
                raise PushToTalk
            frame, _ = stream.read(_FRAME)
            frame = frame[:, 0].copy()
            rms = float(np.sqrt(np.mean(frame.astype(np.float64) ** 2)))
            emit("mic", level=min(1.0, rms / (self._threshold * 8)))
            is_loud = rms >= self._threshold
            if not frames:
                pre_roll.append(frame)
                if is_loud:
                    frames, loud, quiet = list(pre_roll), 1, 0
                continue
            frames.append(frame)
            if is_loud:
                loud, quiet = loud + 1, 0
            else:
                quiet += 1
            if quiet >= _END_SILENCE_FRAMES or len(frames) >= _MAX_FRAMES:
                if loud >= _MIN_SPEECH_FRAMES:
                    return np.concatenate(frames)
                pre_roll.clear()
                frames, loud, quiet = [], 0, 0  # a click or cough; keep waiting

    def wait(self) -> tuple[np.ndarray | None, str]:
        """Return the audio and the words after "Sebas" for the next address.

        Returns ``(None, "")`` when push-to-talk interrupts the wait.
        """
        with sd.InputStream(samplerate=_RATE, channels=1, dtype="int16", blocksize=_FRAME) as stream:
            while True:
                try:
                    pcm = self.next_utterance(stream)
                except PushToTalk:
                    return None, ""
                # "Sebas" always comes first, so only the opening seconds need
                # checking: long background speech (TV, a call) costs far less.
                text = self._ears.transcribe(pcm[: _RATE * _NAME_CHECK_SECONDS])
                remainder = split_address(text)
                if remainder is not None:
                    return pcm, remainder
                logger.debug("Not addressed to Sebas: %r", text)
