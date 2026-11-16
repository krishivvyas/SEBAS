"""Search my stuff: "what did I note about normalisation?"

Looks through what the user has written and kept, on the laptop, and returns
the best-matching passages with where each came from. The model holding the
conversation then answers from them, so the search itself costs no Gemini
request, and nothing is sent anywhere except those few passages.

Where it looks
    Documents (including Sebas Notes, the lecture notes): .md .txt .pdf .docx,
    skipping code projects (git repositories and [projects]) and big files;
    the journal; flashcards and quiz questions; the coding reports; and the
    remembered facts in MEMORY.md.

Text pulled out of PDFs and Word files is cached by file and modification time
in ~/.openjarvis/sebas/search_cache/, so only new or changed files are read.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from openjarvis.core.paths import get_data_dir
from openjarvis.core.registry import ToolRegistry

from custom_tools._base import SebasTool, ToolError

logger = logging.getLogger("sebas.search")

EXTENSIONS = {".md", ".txt", ".pdf", ".docx"}
MAX_FILE_BYTES = 25 * 2**20
MAX_PDF_PAGES = 120
MAX_TEXT = 300_000
READ_BUDGET_SECONDS = 15.0   # reading new PDFs/Word files per search; the rest wait for the next one
CHUNK = 700
RESULTS = 6
_SKIP_DIRS = {"node_modules", ".git", ".venv", "venv", "__pycache__", "$recycle.bin", "appdata", "my music",
              "my pictures", "my videos"}
_STOP = set("""a an the and or but if of to in on at by for with from as is are was were be been being it its this that
these those i me my mine you your we our they their he she his her what which who whom when where why how did do does
done about note notes noted wrote write written say said any some all have has had there here into over than then
tell find search look show give me please sebas sir can could would should will""".split())


# --------------------------------------------------------------------------- reading files

def _cache_dir() -> Path:
    return get_data_dir() / "sebas" / "search_cache"


def _cached(path: Path, reader) -> str:
    """Text of a PDF or Word file, from the cache when the file is unchanged."""
    try:
        stat = path.stat()
    except OSError:
        return ""
    key = hashlib.sha1(str(path).lower().encode()).hexdigest()[:20]
    cache = _cache_dir() / f"{key}.json"
    try:
        data = json.loads(cache.read_text("utf-8"))
        if data.get("mtime") == stat.st_mtime and data.get("size") == stat.st_size:
            return data.get("text", "")
    except (OSError, json.JSONDecodeError):
        pass
    try:
        text = reader(path)[:MAX_TEXT]
    except Exception as exc:  # a damaged or protected file: skip it, remember that
        logger.info("Could not read %s: %s", path.name, exc)
        text = ""
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"path": str(path), "mtime": stat.st_mtime, "size": stat.st_size, "text": text}), "utf-8")
    except OSError:
        pass
    return text


def is_cached(path: Path) -> bool:
    try:
        stat = path.stat()
        key = hashlib.sha1(str(path).lower().encode()).hexdigest()[:20]
        data = json.loads((_cache_dir() / f"{key}.json").read_text("utf-8"))
        return data.get("mtime") == stat.st_mtime and data.get("size") == stat.st_size
    except (OSError, json.JSONDecodeError):
        return False


def read_pdf(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages = []
    for n, page in enumerate(reader.pages[:MAX_PDF_PAGES], 1):
        pages.append(f"\f[page {n}]\n{page.extract_text() or ''}")
    return "".join(pages)


def read_docx(path: Path) -> str:
    with zipfile.ZipFile(path) as zf:
        xml = zf.read("word/document.xml").decode("utf-8", "replace")
    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"<w:tab/>", " ", xml)
    text = re.sub(r"<[^>]+>", "", xml)
    import html

    return html.unescape(text)


def read_plain(path: Path) -> str:
    return path.read_text("utf-8", errors="replace")[:MAX_TEXT]


# --------------------------------------------------------------------------- the sources

def _documents_root() -> Path | None:
    try:
        from custom_tools.assist import known_folder

        folder = Path(known_folder("documents"))
        return folder if folder.is_dir() else None
    except Exception:
        return None


def _project_folders() -> set[Path]:
    try:
        from custom_tools.laptop import _section

        return {Path(str(p)).expanduser().resolve() for p in _section("projects").values()}
    except Exception:
        return set()


def document_files(root: Path) -> list[Path]:
    projects = _project_folders()
    found = []
    for here, folders, names in os.walk(root):
        base = Path(here)
        folders[:] = [f for f in folders if f.lower() not in _SKIP_DIRS and not f.startswith(".")
                      and not (base / f / ".git").exists() and (base / f).resolve() not in projects]
        for name in names:
            path = base / name
            if path.suffix.lower() in EXTENSIONS and not name.startswith("~$"):
                try:
                    if path.stat().st_size <= MAX_FILE_BYTES:
                        found.append(path)
                except OSError:
                    continue
    return found


def _label(path: Path, root: Path) -> str:
    try:
        inner = path.relative_to(root)
    except ValueError:
        return path.name
    if inner.parts and inner.parts[0] == "Sebas Notes":
        return f"Lecture notes: {path.stem}"
    return "Documents/" + "/".join(inner.parts)


def passages(where: str = "all") -> Iterator[tuple[str, str, float]]:
    """(source label, text, modified time) for everything searchable."""
    from custom_tools import household

    if where in ("all", "journal"):
        try:
            for e in household.load("journal"):
                yield f"Journal, {e.get('date', '')}", e.get("entry", ""), _stamp(e.get("date"))
        except ToolError:
            pass
    if where in ("all", "flashcards"):
        from custom_tools import study

        folder = study._study_dir()
        for deck_file in sorted(folder.glob("*.json")) if folder.is_dir() else []:
            try:
                deck = json.loads(deck_file.read_text("utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            subject = deck.get("subject", deck_file.stem)
            for card in deck.get("cards", []):
                yield f"Flashcards: {subject}", f"Q: {card.get('q', '')}\nA: {card.get('a', '')}", deck_file.stat().st_mtime
            for q in deck.get("quiz", []):
                yield f"Quiz: {subject}", f"{q.get('q', '')} Answer: {q.get('right', '')}", deck_file.stat().st_mtime
    if where in ("all", "notes"):
        coding = get_data_dir() / "sebas" / "coding"
        for report in sorted(coding.glob("*.md")) if coding.is_dir() else []:
            yield f"Coding report: {report.stem}", read_plain(report), report.stat().st_mtime
        try:
            from custom_tools.memory import read_facts

            facts = read_facts()
            if facts:
                yield "Remembered facts", "\n".join(facts), time.time()
        except Exception:
            pass
    if where in ("all", "notes", "documents"):
        root = _documents_root()
        if root is None:
            return
        deadline = time.monotonic() + READ_BUDGET_SECONDS
        skipped = 0
        for path in document_files(root):
            label = _label(path, root)
            if where == "notes" and not label.startswith("Lecture notes"):
                continue
            ext = path.suffix.lower()
            if ext in (".pdf", ".docx"):
                if time.monotonic() > deadline and not is_cached(path):
                    skipped += 1
                    continue
                text = _cached(path, read_pdf if ext == ".pdf" else read_docx)
            else:
                try:
                    text = read_plain(path)
                except OSError:
                    continue
            try:
                mtime = path.stat().st_mtime
            except OSError:
                mtime = 0.0
            yield label, text, mtime
        if skipped:
            _SKIPPED[0] = skipped


_SKIPPED = [0]


def _stamp(day: Any) -> float:
    try:
        return datetime.fromisoformat(str(day)[:10]).timestamp()
    except ValueError:
        return 0.0


# --------------------------------------------------------------------------- ranking

def terms(query: str) -> list[str]:
    words = [w for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w) >= 2 and w not in _STOP]
    return list(dict.fromkeys(words))


def _stem(word: str) -> str:
    for ending in ("isation", "ization", "ations", "ation", "ings", "ing", "ies", "ed", "es", "s"):
        if len(word) - len(ending) >= 4 and word.endswith(ending):
            return word[: -len(ending)]
    return word


def chunks(text: str) -> Iterator[tuple[str, str]]:
    """(page marker or '', piece of about CHUNK characters) along paragraph breaks."""
    page = ""
    buffer = ""
    for para in re.split(r"\n\s*\n|\f", text):
        marker = re.match(r"\s*\[page (\d+)\]", para)
        if marker:
            if buffer.strip():
                yield page, buffer
                buffer = ""
            page = f"p. {marker.group(1)}"
            para = para[marker.end():]
        para = " ".join(para.split())
        if not para:
            continue
        if len(buffer) + len(para) > CHUNK and buffer:
            yield page, buffer
            buffer = ""
        while len(para) > CHUNK * 1.5:
            cut = para.rfind(". ", 0, CHUNK) + 1 or CHUNK
            yield page, para[:cut]
            para = para[cut:].strip()
        buffer = f"{buffer} {para}".strip()
    if buffer.strip():
        yield page, buffer


def score(text: str, wanted: list[str], phrase: str) -> float:
    low = text.lower()
    distinct, total = 0, 0
    for word in wanted:
        hits = len(re.findall(r"\b" + re.escape(_stem(word)), low))
        if hits:
            distinct += 1
            total += min(hits, 4)
    if not distinct:
        return 0.0
    value = total * (1 + distinct) / (1 + len(wanted))
    if phrase and len(phrase) > 6 and phrase in low:
        value += 4
    return value


def search(query: str, where: str = "all", limit: int = RESULTS) -> list[dict[str, Any]]:
    wanted = terms(query)
    if not wanted:
        raise ToolError("Say what to look for, in a few words.")
    phrase = " ".join(wanted)
    found = []
    for label, text, mtime in passages(where):
        for page, piece in chunks(text or ""):
            value = score(piece, wanted, phrase)
            if value > 0:
                found.append({"source": label + (f", {page}" if page else ""), "text": piece, "score": value, "mtime": mtime})
    # need at least half the words (or one, for a one-word search) in the passage
    need = 1 if len(wanted) <= 2 else max(1, len(wanted) // 2)
    found = [f for f in found if sum(1 for w in wanted if _stem(w) in f["text"].lower()) >= need]
    found.sort(key=lambda f: (-f["score"], -f["mtime"]))
    picked, per_source = [], {}
    for f in found:  # no more than two passages from one file, so other sources get a say
        base = f["source"].split(", p.")[0]
        if per_source.get(base, 0) >= 2:
            continue
        per_source[base] = per_source.get(base, 0) + 1
        picked.append(f)
        if len(picked) >= limit:
            break
    return picked


@ToolRegistry.register("search_my_stuff")
class SearchMyStuffTool(SebasTool):
    name = "search_my_stuff"
    timeout_seconds = 60.0
    description = (
        "Search what the user has written and kept on the laptop: lecture notes, files in Documents (.md .txt "
        ".pdf .docx), the journal, flashcards and quizzes, coding reports and remembered facts. For 'what did I "
        "note about X?', 'find my notes on X', 'when did I write about X?'. Returns matching passages with their "
        "source; answer from them briefly and say which source it came from. If nothing fits, say so; never "
        "make it up."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The topic, in the user's words."},
            "where": {"type": "string", "enum": ["all", "notes", "documents", "journal", "flashcards"],
                      "description": "Default all. notes = lecture notes and Sebas's own records."},
        },
        "required": ["query"],
    }

    def run(self, query: str, where: str = "all") -> str:
        _SKIPPED[0] = 0
        results = search(query, where or "all")
        note = (f"\n(I had no time to read {_SKIPPED[0]} new PDF or Word files this time; asking again will "
                "include them.)") if _SKIPPED[0] else ""
        if not results:
            return f"Nothing in the user's notes, documents, journal or flashcards matches '{query}'.{note}"
        out = [f"{len(results)} passages for '{query}', best first:"]
        for n, r in enumerate(results, 1):
            out.append(f"{n}. [{r['source']}] {r['text'][:CHUNK]}")
        return "\n".join(out) + note
