"""Study mode: Pomodoro focus blocks, flashcards and quizzes from your notes, exam countdowns.

- Pomodoro: "Sebas, start a pomodoro on DBMS". 25 minutes of focus and 5 of rest
  (adjustable), four rounds, with a ring timer on the interface and spoken cues.
  During focus Sebas is a quiet butler: non-urgent alerts and briefings wait for
  the break (see sebas_scheduler), but he still answers when called.
- Study sets: "make flashcards for DBMS" reads your lecture notes (Documents ›
  Sebas Notes, or a file you name) and asks Gemini ONCE for flashcards and quiz
  questions. They are saved, so reviewing and quizzing work offline, cost no
  quota, and use spaced repetition (Leitner boxes) to show cards when due.
- Exams: "my DBMS exam is on 20 November". Countdown on the interface, mentioned
  in the morning briefing, with warnings a week, three days and a day before.

Data lives in ~/.openjarvis/sebas/ (exams.json, focus.json, study/<subject>.json).
"""

from __future__ import annotations

import json
import logging
import random
import re
import threading
import time
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from openjarvis.core.paths import get_data_dir
from openjarvis.core.registry import ToolRegistry

from custom_tools._base import SebasTool, ToolError
from custom_tools.household import _best_match, load, parse_when, save
from sebas_events import emit

logger = logging.getLogger("sebas.study")
_lock = threading.RLock()


def _announce(text: str) -> None:
    from custom_tools import laptop

    laptop._announce(text)


# =========================================================================== Pomodoro
FOCUS_START = [
    "Focus begins, sir. {m} minutes on {s}. As Rock Lee would say, hard work beats talent.",
    "{m} minutes on {s}, sir. I shall keep the household quiet. Plus Ultra.",
    "The training arc begins: {m} minutes of {s}. I shall hold all non-urgent matters.",
]
BREAK_START = [
    "Time for a {m}-minute break, sir. Even Saitama rests between push-ups.",
    "Well done, sir. {m} minutes of rest; stretch, and perhaps some water.",
    "A {m}-minute break, sir. Kakashi would be reading his book about now.",
]
BACK_TO_WORK = [
    "Break's over, sir. Round {c} of {n} on {s}. Shinzou wo sasageyo.",
    "Back to {s}, sir. Round {c} of {n}. Believe it.",
    "Round {c} of {n}, sir. The second half of the season is always the best.",
]
ALL_DONE = [
    "All {n} rounds complete, sir: {t} minutes on {s} today. A performance worthy of the Survey Corps.",
    "That concludes the session, sir. {t} minutes of {s} today. Even Ainz-sama would be impressed.",
]
STOPPED = "Very good, sir. The session is stopped; {t} minutes of focus recorded today."


class _Pomodoro:
    """One session at a time, on its own timer thread."""

    def __init__(self) -> None:
        self.state: dict[str, Any] | None = None
        self._wake = threading.Event()

    def focusing(self) -> bool:
        s = self.state
        return bool(s and s["phase"] == "focus")

    def public(self) -> dict[str, Any] | None:
        s = self.state
        if not s:
            return None
        return {k: s[k] for k in ("subject", "phase", "ends", "started", "cycle", "cycles", "focus", "rest")}

    def start(self, subject: str, focus: int, rest: int, cycles: int) -> None:
        self.stop(record=True, quiet=True)
        self.state = {"subject": subject, "focus": focus, "rest": rest, "cycles": cycles,
                      "cycle": 1, "phase": "focus", "started": time.time(), "ends": time.time() + focus * 60}
        self._wake = threading.Event()
        threading.Thread(target=self._run, args=(self.state, self._wake), name="sebas-pomodoro", daemon=True).start()
        self._emit()

    def stop(self, record: bool = True, quiet: bool = False) -> int:
        s, self.state = self.state, None
        self._wake.set()
        if s and record and s["phase"] == "focus":
            add_focus(s["subject"], (time.time() - s["started"]) / 60)
        if s and not quiet:
            self._emit()
        return round(focus_today().get(s["subject"], 0)) if s else 0

    def _emit(self) -> None:
        emit("study", view="pomodoro", session=self.public())

    def _run(self, s: dict, wake: threading.Event) -> None:
        while self.state is s:
            # re-checked each second (only while a session runs), so a laptop that
            # slept through the end of a block catches up as soon as it wakes
            if wake.wait(timeout=min(1.0, max(0.0, s["ends"] - time.time()))):
                return  # stopped or replaced
            if self.state is not s:
                return
            if time.time() < s["ends"]:
                continue
            if s["phase"] == "focus":
                add_focus(s["subject"], s["focus"])
                if s["cycle"] >= s["cycles"]:
                    self.state = None
                    self._emit()
                    total = round(focus_today().get(s["subject"], 0))
                    _announce(random.choice(ALL_DONE).format(n=s["cycles"], t=total, s=s["subject"]))
                    _release_held()
                    return
                s.update(phase="break", started=time.time(), ends=time.time() + s["rest"] * 60)
                self._emit()
                _release_held()  # what waited during focus is told now, at the break
                _announce(random.choice(BREAK_START).format(m=s["rest"]))
            else:
                s.update(phase="focus", cycle=s["cycle"] + 1, started=time.time(), ends=time.time() + s["focus"] * 60)
                self._emit()
                _announce(random.choice(BACK_TO_WORK).format(c=s["cycle"], n=s["cycles"], s=s["subject"]))


POMODORO = _Pomodoro()

# Alerts held during focus, delivered at the break by whoever registered a releaser
# (the scheduler). Kept here so the timer thread can release them.
_held_releaser: list = []


def _release_held() -> None:
    for release in list(_held_releaser):
        try:
            release()
        except Exception:
            logger.exception("Releasing held alerts failed")


def focus_active() -> bool:
    """True during a Pomodoro focus block (Sebas holds non-urgent alerts)."""
    return POMODORO.focusing()


def _focus_log() -> dict[str, dict[str, float]]:
    try:
        data = load("focus")
    except ToolError:
        return {}
    return data if isinstance(data, dict) else {}


def add_focus(subject: str, minutes: float) -> None:
    if minutes < 0.5:
        return
    with _lock:
        log = _focus_log()
        day = log.setdefault(date.today().isoformat(), {})
        day[subject] = round(day.get(subject, 0) + minutes, 1)
        for old in sorted(log)[:-60]:  # keep two months
            del log[old]
        save("focus", log)  # household.save writes any JSON value


def focus_today() -> dict[str, float]:
    return _focus_log().get(date.today().isoformat(), {})


def focus_week() -> float:
    log, start = _focus_log(), date.today() - timedelta(days=6)
    return sum(sum(v.values()) for d, v in log.items() if d >= start.isoformat())


@ToolRegistry.register("start_pomodoro")
class StartPomodoroTool(SebasTool):
    name = "start_pomodoro"
    description = (
        "Start a Pomodoro study session: focus blocks with short breaks, a timer on the "
        "interface and spoken cues. While focusing, non-urgent alerts wait until the break."
    )
    parameters = {
        "type": "object",
        "properties": {
            "subject": {"type": "string", "description": "What the user is studying, e.g. 'DBMS'."},
            "focus_minutes": {"type": "integer", "description": "Minutes per focus block (default 25)."},
            "break_minutes": {"type": "integer", "description": "Minutes per break (default 5)."},
            "rounds": {"type": "integer", "description": "Number of focus blocks (default 4)."},
        },
        "required": ["subject"],
    }

    def run(self, subject: str, focus_minutes: int = 25, break_minutes: int = 5, rounds: int = 4) -> str:
        subject = " ".join((subject or "study").split())[:60]
        focus = max(1, min(int(focus_minutes or 25), 180))
        rest = max(1, min(int(break_minutes or 5), 60))
        rounds = max(1, min(int(rounds or 4), 12))
        POMODORO.start(subject, focus, rest, rounds)
        return random.choice(FOCUS_START).format(m=focus, s=subject) + f" ({rounds} rounds, {rest}-minute breaks.)"


@ToolRegistry.register("stop_pomodoro")
class StopPomodoroTool(SebasTool):
    name = "stop_pomodoro"
    description = "Stop the current Pomodoro study session."

    def run(self) -> str:
        if POMODORO.state is None:
            return "There is no study session running."
        total = POMODORO.stop()
        _release_held()
        return STOPPED.format(t=total)


@ToolRegistry.register("study_status")
class StudyStatusTool(SebasTool):
    name = "study_status"
    description = "The current Pomodoro session (if any), focus time today and this week, and upcoming exams."

    def run(self) -> str:
        lines = []
        s = POMODORO.public()
        if s:
            left = max(0, round((s["ends"] - time.time()) / 60))
            lines.append(f"Session: {s['subject']}, {s['phase']} with {left} min left (round {s['cycle']} of {s['cycles']}).")
        today = focus_today()
        lines.append("Focus today: " + (", ".join(f"{k} {round(v)} min" for k, v in today.items()) or "none yet") + ".")
        lines.append(f"Focus this week: {round(focus_week())} minutes.")
        lines.append(exams_summary())
        return "\n".join(lines)


# =========================================================================== Exams
def upcoming_exams() -> list[dict]:
    today = date.today().isoformat()
    return sorted((e for e in load("exams") if e["date"][:10] >= today), key=lambda e: e["date"])


def days_until(exam: dict) -> int:
    return (datetime.fromisoformat(exam["date"]).date() - date.today()).days


def describe_exam(exam: dict) -> str:
    d = days_until(exam)
    when = "today" if d == 0 else "tomorrow" if d == 1 else f"in {d} days"
    return f"{exam['subject']} exam {when} ({datetime.fromisoformat(exam['date']).strftime('%a %d %b')})"


def exams_summary() -> str:
    exams = upcoming_exams()
    return "Upcoming exams: " + "; ".join(describe_exam(e) for e in exams) + "." if exams else "No exams scheduled."


@ToolRegistry.register("add_exam")
class AddExamTool(SebasTool):
    name = "add_exam"
    description = (
        "Record an exam date so Sebas counts down to it, mentions it in briefings and warns "
        "a week, three days and a day before. Convert relative dates using the current date."
    )
    parameters = {
        "type": "object",
        "properties": {
            "subject": {"type": "string", "description": "The exam's subject, e.g. 'DBMS'."},
            "date": {"type": "string", "description": "YYYY-MM-DD, or YYYY-MM-DD HH:MM if a time was given."},
        },
        "required": ["subject", "date"],
    }

    def run(self, subject: str, date: str) -> str:  # noqa: A002
        when = parse_when(date)
        subject = " ".join(subject.split())
        with _lock:
            exams = [e for e in load("exams") if e["subject"].lower() != subject.lower()]
            exams.append({"id": uuid.uuid4().hex[:8], "subject": subject, "date": when.isoformat()})
            save("exams", exams)
        return f"Noted, sir: {describe_exam(exams[-1])}."


@ToolRegistry.register("list_exams")
class ListExamsTool(SebasTool):
    name = "list_exams"
    description = "List upcoming exams with how many days remain."

    def run(self) -> str:
        return exams_summary()


@ToolRegistry.register("remove_exam")
class RemoveExamTool(SebasTool):
    name = "remove_exam"
    description = "Remove an exam (finished, cancelled or entered by mistake)."
    parameters = {"type": "object", "properties": {"subject": {"type": "string"}}, "required": ["subject"]}

    def run(self, subject: str) -> str:
        with _lock:
            exams = load("exams")
            exam = _best_match(exams, subject, "subject")
            save("exams", [e for e in exams if e is not exam])
        return f"Removed the {exam['subject']} exam."


# =========================================================================== Study sets
# Leitner boxes: how many days until a card is shown again after each correct answer.
BOX_DAYS = [0, 1, 2, 4, 8, 16, 32]


def _study_dir() -> Path:
    folder = get_data_dir() / "sebas" / "study"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def slug(subject: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", subject.lower()).strip("-") or "general"


def deck_path(subject: str) -> Path:
    return _study_dir() / f"{slug(subject)}.json"


def load_deck(subject: str) -> dict:
    path = deck_path(subject)
    if not path.exists():
        # a near match: "dbms" for "DBMS notes", "database" for "Database Systems"
        names = {p.stem: p for p in _study_dir().glob("*.json")}
        close = [p for s, p in names.items() if slug(subject) in s or s in slug(subject)]
        if not close:
            have = ", ".join(json.loads(p.read_text("utf-8"))["subject"] for p in names.values()) or "none yet"
            raise ToolError(f"There is no study set for {subject} (study sets: {have}). Ask me to make one from your notes.")
        path = close[0]
    return json.loads(path.read_text("utf-8"))


def save_deck(deck: dict) -> None:
    path = deck_path(deck["subject"])
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(deck, indent=1, ensure_ascii=False), "utf-8")
    tmp.replace(path)


def list_decks() -> list[dict]:
    out = []
    for p in sorted(_study_dir().glob("*.json")):
        try:
            d = json.loads(p.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        out.append({"subject": d["subject"], "cards": len(d["cards"]), "due": len(due_cards(d)),
                    "quiz": len(d.get("quiz", [])), "best": d.get("best_quiz")})
    return out


def due_cards(deck: dict, now: datetime | None = None) -> list[dict]:
    now_s = (now or datetime.now()).isoformat(timespec="minutes")
    return [c for c in deck["cards"] if c.get("due", "") <= now_s]


def grade_card(deck: dict, card_id: str, grade: str, now: datetime | None = None) -> dict:
    """again: back to box 0, shown again in ten minutes; good: up one box; easy: up two."""
    now = now or datetime.now()
    card = next(c for c in deck["cards"] if c["id"] == card_id)
    box = card.get("box", 0)
    if grade == "again":
        card["box"], due = 0, now + timedelta(minutes=10)
    else:
        card["box"] = min(box + (2 if grade == "easy" else 1), len(BOX_DAYS) - 1)
        due = now + timedelta(days=BOX_DAYS[card["box"]])
        if BOX_DAYS[card["box"]] >= 1:  # whole days: due from the start of that day
            due = due.replace(hour=0, minute=0)
    card["due"] = due.isoformat(timespec="minutes")
    card["seen"] = card.get("seen", 0) + 1
    return card


def find_notes(subject: str) -> list[Path]:
    """Notes in Documents › Sebas Notes whose name or text mentions the subject."""
    from custom_tools.notes import notes_folder

    words = [w for w in re.findall(r"[a-z0-9]+", subject.lower()) if len(w) > 1]
    hits = []
    for path in sorted(notes_folder().glob("*.*"), key=lambda p: p.stat().st_mtime, reverse=True):
        if path.suffix.lower() not in (".md", ".txt", ".pdf"):
            continue
        name = path.stem.lower()
        if all(w in name for w in words):
            hits.append(path)
        elif path.suffix.lower() != ".pdf":
            head = path.read_text("utf-8", errors="ignore")[:4000].lower()
            if all(w in head for w in words):
                hits.append(path)
    return hits[:6]


def read_source(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        from custom_tools.notes import text_from_pdf

        return text_from_pdf(path)[1]
    return path.read_text("utf-8", errors="ignore")


STUDY_PROMPT = """You are making study material for a university student from their notes on "{subject}".
Return ONLY a JSON object, no commentary, of this shape:
{{"cards": [{{"q": "short question", "a": "short answer (one or two sentences)"}}],
 "quiz": [{{"q": "multiple-choice question", "right": "the correct option", "wrong": ["wrong 1", "wrong 2", "wrong 3"]}}]}}
Make {cards} flashcards and {quiz} quiz questions covering the most important, examinable ideas:
definitions, differences between concepts, steps of procedures, and formulas. Use only facts from the notes.
Keep each option under 12 words, and make the wrong options plausible.

Notes:
{notes}"""


def parse_study_json(text: str) -> dict:
    """Gemini's reply as {"cards": [...], "quiz": [...]}, tolerating code fences and stray text."""
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE)
    start = text.find("{")
    if start < 0:
        raise ToolError("Gemini did not return study material I could read; please try again.")
    try:  # the first complete JSON object; anything after it is ignored
        data, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError as exc:
        logger.warning("Unreadable study material: %s ... %s", text[:200], text[-200:])
        raise ToolError("Gemini's study material was malformed; please try again.") from exc
    cards = [{"q": str(c["q"]).strip(), "a": str(c["a"]).strip()} for c in data.get("cards", [])
             if isinstance(c, dict) and c.get("q") and c.get("a")]
    quiz = [{"q": str(q["q"]).strip(), "right": str(q["right"]).strip(), "wrong": [str(w).strip() for w in q["wrong"]][:3]}
            for q in data.get("quiz", [])
            if isinstance(q, dict) and q.get("q") and q.get("right") and isinstance(q.get("wrong"), list) and len(q["wrong"]) >= 3]
    if not cards and not quiz:
        raise ToolError("Gemini returned no usable cards or questions.")
    return {"cards": cards, "quiz": quiz}


@ToolRegistry.register("make_study_set")
class MakeStudySetTool(SebasTool):
    name = "make_study_set"
    description = (
        "Make flashcards and quiz questions for a subject from the user's notes (Documents › "
        "Sebas Notes, matched by subject, or a specific .md/.txt/.pdf file). Uses Gemini once; "
        "afterwards reviewing and quizzing work offline. Existing progress on the same cards is kept."
    )
    parameters = {
        "type": "object",
        "properties": {
            "subject": {"type": "string", "description": "The subject, e.g. 'DBMS'."},
            "file": {"type": "string", "description": "Optional path of a notes file to use instead."},
            "cards": {"type": "integer", "description": "How many flashcards (default 20)."},
        },
        "required": ["subject"],
    }
    timeout_seconds = 180.0

    def run(self, subject: str, file: str = "", cards: int = 20) -> str:
        subject = " ".join(subject.split())
        sources = [Path(file.strip().strip('"'))] if file.strip() else find_notes(subject)
        if not sources:
            raise ToolError(f"I found no notes about {subject} in Documents › Sebas Notes. "
                            "Record a lecture, or give me the path of a notes file.")
        notes = "\n\n---\n\n".join(read_source(p) for p in sources)[:60_000]
        if len(notes.split()) < 60:
            raise ToolError("Those notes are too short to make study material from.")
        n = max(5, min(int(cards or 20), 40))
        from custom_tools.assist import gemini_once

        made = parse_study_json(gemini_once(
            [STUDY_PROMPT.format(subject=subject, notes=notes, cards=n, quiz=max(5, n // 2))],
            need="Making flashcards", timeout_ms=150_000, json_mode=True))
        with _lock:
            try:
                old = load_deck(subject) if deck_path(subject).exists() else {}
            except ToolError:
                old = {}
            progress = {c["q"]: c for c in old.get("cards", [])}
            now = datetime.now().isoformat(timespec="minutes")
            deck = {
                "subject": old.get("subject", subject),
                "sources": [str(p) for p in sources],
                "made": now,
                "cards": [progress.get(c["q"]) or {"id": uuid.uuid4().hex[:8], **c, "box": 0, "due": now}
                          for c in made["cards"]],
                "quiz": made["quiz"],
                "best_quiz": old.get("best_quiz"),
            }
            save_deck(deck)
        names = ", ".join(p.name for p in sources)
        return (f"Made {len(deck['cards'])} flashcards and {len(deck['quiz'])} quiz questions on {deck['subject']}, "
                f"from {names}. Say 'review my {deck['subject']} flashcards' or 'quiz me on {deck['subject']}'.")


class _OpenOnInterface(SebasTool):
    """Opens a study panel on the laptop's interface."""

    acts_on_laptop = True
    view = ""
    parameters = {"type": "object", "properties": {"subject": {"type": "string", "description": "The subject."}},
                  "required": ["subject"]}

    def run(self, subject: str) -> str:
        deck = load_deck(subject)
        emit("study", view=self.view, subject=deck["subject"])
        return self.describe(deck)

    def describe(self, deck: dict) -> str:
        raise NotImplementedError


@ToolRegistry.register("review_flashcards")
class ReviewFlashcardsTool(_OpenOnInterface):
    name = "review_flashcards"
    view = "cards"
    description = "Open a flashcard review (spaced repetition) for a subject on the laptop's interface."

    def describe(self, deck: dict) -> str:
        due = len(due_cards(deck))
        return (f"Opened the {deck['subject']} flashcards on the interface: {due} of {len(deck['cards'])} due."
                if due else f"No {deck['subject']} cards are due just now; I opened the deck for extra practice.")


@ToolRegistry.register("quiz_me")
class QuizMeTool(_OpenOnInterface):
    name = "quiz_me"
    view = "quiz"
    description = "Open a multiple-choice quiz on a subject, from the user's study set, on the laptop's interface."

    def describe(self, deck: dict) -> str:
        if not deck.get("quiz"):
            raise ToolError(f"The {deck['subject']} study set has no quiz questions; ask me to make it again.")
        return f"The {deck['subject']} quiz is on the interface: {min(10, len(deck['quiz']))} questions."


@ToolRegistry.register("list_study_sets")
class ListStudySetsTool(SebasTool):
    name = "list_study_sets"
    description = "List the user's study sets with how many flashcards are due."

    def run(self) -> str:
        decks = list_decks()
        if not decks:
            return "There are no study sets yet."
        return "\n".join(f"- {d['subject']}: {d['cards']} cards ({d['due']} due), {d['quiz']} quiz questions"
                         + (f", best quiz {d['best']}" if d.get("best") else "") for d in decks)


# =========================================================================== for the interface
def snapshot() -> dict[str, Any]:
    return {
        "session": POMODORO.public(),
        "exams": [{"subject": e["subject"], "days": days_until(e)} for e in upcoming_exams()[:4]],
        "focus_today": round(sum(focus_today().values())),
        "decks": list_decks(),
    }


def deck_for_review(subject: str) -> dict:
    deck = load_deck(subject)
    due = due_cards(deck)
    cards = due if due else random.sample(deck["cards"], min(10, len(deck["cards"])))  # extra practice
    return {"subject": deck["subject"], "cards": [{"id": c["id"], "q": c["q"], "a": c["a"]} for c in cards],
            "extra": not due}


def grade(subject: str, card_id: str, verdict: str) -> None:
    with _lock:
        deck = load_deck(subject)
        grade_card(deck, card_id, verdict)
        save_deck(deck)


def quiz_for(subject: str) -> dict:
    deck = load_deck(subject)
    qs = random.sample(deck.get("quiz", []), min(10, len(deck.get("quiz", []))))
    return {"subject": deck["subject"], "questions": [[q["q"], q["right"], q["wrong"]] for q in qs],
            "best": deck.get("best_quiz")}


def record_quiz(subject: str, score: int, total: int) -> None:
    with _lock:
        deck = load_deck(subject)
        best = deck.get("best_quiz")
        if not best or score / max(total, 1) > int(best.split("/")[0]) / max(int(best.split("/")[1]), 1):
            deck["best_quiz"] = f"{score}/{total}"
            save_deck(deck)
