"""What Sebas does, as opposed to what he says: one gate and one log.

The gate. A tool marked ``risky`` (hard to undo: deleting, overwriting, closing,
sending) does not run when the model calls it at the laptop. It is parked here
and the model is told to ask for a yes. Only the user's *next* request can
release it: ``answer()`` is consulted before a request reaches the model, so the
model cannot confirm on the user's behalf. Anything other than a yes or a no
drops the parked action. From Discord, the existing remote gate applies instead.

The log. Every action worth a record is appended to
~/.openjarvis/sebas/actions.jsonl (one JSON object per line), so "what did you
do while I was away?" has an answer after the fact.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from datetime import datetime
from typing import Any

from openjarvis.core.paths import get_data_dir

logger = logging.getLogger("sebas.actions")

CONFIRM_SECONDS = 120
_YES = {"yes", "yeah", "yep", "yes please", "yes do it", "confirm", "confirmed", "do it", "go ahead",
        "proceed", "please do", "sure", "yes go ahead", "yes sebas", "affirmative"}
_NO = {"no", "nope", "cancel", "cancel it", "never mind", "nevermind", "don't", "do not", "stop",
       "no thank you", "no thanks", "leave it", "no sebas"}
# Hindi and Gujarati, as the speech model writes them (in their own script or
# in Latin letters). Kept to unmistakable words: an unclear answer is dropped,
# never taken as a yes.
_YES |= {"haan", "han", "haa", "haan ji", "ji haan", "haanji", "theek hai", "thik hai", "kar do", "haan kar do",
         "हाँ", "हां", "हा", "हाँ जी", "हां जी", "जी हाँ", "जी हां", "ठीक है", "कर दो", "हाँ कर दो", "हां कर दो",
         "હા", "હાં", "હા જી", "જી હા", "બરાબર", "કરી દો", "હા કરી દો", "ઠીક છે"}
_NO |= {"nahi", "nahin", "nahi nahi", "mat karo", "rehne do", "rahne do",
        "नहीं", "नही", "ना", "नहीं नहीं", "मत करो", "रहने दो", "नहीं रहने दो",
        "ના", "નહીં", "નહિ", "ના ના", "રહેવા દો", "ના રહેવા દો", "નથી કરવું"}

_lock = threading.Lock()
_pending: dict[str, Any] | None = None


def _log_path():
    return get_data_dir() / "sebas" / "actions.jsonl"


def log(action: str, detail: str, ok: bool = True) -> None:
    """Record something Sebas did. Never raises: a log is not worth a failure."""
    entry = {"at": datetime.now().isoformat(timespec="seconds"), "action": action, "detail": detail[:500], "ok": ok}
    try:
        path = _log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        logger.debug("Could not write the action log", exc_info=True)


def on_day(day: str) -> list[dict[str, Any]]:
    """Every action logged on one day ('YYYY-MM-DD')."""
    try:
        lines = _log_path().read_text("utf-8").splitlines()
    except OSError:
        return []
    found = []
    for line in lines:
        if not line.startswith('{"at": "' + day):
            continue
        try:
            found.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return found


def recent(limit: int = 20) -> list[dict[str, Any]]:
    try:
        lines = _log_path().read_text("utf-8").splitlines()[-limit:]
    except OSError:
        return []
    entries = []
    for line in lines:
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def request(tool: str, params: dict[str, Any], summary: str, on_settled=None) -> str:
    """Park a risky action. Returns what the model is told. ``on_settled(outcome,
    text, ok)`` is called once it is decided: outcome is "yes", "no", "dropped"
    or "lapsed" (a background errand waits on this)."""
    global _pending
    with _lock:
        previous = _pending
        _pending = {"tool": tool, "params": params, "summary": summary, "asked": time.monotonic(),
                    "on_settled": on_settled}
    _settle(previous, "dropped", "")  # a newer request takes its place
    return (
        f"NOT DONE YET. This is hard to undo, so it needs the master's spoken yes: {summary} "
        "Ask him, in one short sentence, whether to proceed. Do not call the tool again and do "
        "not say it is done; his yes will carry it out."
    )


def pending_summary() -> str:
    with _lock:
        return _pending["summary"] if _pending else ""


def _normalise(text: str) -> str:
    # Latin, Devanagari and Gujarati letters with their vowel signs; the danda (।)
    # and punctuation go, so "हाँ।" is a yes like "yes."
    return " ".join(re.sub(r"[^a-z' ऀ-ॣ०-ॿ઀-ૣ૦-૿]", " ", text.lower()).split())


def answer(text: str) -> str | None:
    """The user's next words after a parked action. A yes runs it and returns the
    result; a no cancels it; anything else drops it and returns None, so the
    request goes to the model as usual."""
    global _pending
    with _lock:
        pending, _pending = _pending, None
    if pending is None:
        return None
    said = _normalise(text)
    if said in _NO:
        log(pending["tool"], f"cancelled: {pending['summary']}", ok=False)
        _settle(pending, "no", "")
        return "Very good, sir. I have left it as it was."
    if said not in _YES:
        _settle(pending, "dropped", "")
        return None
    if time.monotonic() - pending["asked"] > CONFIRM_SECONDS:
        _settle(pending, "lapsed", "")
        return "That request has lapsed, sir. Do ask again should you still wish it."
    from openjarvis.core.registry import ToolRegistry

    result = ToolRegistry.create(pending["tool"]).run_now(**pending["params"])
    log(pending["tool"], f"{pending['summary']} -> {result.content}", ok=result.success)
    _settle(pending, "yes", result.content, result.success)
    return f"Done, sir. {result.content}" if result.success else f"I regret it did not succeed, sir. {result.content}"


def _settle(pending: dict[str, Any] | None, outcome: str, text: str, ok: bool = False) -> None:
    callback = pending.get("on_settled") if pending else None
    if callback is not None:
        try:
            callback(outcome, text, ok)
        except Exception:
            logger.exception("A confirmation callback failed")
