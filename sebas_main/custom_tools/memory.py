"""Long-term memory: facts kept in MEMORY.md, which OpenJarvis adds to every prompt.

The file is plain text at ~/.openjarvis/MEMORY.md (or $OPENJARVIS_HOME), so it
can also be read and edited by hand.
"""

from __future__ import annotations

import threading
from difflib import SequenceMatcher
from pathlib import Path

from openjarvis.core.paths import get_config_dir
from openjarvis.core.registry import ToolRegistry

from custom_tools._base import SebasTool, ToolError

# Keep in step with [system_prompt] memory_max_chars in configs/sebas/config.toml;
# beyond it OpenJarvis truncates the file when building the prompt.
MAX_CHARS = 6000
_lock = threading.Lock()


def memory_path() -> Path:
    return get_config_dir() / "MEMORY.md"


def read_facts() -> list[str]:
    path = memory_path()
    if not path.exists():
        return []
    return [
        line[2:].strip()
        for line in path.read_text("utf-8").splitlines()
        if line.startswith("- ") and line[2:].strip()
    ]


def _write(facts: list[str]) -> None:
    path = memory_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"- {fact}\n" for fact in facts), "utf-8")


@ToolRegistry.register("remember")
class RememberTool(SebasTool):
    name = "remember"
    description = (
        "Save a lasting fact about the user so it is available in every future "
        "conversation: when they ask you to remember something, or state a "
        "durable preference, routine or detail (e.g. 'I prefer metric units'). "
        "Write it as one short third-person sentence. Never store passwords, "
        "tokens or other secrets. Saved facts already appear under 'Agent Memory'."
    )
    parameters = {
        "type": "object",
        "properties": {"fact": {"type": "string", "description": "The fact, in one sentence."}},
        "required": ["fact"],
    }

    def run(self, fact: str) -> str:
        fact = " ".join((fact or "").split())
        if not fact:
            raise ToolError("There was nothing to remember.")
        with _lock:
            facts = read_facts()
            if any(f.lower() == fact.lower() for f in facts):
                return f"Already remembered: {fact}"
            size = sum(len(f) + 3 for f in facts) + len(fact) + 3
            if size > MAX_CHARS:
                raise ToolError(
                    "Memory is full. Ask the user which older facts to forget first."
                )
            _write(facts + [fact])
        return f"Remembered: {fact}"


@ToolRegistry.register("forget")
class ForgetTool(SebasTool):
    name = "forget"
    description = (
        "Remove one remembered fact when the user asks you to forget it or it is "
        "no longer true. Quote the fact as it appears under 'Agent Memory'."
    )
    parameters = {
        "type": "object",
        "properties": {"fact": {"type": "string", "description": "The fact to remove."}},
        "required": ["fact"],
    }

    def run(self, fact: str) -> str:
        target = " ".join((fact or "").split()).lower()
        if not target:
            raise ToolError("Say which fact to forget.")
        with _lock:
            facts = read_facts()
            scored = sorted(
                ((SequenceMatcher(None, target, f.lower()).ratio(), i) for i, f in enumerate(facts)),
                reverse=True,
            )
            if not scored or scored[0][0] < 0.6:
                raise ToolError(f"No remembered fact matches '{fact}'.")
            if len(scored) > 1 and scored[0][0] - scored[1][0] < 0.05:
                options = "; ".join(facts[i] for _, i in scored[:2])
                raise ToolError(f"More than one fact matches. Which one: {options}?")
            removed = facts.pop(scored[0][1])
            _write(facts)
        return f"Forgotten: {removed}"
