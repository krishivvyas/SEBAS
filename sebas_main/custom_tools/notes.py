"""Reading aloud, and notes from lectures and meetings.

- read_aloud: a web page, a PDF, the clipboard or given text, read in Sebas's
  voice paragraph by paragraph on a background thread; stop_reading ends it.
- start_recording / stop_recording: record the microphone to a WAV file; on
  stop, transcribe it on the laptop with faster-whisper, summarise it with
  Gemini (outside the conversation, so the transcript does not bloat Sebas's
  memory of the chat), and save "Sebas Notes/<date> <title>.md" in Documents.
  Sebas announces when the notes are ready.

The voice and the announcements come from whatever run_sebas registered
(set_reader); without a voice (text mode, Discord) reading aloud is unavailable.
"""

from __future__ import annotations

import html as html_lib
import logging
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

import httpx
from openjarvis.core.paths import get_data_dir
from openjarvis.core.registry import ToolRegistry

from custom_tools._base import BROWSER_USER_AGENT, SebasTool, ToolError

logger = logging.getLogger(__name__)

_MAX_READ_WORDS = 6000
_WORDS_PER_MINUTE = 160
_MAX_RECORD_SECONDS = 3 * 3600

# --------------------------------------------------------------------------- reading aloud

_speak: Callable[[str], None] | None = None
_stop_reading = threading.Event()
_reading_lock = threading.Lock()


def set_reader(speak: Callable[[str], None] | None) -> None:
    """Called by run_sebas / the interface with the voice's speak function."""
    global _speak
    _speak = speak


def text_from_web(url: str) -> tuple[str, str]:
    """(title, readable text) of a web page."""
    from lxml import html

    try:
        response = httpx.get(url, headers={"User-Agent": BROWSER_USER_AGENT}, timeout=30, follow_redirects=True)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ToolError(f"Could not open {url}: {exc}") from exc
    tree = html.fromstring(response.content)
    for junk in tree.xpath("//script|//style|//nav|//footer|//header|//aside|//form|//noscript"):
        junk.drop_tree()
    title = (tree.findtext(".//title") or url).strip()
    root = (tree.xpath("//article") or tree.xpath("//main") or [tree])[0]
    blocks = [" ".join(e.text_content().split()) for e in root.xpath(".//h1|.//h2|.//h3|.//p|.//li")]
    return title, "\n\n".join(b for b in blocks if len(b) > 30 or b.endswith((".", ":", "?")))


def text_from_pdf(path: Path) -> tuple[str, str]:
    from pypdf import PdfReader

    if not path.is_file():
        raise ToolError(f"There is no file at {path}.")
    reader = PdfReader(str(path))
    pages = [page.extract_text() or "" for page in reader.pages]
    text = "\n\n".join(p.strip() for p in pages if p.strip())
    if not text:
        raise ToolError("That PDF has no readable text (it may be scanned images).")
    return path.stem, text


def _paragraphs(text: str) -> list[str]:
    text = html_lib.unescape(text)
    parts = [" ".join(p.split()) for p in re.split(r"\n\s*\n", text)]
    return [p for p in parts if p]


def _read(title: str, paragraphs: list[str]) -> None:
    with _reading_lock:
        _stop_reading.clear()
        for paragraph in paragraphs:
            if _stop_reading.is_set():
                return
            try:
                _speak(paragraph)
            except Exception:
                logger.exception("Reading aloud failed")
                return


@ToolRegistry.register("read_aloud")
class ReadAloudTool(SebasTool):
    name = "read_aloud"
    acts_on_laptop = True
    description = (
        "Read something aloud in Sebas's voice: a web page (url), a PDF file (path), the "
        "clipboard, or text you provide. It reads in the background; stop_reading ends it."
    )
    parameters = {
        "type": "object",
        "properties": {
            "source": {"type": "string", "enum": ["url", "pdf", "clipboard", "text"]},
            "value": {"type": "string", "description": "The URL, the PDF's full path, or the text (not needed for clipboard)."},
        },
        "required": ["source"],
    }
    timeout_seconds = 60.0

    def run(self, source: str, value: str = "") -> str:
        if _speak is None:
            raise ToolError("Reading aloud needs Sebas's voice, which is not running in this mode.")
        if source == "url":
            title, text = text_from_web(value.strip())
        elif source == "pdf":
            title, text = text_from_pdf(Path(value.strip().strip('"')).expanduser())
        elif source == "clipboard":
            from custom_tools.assist import read_clipboard

            title, text = "the clipboard", read_clipboard()
        elif source == "text":
            title, text = "your text", value
        else:
            raise ToolError("Source must be url, pdf, clipboard or text.")
        words = text.split()
        if not words:
            raise ToolError("There was nothing to read.")
        note = ""
        if len(words) > _MAX_READ_WORDS:
            text, note = " ".join(words[:_MAX_READ_WORDS]), f" (the first {_MAX_READ_WORDS:,} words of {len(words):,})"
        _stop_reading.set()  # interrupt anything already being read
        threading.Thread(target=_read, args=(title, _paragraphs(text)), daemon=True).start()
        minutes = max(1, round(min(len(words), _MAX_READ_WORDS) / _WORDS_PER_MINUTE))
        return f"Reading {title} aloud now{note}, about {minutes} minute{'s' if minutes != 1 else ''}. Say 'stop reading' to end it."


@ToolRegistry.register("stop_reading")
class StopReadingTool(SebasTool):
    name = "stop_reading"
    acts_on_laptop = True
    description = "Stop reading aloud (after the current paragraph)."

    def run(self) -> str:
        busy = _reading_lock.locked()
        _stop_reading.set()
        return "I shall stop after this paragraph." if busy else "I was not reading anything."


# --------------------------------------------------------------------------- lecture / meeting notes

_recording: dict | None = None
_recording_guard = threading.Lock()


def notes_folder() -> Path:
    from custom_tools.assist import known_folder

    folder = Path(known_folder("documents")) / "Sebas Notes"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _announce(text: str) -> None:
    from custom_tools import laptop

    laptop._announce(text)


def transcribe_file(wav: Path) -> str:
    from faster_whisper import WhisperModel

    model = WhisperModel("small.en", device="cpu", compute_type="int8")
    segments, _ = model.transcribe(str(wav), language="en", vad_filter=True, beam_size=1)
    return " ".join(s.text.strip() for s in segments).strip()


SUMMARY_PROMPT = """You are summarising a transcript of a {kind} titled "{title}" for a busy student/developer.
Write Markdown with these sections:
## Summary
(5-8 sentences)
## Key points
(bullet list)
## Action items
(bullet list of tasks with owners/dates if mentioned; "None mentioned" if none)
## Questions to follow up
(bullet list, or "None")

Transcript:
{transcript}"""


def _finish_notes(recording: dict) -> None:
    title, wav = recording["title"], recording["path"]
    try:
        transcript = transcribe_file(wav)
        if not transcript:
            _announce(f"Sir, the recording '{title}' contained no speech I could make out.")
            return
        summary = ""
        try:
            from custom_tools.assist import gemini_once

            summary = gemini_once(
                [SUMMARY_PROMPT.format(kind=recording["kind"], title=title, transcript=transcript)],
                need="Summarising the notes", timeout_ms=120_000)
        except Exception as exc:
            logger.warning("Summary failed: %s", exc)
            summary = "_A summary could not be made (Gemini unavailable); the full transcript follows._"
        stamp = recording["started"].strftime("%Y-%m-%d %H%M")
        safe = re.sub(r'[<>:"/\\|?*]', "", title).strip() or "Notes"
        path = notes_folder() / f"{stamp} {safe}.md"
        minutes = round(recording["seconds"] / 60)
        path.write_text(
            f"# {title}\n\n*{recording['kind'].capitalize()} recorded {recording['started'].strftime('%A %d %B %Y, %I:%M %p')}"
            f" · {minutes} minutes · notes by Sebas*\n\n{summary}\n\n## Full transcript\n\n{transcript}\n",
            "utf-8",
        )
        _announce(f"Sir, your notes on {title} are ready, in Documents, Sebas Notes.")
    except Exception:
        logger.exception("Making notes failed")
        _announce(f"I regret, sir, that the notes on {title} could not be made. The recording is kept at {wav}.")


@ToolRegistry.register("start_recording")
class StartRecordingTool(SebasTool):
    name = "start_recording"
    acts_on_laptop = True
    description = (
        "Start recording a lecture or meeting with the laptop's microphone, for notes. "
        "Recording continues until stop_recording (at most 3 hours)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "What it is, e.g. 'DBMS lecture 7'."},
            "kind": {"type": "string", "enum": ["lecture", "meeting"]},
        },
        "required": ["title"],
    }

    def run(self, title: str, kind: str = "lecture") -> str:
        global _recording
        import sounddevice as sd
        import soundfile as sf

        with _recording_guard:
            if _recording is not None:
                raise ToolError(f"Already recording '{_recording['title']}'. Stop that first.")
            folder = get_data_dir() / "sebas" / "recordings"
            folder.mkdir(parents=True, exist_ok=True)
            started = datetime.now()
            path = folder / f"{started:%Y%m%d-%H%M%S}.wav"
            wav = sf.SoundFile(str(path), mode="w", samplerate=16000, channels=1, subtype="PCM_16")
            state = {"title": title.strip() or "Untitled", "kind": kind, "path": path, "file": wav,
                     "started": started, "seconds": 0.0, "t0": time.monotonic()}

            def on_audio(indata, frames, _time, _status):
                wav.write(indata)
                state["seconds"] += frames / 16000
                if state["seconds"] > _MAX_RECORD_SECONDS:
                    raise sd.CallbackStop

            stream = sd.InputStream(samplerate=16000, channels=1, dtype="int16", callback=on_audio)
            stream.start()
            state["stream"] = stream
            _recording = state
        return f"Recording '{state['title']}'. Say 'stop recording' when it ends, and I shall prepare the notes."


@ToolRegistry.register("stop_recording")
class StopRecordingTool(SebasTool):
    name = "stop_recording"
    acts_on_laptop = True
    description = "Stop the lecture/meeting recording and start making the notes (transcript and summary)."

    def run(self) -> str:
        global _recording
        with _recording_guard:
            if _recording is None:
                raise ToolError("Nothing is being recorded.")
            state, _recording = _recording, None
        state["stream"].stop(); state["stream"].close(); state["file"].close()
        minutes = state["seconds"] / 60
        threading.Thread(target=_finish_notes, args=(state,), daemon=True).start()
        estimate = max(1, round(minutes * 0.3))
        length = f"{minutes:.0f} minutes" if minutes >= 1.5 else "under a minute" if minutes < 1 else "a minute"
        return (f"Stopped after {length}. I am transcribing it on the laptop, which takes about "
                f"{estimate} minute{'s' if estimate != 1 else ''}, and shall tell you when the notes are ready.")
