"""Anime Easter eggs: secret phrases with a scripted reply and an interface effect.

Matched on the laptop before anything reaches Gemini, so they answer instantly
and cost no quota. The patterns allow for the ways Whisper tends to spell
names it has never heard ("Ains Oal Gown", "El Psy Congroo").

    "Ainz Ooal Gown"             Nazarick mode on/off (crimson interface, Sebas Tian)
    "El Psy Kongroo"             the Steins;Gate divergence meter
    "Are you merely a butler?"   Black Butler: crimson eyes, "one hell of a butler"
    "What's your power level?"   DBZ: the gauges spike and crack, "over nine thousand"
    "Sharingan"                  Naruto: red eyes with spinning tomoe
(The Konami-code costume lives entirely in the interface.)
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sebas_events import emit


@dataclass(frozen=True)
class Egg:
    name: str
    line: str


_nazarick = False

_PATTERNS = [
    ("nazarick", re.compile(r"\ba[iy]n[sz]?\W{0,3}(?:o+a?l|u+w?a?l|owl|oal|ool)\W{0,3}g[ao]wn\b|\bnazarick\b")),
    ("divergence", re.compile(r"\bel\W{0,2}ps[yi]\W{0,2}[kc]on+g?r[ou]+\b")),
    ("butler", re.compile(r"\b(?:merely|just|only|simply|nothing but)\W+(?:a|one|your)\W+butler\b|"
                          r"\bwhat (?:kind|sort) of (?:a )?butler\b|\bone hell of a butler\b")),
    ("power", re.compile(r"\bpower\W+level\b")),
    ("sharingan", re.compile(r"\bsh?ar[iy]n\W?gan\b")),
]


def check(text: str) -> Egg | None:
    """The Easter egg ``text`` triggers, with Sebas's line; None for ordinary requests."""
    global _nazarick
    low = text.lower()
    for name, pattern in _PATTERNS:
        if not pattern.search(low):
            continue
        if name == "nazarick":
            _nazarick = not _nazarick
            line = ("All hail the Supreme One. Sebas Tian, Head Butler of the Great Tomb of Nazarick, "
                    "awaits your command, Lord Ainz." if _nazarick else
                    "As you wish, my lord. The Tomb shall keep. I return to the household, sir.")
            return Egg("nazarick-on" if _nazarick else "nazarick-off", line)
        return Egg(name, {
            "divergence": "Divergence one point zero four eight five nine six. The worldline holds, sir. "
                          "The Organisation has not found us... yet. El Psy Kongroo.",
            "butler": "I am simply one hell of a butler, sir.",
            "power": "It's over nine thousand! ... I do beg your pardon, sir. The instruments appear to be broken.",
            "sharingan": "Sharingan. Nothing escapes my notice, sir. Least of all your unfinished assignments.",
        }[name])
    return None


def trigger(egg: Egg) -> None:
    """Show the effect in the interface (the caller speaks the line)."""
    emit("egg", name=egg.name)
