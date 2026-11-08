"""Open the Games Room by voice or typing: "Sebas, let's play pong".

Matched on the laptop like the Easter eggs, so it is instant and costs no Gemini
quota. The games themselves (ui/games.js) are hard-coded and need no AI; Sebas's
lines in them are scripted, with anime references for each situation.
"""

from __future__ import annotations

import re

from sebas_events import emit

# game name in ui/games.js -> the ways people (and Whisper) say it
_GAMES = {
    "tictactoe": r"tic\W?t[ae]c\W?t[oe]e?|noughts? (?:and|&|n) crosses|x(?:s)? (?:and|&|n) o(?:s)?",
    "pong": r"pong|table tennis|ping\W?pong",
    "rps": r"rock\W+paper\W+scissors?|jan\W?ken",
    "memory": r"memory(?: match| game)?|match(?:ing)? pairs|pairs",
    "trivia": r"(?:anime )?trivia|(?:anime )?quiz",
    "connect4": r"connect\W?(?:four|4)|four in a row",
    "hangman": r"hang\W?man",
    "snake": r"snakes?",
}
_UNAMBIGUOUS = {"tictactoe", "pong", "rps", "connect4", "hangman"}
_PLAY = re.compile(r"\b(?:play|game|games|challenge|fancy|rematch)\b")
_ROOM = re.compile(r"\b(?:let'?s|shall we|can we|want to|wanna)?\W*play (?:a |some )?games?\b|\bgames? room\b|\bopen (?:the )?games\b|\bi'?m bored\b")

_LINES = {
    "tictactoe": "Noughts and crosses, sir? Very well. I shall try not to be too merciless.",
    "pong": "Table tennis, sir? My reflexes were honed in the Great Tomb. Do keep up.",
    "rps": "Rock, paper, scissors. Gon would choose rock. I shall not say what I choose.",
    "memory": "A test of memory, sir. I remember every guest of Nazarick by name.",
    "trivia": "Anime trivia, sir. Let us see whether you are a true otaku.",
    "connect4": "Connect Four, sir. I see several moves ahead; do try to keep up.",
    "hangman": "Anime hangman, sir. Mind the lantern; it dims with every miss.",
    "snake": "Snake, sir. Do try not to bite yourself; Orochimaru never quite managed it.",
    None: "The Games Room is open, sir. Even the guardians of Nazarick need their leisure.",
}


def check(text: str) -> tuple[str | None, str] | None:
    """(game or None for the menu, Sebas's line) when ``text`` asks for a game; else None."""
    low = text.lower()
    for name, pattern in _GAMES.items():
        # "pong" alone is plainly a game; "quiz" or "pairs" need a word like "play"
        if re.search(rf"\b(?:{pattern})\b", low) and (name in _UNAMBIGUOUS or _PLAY.search(low)):
            return name, _LINES[name]
    if _ROOM.search(low):
        return None, _LINES[None]
    return None


def open_game(name: str | None) -> None:
    emit("game", name=name or "")
