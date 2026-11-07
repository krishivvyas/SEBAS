"""A one-way event feed from Sebas's internals to whatever displays them (the UI).

Modules call ``emit("state", state="thinking")`` and never need to know whether
a UI is attached. Without a sink, events are dropped.

Event kinds:
    state       state: idle | listening | thinking | speaking
    transcript  role: user | sebas, text
    tool        phase: start | end, tool, success (end only)
    mic         level: 0..1 (microphone loudness while waiting for "Sebas")
    speech      envelope: [0..1, ...], step: seconds per value (one sentence)
    mode        mode: cloud | local, model
    notice      text
"""

from __future__ import annotations

import logging
from typing import Any, Callable

Sink = Callable[[str, dict[str, Any]], None]
_sink: Sink | None = None          # the interface, if one is open
_listeners: list[Sink] = []        # anything else that wants a copy (Discord)


def set_sink(sink: Sink | None) -> None:
    global _sink
    _sink = sink


def add_listener(listener: Sink) -> None:
    _listeners.append(listener)


def emit(kind: str, **data: Any) -> None:
    for target in ([_sink] if _sink else []) + _listeners:
        try:
            target(kind, data)
        except Exception:  # a display problem must never break Sebas himself
            logging.getLogger(__name__).debug("Event sink failed", exc_info=True)
