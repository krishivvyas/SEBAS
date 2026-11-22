"""A native Gujarati voice: Meta's MMS-TTS Gujarati model (VITS), run through
ONNX Runtime like Kokoro, so no PyTorch.

Kokoro has no Gujarati voice; its Hindi voice reading Gujarati sounds like a
Hindi speaker. This one was trained on Gujarati speech. The model (~114 MB,
16 kHz) is the sherpa-onnx conversion of facebook/mms-tts-guj, downloaded to
~/.cache/sebas/mms-guj on first use.

Licence: the MMS-TTS models are CC BY-NC 4.0 (non-commercial use only). Fine
for a personal assistant; ``SEBAS_GUJARATI_VOICE=kokoro`` uses Kokoro's Hindi
voice instead.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import unicodedata
from pathlib import Path

import numpy as np

logger = logging.getLogger("sebas.voice")

_DIR = Path(os.environ.get("SEBAS_GUJARATI_TTS_DIR") or Path.home() / ".cache" / "sebas" / "mms-guj")
_URL = "https://huggingface.co/willwade/mms-tts-multilingual-models-onnx/resolve/main/guj/"
_FILES = ("model.onnx", "tokens.txt")
RATE = 16000
_THREADS = 4

_lock = threading.Lock()
_session = None
_tokens: dict[str, int] = {}


def _release() -> None:
    """Let the model go after a spell without Gujarati (SEBAS_LANGUAGE_IDLE_MINUTES)."""
    global _session
    with _lock:
        _session = None


_idle = None


def loaded() -> bool:
    return _session is not None


def wanted() -> bool:
    """False when the user prefers Kokoro's Hindi voice for Gujarati."""
    return os.environ.get("SEBAS_GUJARATI_VOICE", "").split("#")[0].strip().lower() not in ("kokoro", "hindi", "off")


def _ensure_files() -> None:
    import httpx

    _DIR.mkdir(parents=True, exist_ok=True)
    for name in _FILES:
        target = _DIR / name
        if target.exists() and target.stat().st_size > 100:
            continue
        logger.warning("Downloading the Gujarati voice %s (first use only)...", name)
        partial = target.with_suffix(target.suffix + ".part")
        with httpx.stream("GET", _URL + name, follow_redirects=True, timeout=120) as response:
            response.raise_for_status()
            with open(partial, "wb") as fh:
                for chunk in response.iter_bytes(1 << 20):
                    fh.write(chunk)
        partial.replace(target)


def _load() -> None:
    global _session, _tokens
    if _session is not None:
        return
    import onnxruntime as ort

    _ensure_files()
    table: dict[str, int] = {}
    for line in (_DIR / "tokens.txt").read_text(encoding="utf-8").split("\n"):
        if not line:
            continue
        symbol, _, number = line.rpartition(" ")
        table[symbol if symbol else " "] = int(number)
    options = ort.SessionOptions()
    options.enable_cpu_mem_arena = False
    options.intra_op_num_threads = _THREADS
    _session = ort.InferenceSession(str(_DIR / "model.onnx"), options, providers=["CPUExecutionProvider"])
    _tokens = table


def to_ids(text: str, table: dict[str, int]) -> list[int]:
    """Characters to model ids, with the blank (0) between and around them, as
    the model was trained ("add_blank"). Characters it never saw are dropped;
    runs of spaces and punctuation become one space."""
    text = unicodedata.normalize("NFC", text)
    text = re.sub(r"[૦-૯0-9]+", lambda m: _digits(m.group()), text)
    text = re.sub(r"[^઀-૿'\- ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    ids = [table[c] for c in text if c in table]
    blank = table.get("|", 0)
    out = [blank]
    for i in ids:
        out += [i, blank]
    return out


_ONES = ["શૂન્ય", "એક", "બે", "ત્રણ", "ચાર", "પાંચ", "છ", "સાત", "આઠ", "નવ"]


def _digits(number: str) -> str:
    """Numbers read digit by digit in Gujarati ("120" -> "એક બે શૂન્ય"): plain, never wrong."""
    digits = [int(unicodedata.digit(c, 0)) for c in number]
    return " " + " ".join(_ONES[d] for d in digits) + " "


def synthesize(text: str, speed: float = 1.0) -> tuple[np.ndarray, int]:
    """Gujarati ``text`` as float32 audio at 16 kHz."""
    global _idle
    with _lock:
        _load()
        ids = to_ids(text, _tokens)
        if len(ids) < 3:
            return np.zeros(0, dtype=np.float32), RATE
        audio = _session.run(None, {
            "x": np.array([ids], dtype=np.int64),
            "x_length": np.array([len(ids)], dtype=np.int64),
            "noise_scale": np.array([0.667], dtype=np.float32),
            "length_scale": np.array([1.0 / max(0.5, speed)], dtype=np.float32),
            "noise_scale_w": np.array([0.8], dtype=np.float32),
        })[0]
    if _idle is None:
        from voice_pipeline.ears import IdleRelease

        _idle = IdleRelease(_release, "the Gujarati voice")
    _idle.touch()
    return audio.reshape(-1).astype(np.float32), RATE
